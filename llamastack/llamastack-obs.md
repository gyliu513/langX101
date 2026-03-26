## Llama Stack Observability Deep Dive

Llama Stack's observability architecture uses a **dual-layer approach of Auto Instrumentation + Manual Instrumentation**, unified through OpenTelemetry's data pipeline, covering full observability from the HTTP transport layer to the LLM business logic layer.

---

### 1. Infrastructure: Data Pipeline Architecture

```
┌──────────────┐
│  Llama Stack │──┐
│  Server      │  │  OTLP     ┌───────────────────┐   scrape    ┌──────────────┐
└──────────────┘  ├─────────►│  OTel Collector     │◄───────────│  Prometheus  │
┌──────────────┐  │  :4318   │  :4317 (gRPC)       │   :9464    │  :9090       │
│  Llama Stack │──┘          │  :4318 (HTTP)       │            └──────────────┘
│  Client      │             └────────┬────────────┘                   ▲
└──────────────┘                      │ OTLP                           │
                                      ▼                           datasource
                             ┌────────────────┐                        │
                             │  Jaeger         │              ┌──────────────┐
                             │  :16686 (UI)    │◄────────────│  Grafana     │
                             └────────────────┘  datasource   │  :3000 (UI)  │
                                                              └──────────────┘
```

Startup procedure:

```bash
# 1. Start telemetry backends (Jaeger + OTel Collector + Prometheus + Grafana)
./scripts/telemetry/setup_telemetry.sh

# 2. Install OTel Python packages
uv pip install opentelemetry-distro opentelemetry-exporter-otlp
uv run opentelemetry-bootstrap -a requirements | uv pip install --requirement -

# 3. Wrap the server startup with opentelemetry-instrument
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_SERVICE_NAME=llama-stack-server
uv run opentelemetry-instrument llama stack run starter
```

---

### 2. Auto Instrumentation

**How it works:** `opentelemetry-instrument` is a CLI wrapper that automatically discovers installed instrumentor libraries (via `opentelemetry-bootstrap`) at startup and injects traces and metrics through monkey-patching — without modifying any llama-stack source code.

**Automatically collected metrics:**

| Layer | Metric | Instrumentor Library |
|-------|--------|---------------------|
| **HTTP Server (FastAPI)** | `http_server_duration_milliseconds` — request latency histogram | `opentelemetry-instrumentation-fastapi` |
| | `http_server_active_requests` — currently active request count | |
| | `http_server_request_size_bytes` — request body size | |
| | `http_server_response_size_bytes` — response body size | |
| **GenAI Client** | `gen_ai_client_token_usage` — input/output token usage (grouped by model) | `opentelemetry-instrumentation-openai` |
| **HTTP Client** | outbound HTTP call traces (calls to inference providers) | `opentelemetry-instrumentation-httpx` |
| **Database** | SQL query traces (SQLAlchemy, asyncpg, sqlite3) | `opentelemetry-instrumentation-sqlalchemy` |

**Automatically generated traces:** A single inference request automatically produces a chain of correlated spans:

```
HTTP Server span (FastAPI)
  └── HTTP Client span (httpx → OpenAI API)
       └── GenAI span (token usage, model, finish_reason)
```

**Corresponding Grafana Dashboard:** `llama-stack-dashboard.json` — displays Prompt Tokens, Completion Tokens, HTTP Duration P95/P99, Total Requests, Request/Response Size. All panel data comes **entirely from auto instrumentation**, requiring zero code changes.

**Known issue:** When auto instrumentation is enabled, low-level database driver instrumentors (e.g., `asyncpg`, `sqlite3`) and the SQLAlchemy ORM instrumentor activate simultaneously, causing duplicate spans. Solution:

```bash
export OTEL_PYTHON_DISABLED_INSTRUMENTATIONS="sqlite3,asyncpg"
```

**Limitations:** Auto instrumentation can only observe the generic HTTP/DB/GenAI layers. It **cannot capture** LLM-specific business logic (tool invocation latency, vector retrieval throughput, inference TTFT, API-level method differentiation, etc.) — this is why manual instrumentation exists.

