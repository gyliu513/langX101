# Ollama + OpenTelemetry Demo

This document explains how to configure the environment, run the test programs, and view observability data in Jaeger and Prometheus.

---

## Table of Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Environment Setup](#environment-setup)
- [Running the Test Programs](#running-the-test-programs)
- [Viewing Results](#viewing-results)
- [Approach Comparison](#approach-comparison)

---

## Architecture

```
Python Program
(ollama_otel.py / ollama_otel_auto.py)
        │
        │ OTLP gRPC (port 4317)
        ▼
OTel Collector (localhost:4317)
        ├── Traces ──► Jaeger (localhost:16686)
        ├── Traces ──► Zipkin (localhost:9411)
        └── Metrics ► Prometheus (localhost:9090)
                              └── Grafana (localhost:3000)

Ollama (localhost:11434)  ◄── OpenAI-compatible API calls
```

**Data flow:**

1. The Python program sends chat completion requests to the local Ollama instance via its OpenAI-compatible API.
2. The OTel SDK (or the `opentelemetry-instrument` CLI) collects traces and metrics — manually or automatically — and exports them via OTLP gRPC to the OTel Collector.
3. The OTel Collector forwards traces to Jaeger and Zipkin, and exposes metrics for Prometheus to scrape.

---

## Prerequisites

| Component | Notes |
|-----------|-------|
| Python 3.12+ | Installed locally |
| Ollama | Running locally with at least one model pulled |
| Docker & Docker Compose | Required to run the backend services |

Verify that Ollama is running and has available models:

```bash
curl http://localhost:11434/api/tags
```

This demo uses `llama3.2:3b`. Pull it first if it is not already available:

```bash
ollama pull llama3.2:3b
```

---

## Environment Setup

### 1. Start Backend Infrastructure

```bash
cd otel/demo
docker compose up -d
```

Services and their ports after startup:

| Service | Port | Description |
|---------|------|-------------|
| OTel Collector | 4317 (gRPC), 4318 (HTTP) | Receives OTLP data |
| Jaeger | 16686 | Trace visualization UI |
| Zipkin | 9411 | Trace visualization UI (alternative) |
| Prometheus | 9090 | Metrics query |
| Grafana | 3000 | Metrics visualization dashboard |

Verify all services are running:

```bash
docker ps
# All containers should show "Up" status
```

### 2. Create a Python Virtual Environment

```bash
cd otel/demo
python3 -m venv .venv
```

### 3. Install Dependencies

**For the manual instrumentation version (`ollama_otel.py`):**

```bash
.venv/bin/pip install \
  openai \
  opentelemetry-sdk \
  opentelemetry-exporter-otlp-proto-grpc \
  opentelemetry-api
```

**For the auto instrumentation version (`ollama_otel_auto.py`), additionally install:**

```bash
.venv/bin/pip install \
  opentelemetry-instrumentation-openai \
  opentelemetry-distro
```

Package descriptions:

- `opentelemetry-instrumentation-openai`: Maintained by Traceloop. Automatically intercepts all OpenAI SDK API calls and produces spans following the GenAI semantic conventions — no changes to business logic required.
- `opentelemetry-distro`: Provides the `opentelemetry-instrument` CLI. Automatically injects TracerProvider and MeterProvider at process startup based on environment variables — no SDK initialization code needed in your program.

---

## Running the Test Programs

### Method 1: Manual Instrumentation

**File: `ollama_otel.py`**

OTel SDK initialization, span creation, and metrics recording are all done explicitly in code. No environment variables are required — just run it directly.

```bash
cd otel/demo
.venv/bin/python ollama_otel.py
```

Key configuration constants in the code:

```python
OTEL_ENDPOINT    = "http://localhost:4317"     # OTel Collector gRPC address
OLLAMA_BASE_URL  = "http://localhost:11434/v1" # Ollama OpenAI-compatible API
MODEL            = "llama3.2:3b"
SERVICE_NAME     = "ollama-chat-demo"          # Service name shown in Jaeger
```

Metrics collected manually:

| Metric | Type | Description |
|--------|------|-------------|
| `ollama.chat.requests` | Counter | Total number of requests |
| `ollama.chat.latency_ms` | Histogram | Response latency in milliseconds |
| `ollama.chat.prompt_tokens` | Counter | Total prompt (input) token count |
| `ollama.chat.completion_tokens` | Counter | Total completion (output) token count |

Span attributes collected manually:

| Attribute | Description |
|-----------|-------------|
| `model` | Model name used for the request |
| `latency_ms` | End-to-end request latency |
| `llm.usage.prompt_tokens` | Number of prompt tokens |
| `llm.usage.completion_tokens` | Number of completion tokens |
| `llm.usage.total_tokens` | Total tokens consumed |

---

### Method 2: Auto Instrumentation

**File: `ollama_otel_auto.py`**

The Python file contains no OTel code whatsoever. All instrumentation is injected by the `opentelemetry-instrument` CLI at process startup.

**Step 1: Set environment variables**

```bash
export OTEL_SERVICE_NAME=ollama-chat-auto
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_TRACES_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=otlp
```

**Step 2: Run via the CLI**

```bash
.venv/bin/opentelemetry-instrument python ollama_otel_auto.py
```

At startup, `opentelemetry-instrument` automatically discovers and loads all installed instrumentation packages (including `opentelemetry-instrumentation-openai`) and configures TracerProvider and MeterProvider from the environment variables above.

Span attributes collected automatically (GenAI semantic conventions):

| Attribute | Description |
|-----------|-------------|
| `gen_ai.system` | AI system identifier |
| `gen_ai.request.model` | Requested model name |
| `gen_ai.usage.prompt_tokens` | Number of prompt tokens |
| `gen_ai.usage.completion_tokens` | Number of completion tokens |

---

## Viewing Results

### Jaeger — View Traces

Open in browser: **http://localhost:16686**

1. Select `ollama-chat-demo` (manual) or `ollama-chat-auto` (auto) from the **Service** dropdown.
2. Click **Find Traces** to list all recorded traces.
3. Click any trace to inspect span details and all captured attributes.

### Prometheus — View Metrics

Open in browser: **http://localhost:9090**

Useful PromQL queries for the manual instrumentation version:

```promql
# Total request count
ollama_chat_requests_total

# P99 latency
histogram_quantile(0.99, rate(ollama_chat_latency_ms_bucket[5m]))

# Token consumption
ollama_chat_prompt_tokens_total
ollama_chat_completion_tokens_total
```

### Grafana — Dashboard

Open in browser: **http://localhost:3000**  
Default credentials: `admin` / `admin`

The Prometheus datasource is pre-configured. Create custom dashboards using the metrics listed above.

---

## Approach Comparison

| | Manual Instrumentation `ollama_otel.py` | Auto Instrumentation `ollama_otel_auto.py` |
|---|---|---|
| **Run command** | `.venv/bin/python ollama_otel.py` | `.venv/bin/opentelemetry-instrument python ollama_otel_auto.py` |
| **Configuration** | Hardcoded in source | Environment variables |
| **OTel code in app** | Extensive (SDK init + span management) | None (zero OTel imports) |
| **Span name** | `ollama.chat.completion` (custom) | `openai.chat` (framework standard) |
| **Span attribute schema** | Custom fields | GenAI semantic conventions |
| **Best for** | Custom spans, fine-grained control | Fast integration, zero code changes |
| **Extra dependencies** | None | `opentelemetry-instrumentation-openai`, `opentelemetry-distro` |