---

### 3. Manual Instrumentation

#### 3.1 Foundation: `telemetry/__init__.py` — MeterProvider Initialization

This is the **foundation switch** for all manual metrics.

**Why it's needed:** The OpenTelemetry SDK follows a **"safe by default"** design principle — it uses a no-op MeterProvider by default. Any Meter returned by `metrics.get_meter()` and any instruments created (Counter, Histogram, etc.) are empty implementations where `.record()` / `.add()` do nothing, with zero performance overhead.

This design solves the **library vs. application separation problem**:
- **Library (llama-stack)** freely adds instrumentation code without needing `if telemetry_enabled:` checks
- **Application (the operator)** decides whether to enable via environment variables — set `OTEL_EXPORTER_OTLP_ENDPOINT` to enable, leave it unset for silent operation
- No crashes from missing telemetry backends

Core logic in `telemetry/__init__.py`:

```python
def setup_telemetry():
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otlp_endpoint:
        return  # → all manual metrics remain no-op

    exporter = OTLPMetricExporter(endpoint=f"{otlp_endpoint}/v1/metrics")
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=export_interval_ms)

    resource = Resource(attributes={"service.name": service_name})
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)  # ← after this, all get_meter() calls return real Meters

# Automatically executed on module import
setup_telemetry()
```

**Data flow:**

```
setup_telemetry() sets the global MeterProvider
         │
         ▼
metrics.get_meter("llama_stack.xxx") in various *_metrics.py files
         │  → obtains a real Meter (not no-op)
         ▼
meter.create_histogram() / create_counter()
         │  → creates real instruments
         ▼
instrument.record() / .add() in Router/Middleware
         │  → data is aggregated by MeterProvider
         ▼
PeriodicExportingMetricReader collects + exports every 60s
         │
         ▼
OTel Collector → Prometheus → Grafana
```

#### 3.2 Manual Metrics Code Pattern

All manual metrics follow a consistent three-layer pattern:

```
telemetry/constants.py          → defines metric name constants
telemetry/*_metrics.py          → creates Meter + Instrument objects + attribute helpers
core/routers/*.py or middleware → actually calls .record() / .add() for recording
```

#### 3.3 Five Metrics PRs in Detail

**PR #4904: Tool Runtime Metrics**

| Metric | Type | Purpose |
|--------|------|---------|
| `llama_stack.tool_runtime.invocations_total` | Counter | Total tool invocation count |
| `llama_stack.tool_runtime.duration_seconds` | Histogram | Tool invocation latency distribution |

Attributes: `tool_name`, `tool_group`, `provider`, `status`

Recording location: `invoke_tool()` method in `core/routers/tool_runtime.py`:

```python
# On success
result = await provider.invoke_tool(tool_name=tool_name, kwargs=kwargs, authorization=authorization)
duration = time.perf_counter() - start_time
success_attrs = {**metric_attrs, "status": "success"}
tool_invocations_total.add(1, success_attrs)
tool_duration.record(duration, metric_attrs)

# On failure
except Exception:
    duration = time.perf_counter() - start_time
    error_attrs = {**metric_attrs, "status": "error"}
    tool_invocations_total.add(1, error_attrs)
    tool_duration.record(duration, error_attrs)
    raise
```

Dashboard: `llama-stack-tool-runtime-metrics.json` — Tool Invocation Rate, Success/Error Pie, Latency P50/P95/P99, Error Rate by Provider, Invocations by Tool Group.

---

**PR #5096: Vector IO Metrics**

| Metric | Type | Purpose |
|--------|------|---------|
| `llama_stack.vector_io.inserts_total` | Counter | Vector insert count |
| `llama_stack.vector_io.queries_total` | Counter | Vector query count |
| `llama_stack.vector_io.deletes_total` | Counter | Vector delete count |
| `llama_stack.vector_io.stores_total` | Counter | Vector store creation count |
| `llama_stack.vector_io.files_total` | Counter | File attachment count |
| `llama_stack.vector_io.chunks_processed_total` | Counter | Chunks processed count |
| `llama_stack.vector_io.insert_duration_seconds` | Histogram | Insert latency |
| `llama_stack.vector_io.retrieval_duration_seconds` | Histogram | Query latency |

Attributes: `vector_db`, `operation`, `provider`, `status`

Recording location: `core/routers/vector_io.py` — 15+ recording points distributed across insert_chunks, query_chunks, create/delete_vector_store, search_vector_store, attach_file_to_vector_store, etc., following the same pattern as tool runtime.

Dashboard: `llama-stack-vector-io-metrics.json`

---

**PR #5201: API Request Metrics**

| Metric | Type | Purpose |
|--------|------|---------|
| `llama_stack.requests_total` | Counter | Total API request count |
| `llama_stack.request_duration_seconds` | Histogram | API request latency |
| `llama_stack.concurrent_requests` | UpDownCounter | Current concurrent request count |

Attributes: `api`, `method`, `status`, `status_code`

**Key difference from auto instrumentation:** Auto instrumentation's `http_server_duration` only knows the HTTP path (e.g., `/v1/models`) but doesn't know which API method it corresponds to. Manual `requests_total` builds a precise HTTP method+path → API+method mapping at server startup, distinguishing different methods on the same path:

```
GET  /v1/models       → api="models", method="openai_list_models"
POST /v1/models       → api="models", method="register_model"
POST /v1/chat/completions → api="inference", method="openai_chat_completion"
```

Recording location: `RequestMetricsMiddleware` in `core/server/metrics.py` (ASGI middleware):

```python
class RequestMetricsMiddleware:
    async def __call__(self, scope, receive, send):
        route_info = self._resolve_route(http_method, path)
        base_attrs = {"api": route_info.api, "method": route_info.method}

        concurrent_requests.add(1, {"api": route_info.api})
        start_time = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
            status = "success" if status_code < 400 else "error"
        except Exception:
            status = "error"
            raise
        finally:
            duration = time.perf_counter() - start_time
            requests_total.add(1, {**base_attrs, "status": status, "status_code": str(status_code)})
            request_duration_seconds.record(duration, base_attrs)
            concurrent_requests.add(-1, {"api": route_info.api})
```

Registered on the FastAPI app (`core/server/server.py`):

```python
route_to_api = build_route_to_api_map(_ROUTER_FACTORIES, all_routes, impls)
app.add_middleware(RequestMetricsMiddleware, route_to_api=route_to_api)
```

Dashboard: `llama-stack-request-metrics.json`

---

**PR #5255: Responses API Parameter Usage**

| Metric | Type | Purpose |
|--------|------|---------|
| `llama_stack.responses.parameter_usage_total` | Counter | Tracks which optional parameters users explicitly provide |

Attributes: `operation`, `parameter`

Purpose: Helps the team understand API usage patterns and prioritize implementation of frequently used OpenAI-compatible parameters.

Recording location: `providers/inline/responses/builtin/impl.py`:

```python
_meter = metrics.get_meter("llama_stack.responses", version="1.0.0")

_parameter_usage_total = _meter.create_counter(
    name=RESPONSES_PARAMETER_USAGE_TOTAL,
    description="Tracks which optional parameters are explicitly provided in Responses API calls",
    unit="1",
)

_REQUIRED_FIELDS = {"input", "model"}

def _record_parameter_usage(request: CreateResponseRequest, operation: str) -> None:
    declared_fields = set(request.model_fields.keys())
    for field_name in (request.model_fields_set & declared_fields) - _REQUIRED_FIELDS:
        _parameter_usage_total.add(1, {"operation": operation, "parameter": field_name})
```

For example, if a request includes `temperature`, `stream`, and `tools`, the counter records 3 increments.

Dashboard: `llama-stack-responses-metrics.json`

---

**PR #5320: Inference Metrics**

| Metric | Type | Purpose |
|--------|------|---------|
| `llama_stack.inference.duration_seconds` | Histogram | End-to-end inference latency |
| `llama_stack.inference.time_to_first_token_seconds` | Histogram | Time to first token (streaming only) |
| `llama_stack.inference.tokens_per_second` | Histogram | Output throughput |

Attributes: `model`, `provider`, `stream`, `status`

Metric definitions (`telemetry/inference_metrics.py`):

```python
meter = metrics.get_meter("llama_stack.inference", version="1.0.0")

inference_duration: Histogram = meter.create_histogram(
    name=INFERENCE_DURATION,
    description="Duration of inference requests from start to completion",
    unit="s",
)
inference_time_to_first_token: Histogram = meter.create_histogram(
    name=INFERENCE_TIME_TO_FIRST_TOKEN,
    description="Time from request start to first content token (streaming only)",
    unit="s",
)
inference_tokens_per_second: Histogram = meter.create_histogram(
    name=INFERENCE_TOKENS_PER_SECOND,
    description="Output token throughput (completion tokens / duration)",
)
```

Recording location: `core/routers/inference.py` — two paths:

**Non-streaming path:**

```python
start_time = time.perf_counter()
status = "success"
try:
    response = await self._nonstream_openai_chat_completion(provider, params)
except Exception:
    status = "error"
    raise
finally:
    duration = time.perf_counter() - start_time
    attrs = create_inference_metric_attributes(
        model=request_model_id, provider=provider.__provider_id__,
        stream=False, status=status,
    )
    inference_duration.record(duration, attributes=attrs)

if response.usage and response.usage.completion_tokens and duration > 0:
    tokens_per_sec = response.usage.completion_tokens / duration
    inference_tokens_per_second.record(tokens_per_sec, attributes=...)
```

**Streaming path:**

```python
start_time = time.perf_counter()
first_token_time: float | None = None
completion_tokens: int | None = None
status = "success"

try:
    async for chunk in response:
        if choice_delta.delta:
            delta = choice_delta.delta
            if delta.content:
                if first_token_time is None:
                    first_token_time = time.perf_counter()  # capture first token time

        if chunk.usage and chunk.usage.completion_tokens:
            completion_tokens = chunk.usage.completion_tokens  # from the last chunk

        yield chunk
except Exception:
    status = "error"
    raise
finally:
    duration = time.perf_counter() - start_time
    attrs = create_inference_metric_attributes(
        model=fully_qualified_model_id, provider=provider_id,
        stream=True, status=status,
    )
    inference_duration.record(duration, attributes=attrs)

    if first_token_time is not None:
        ttft = first_token_time - start_time
        inference_time_to_first_token.record(ttft, attributes=attrs)

    if completion_tokens and duration > 0:
        tokens_per_sec = completion_tokens / duration
        inference_tokens_per_second.record(tokens_per_sec, attributes=attrs)
```

**Key dependency — automatic `include_usage` injection:** Streaming `tokens_per_second` depends on the provider returning `usage.completion_tokens` in the final chunk, which requires `stream_options: {"include_usage": true}` in the request. The code is in `providers/utils/inference/openai_compat.py`:

```python
def get_stream_options_for_telemetry(stream_options, is_streaming, supports_stream_options):
    if not is_streaming or not supports_stream_options:
        return stream_options

    from opentelemetry import trace
    span = trace.get_current_span()
    if not span or not span.is_recording():
        return stream_options  # OTel not enabled → don't inject

    if stream_options is None:
        return {"include_usage": True}
    return {**stream_options, "include_usage": True}  # OTel enabled → auto-inject
```

**Why Histogram instead of Counter/Gauge:** Duration and TTFT are latency metrics that need distribution information (P50/P95/P99), which Histogram natively supports through bucket aggregation. `tokens_per_second` is an instantaneous per-request value (not a continuously changing state), and using Histogram allows queries like "90% of requests have throughput > 30 tok/s".

**Prometheus naming caveat:** Initially `tokens_per_second` was configured with `unit="{token}/s"`, and the OTLP-to-Prometheus exporter automatically appended a `_per_second` suffix, resulting in the metric name `tokens_per_second_per_second`. The fix was to remove the `unit` parameter entirely, since the metric name already contains the unit information.

Dashboard: `llama-stack-inference-metrics.json` — 14 panels across 5 sections (Overview, Duration, TTFT, Throughput, Provider Comparison).

---

#### 3.4 Pre-existing Manual Traces/Spans (Before the Five PRs)

The llama-stack team had already established tracing infrastructure before the metrics PRs, primarily focused on Safety and Tool execution:

**Safety Shield Tracing:**

`core/routers/safety.py` creates a tracer and creates spans in `run_shield()`:

```python
tracer = trace.get_tracer(__name__)

class SafetyRouter(Safety):
    async def run_shield(self, request: RunShieldRequest) -> RunShieldResponse:
        with tracer.start_as_current_span(name=safety_span_name(request.shield_id)):
            provider = await self.routing_table.get_provider_impl(request.shield_id)
            response = await provider.run_shield(request)
            safety_request_span_attributes(request.shield_id, request.messages, response)
        return response
```

`telemetry/helpers.py` sets span attributes:

```python
def safety_request_span_attributes(shield_id, messages, response):
    span = trace.get_current_span()
    span.set_attribute(SAFETY_REQUEST_SHIELD_ID_ATTRIBUTE, shield_id)
    span.set_attribute(SAFETY_REQUEST_MESSAGES_ATTRIBUTE, messages_json)

    if response.violation:
        span.set_attribute(SAFETY_RESPONSE_METADATA_ATTRIBUTE, metadata_json)
        span.set_attribute(SAFETY_RESPONSE_USER_MESSAGE_ATTRIBUTE, response.violation.user_message)
        span.set_attribute(SAFETY_RESPONSE_VIOLATION_LEVEL_ATTRIBUTE, response.violation.violation_level.value)
```

Each `run_shield()` call creates a span recording the shield ID, input messages, and violation results. The complete safety check trace chain is visible in Jaeger.

**Tool Executor Tracing:**

`providers/inline/responses/builtin/responses/tool_executor.py`:

```python
tracer = trace.get_tracer(__name__)

# MCP tool invocation
with tracer.start_as_current_span("invoke_mcp_tool", attributes=attributes):
    ...

# Regular tool invocation
with tracer.start_as_current_span("invoke_tool", attributes=attributes):
    ...
```

`providers/inline/responses/builtin/responses/streaming.py`:

```python
tracer = trace.get_tracer(__name__)

# List MCP tools
with tracer.start_as_current_span("list_mcp_tools", attributes=attributes):
    ...
```

**OTel Context Propagation:**

`core/task.py` — ensures spans created in background tasks are correctly associated with the original request's trace:

```python
@dataclass
class RequestContext:
    otel_ctx: otel_context.Context
    provider_data: Any

def capture_request_context() -> RequestContext:
    return RequestContext(
        otel_ctx=otel_context.get_current(),
        provider_data=PROVIDER_DATA_VAR.get(),
    )

@contextmanager
def activate_request_context(ctx: RequestContext):
    otel_token = otel_context.attach(ctx.otel_ctx)
    provider_token = PROVIDER_DATA_VAR.set(ctx.provider_data)
    try:
        yield
    finally:
        PROVIDER_DATA_VAR.reset(provider_token)
        otel_context.detach(otel_token)

def create_detached_background_task(coro):
    # Clear context before creating task to prevent background workers
    # from permanently inheriting the request's trace identity
    otel_token = otel_context.attach(otel_context.Context())
    provider_token = PROVIDER_DATA_VAR.set(None)
    try:
        task = asyncio.create_task(coro)
    finally:
        PROVIDER_DATA_VAR.reset(provider_token)
        otel_context.detach(otel_token)
    return task
```

---

### 4. Auto vs. Manual Comparison Summary

| | Auto Instrumentation | Manual Instrumentation |
|---|---|---|
| **Code changes** | None (`opentelemetry-instrument` startup is sufficient) | Requires recording points in routers/middleware |
| **Activation method** | `opentelemetry-instrument` CLI wrapper | `setup_telemetry()` in `telemetry/__init__.py` + environment variables |
| **Coverage** | HTTP layer, DB layer, GenAI client generic metrics | LLM business-specific metrics (tool invocations, vector operations, inference performance, API method-level) |
| **Metric granularity** | By HTTP path/method | By business dimensions: model, provider, tool_name, api, method, etc. |
| **Typical metrics** | `http_server_duration`, `gen_ai_client_token_usage` | `inference.tokens_per_second`, `tool_runtime.invocations_total`, `requests_total` |
| **Traces** | Automatically generated span chains (HTTP → provider → DB) | Manually created spans (safety shield, tool execution, MCP) |
| **Overhead when disabled** | Instrumentor libraries are not activated if not installed | no-op MeterProvider, zero overhead |

**In practice, both are enabled simultaneously and work complementarily:**
- Auto instrumentation provides baseline HTTP/trace/GenAI observability
- Manual instrumentation adds LLM-specific business metrics and spans on top
- Both types of data are exported through the same OTLP pipeline to OTel Collector → Prometheus + Jaeger → Grafana (6 dashboards)

---

### 5. Prometheus Query Examples

```bash
# P50 Tokens Per Second (median inference throughput)
curl -s --get 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=histogram_quantile(0.50, sum by (le) (rate(llama_stack_llama_stack_inference_tokens_per_second_bucket[5m])))'

# P95 Inference Duration
curl -s --get 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=histogram_quantile(0.95, sum by (le) (rate(llama_stack_llama_stack_inference_duration_seconds_bucket[5m])))'

# P95 Time to First Token (streaming only)
curl -s --get 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=histogram_quantile(0.95, sum by (le) (rate(llama_stack_llama_stack_inference_time_to_first_token_seconds_bucket{stream="true"}[5m])))'

# All inference metric values
curl -s --get 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query={__name__=~"llama_stack_llama_stack_inference.*_count|llama_stack_llama_stack_inference.*_sum"}' \
  | python3 -c "
import sys,json
for item in json.load(sys.stdin)['data']['result']:
    name = item['metric']['__name__']
    stream = item['metric'].get('stream','')
    val = item['value'][1]
    print(f'{name} stream={stream} => {val}')
"
```

---

### 6. Global View: All Manual Instrumentation Locations

| Function | File | Type | Origin |
|----------|------|------|--------|
| MeterProvider initialization | `telemetry/__init__.py` | Setup | Pre-existing |
| Metric name constants | `telemetry/constants.py` | Constants | Pre-existing + extended by 5 PRs |
| Safety span attribute helper | `telemetry/helpers.py` | Trace helper | Pre-existing |
| Safety tracing | `core/routers/safety.py` | Trace | Pre-existing |
| Tool executor tracing | `responses/tool_executor.py` | Trace | Pre-existing |
| Streaming tracing | `responses/streaming.py` | Trace | Pre-existing |
| OTel context propagation | `core/task.py` | Context | Pre-existing |
| Conditional usage injection | `providers/utils/inference/openai_compat.py` | Trace check | Pre-existing |
| Tool runtime metric definitions | `telemetry/tool_runtime_metrics.py` | Metrics | PR #4904 |
| Tool runtime recording | `core/routers/tool_runtime.py` | Recording | PR #4904 |
| Vector IO metric definitions | `telemetry/vector_io_metrics.py` | Metrics | PR #5096 |
| Vector IO recording | `core/routers/vector_io.py` | Recording | PR #5096 |
| Request metrics + middleware | `core/server/metrics.py` | Metrics + Middleware | PR #5201 |
| Middleware registration | `core/server/server.py` | Registration | PR #5201 |
| Responses parameter metrics | `responses/builtin/impl.py` | Metrics + Recording | PR #5255 |
| Inference metric definitions | `telemetry/inference_metrics.py` | Metrics | PR #5320 |
| Inference recording | `core/routers/inference.py` | Recording | PR #5320 |
