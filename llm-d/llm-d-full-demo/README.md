# llm-d Full Stack Observability Demo (No GPU)

This guide deploys the **complete llm-d stack** on a local Kind cluster **without GPU**, covering every key llm-d component: the **Envoy** data-plane proxy, the **EPP / llm-d Router** (Endpoint Picker), the **Inference Payload Processor (IPP)**, **InferencePool / InferenceObjective**, **inference-sim** model servers, the embedded **KV-cache indexer**, the **Workload Variant Autoscaler (WVA)**, and the optional **P/D disaggregation** path. It provides end-to-end observability with **Prometheus** (metrics), **Grafana** (dashboards), and **Jaeger** (distributed tracing).

Each request is observable in Jaeger across **three trace sources** — the **Envoy** proxy, the **IPP**, and the **EPP** — so you can see and time every hop of the gateway. Envoy's own trace contains the `ingress` span plus **both `ext_proc` calls** (to the IPP and the EPP) as child spans, which is what proves the request really flows `Envoy → IPP → EPP → model server`.

> [!IMPORTANT]
> These are **separate traces**, not one stitched trace. The EPP and IPP each root their own trace (the llm-d EPP starts `gateway.request` from the gRPC stream and injects `traceparent` *downstream* to the model server by design; it does not adopt Envoy's `ext_proc` trace context). So you correlate the three by time and by the ext_proc spans in Envoy's trace, not by a shared trace ID. The EPP→model-server hop *would* share a trace ID with a trace-exporting model server (real vLLM with `--otlp-traces-endpoint`); the no-GPU `inference-sim` does not export traces. This behavior was verified on a live Kind cluster — see [Observed tracing behavior](#observed-tracing-behavior).

> Envoy was always part of this stack; it runs as a sidecar inside the `llm-d-epp` pod (the standalone router chart's `proxy`). This revision makes it explicit, adds the IPP as a second `ext_proc` filter in front of the EPP, and enables Envoy's own OpenTelemetry tracing so the proxy hop (and the two ext_proc calls) become visible.

> **中文版本：** [README-zh.md](./README-zh.md)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Kind Cluster (single node, 14 CPU / 23 GB)                                    │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  llm-d namespace                                                         │ │
│  │                                                                          │ │
│  │   Client                                                                 │ │
│  │     │ HTTP :80                                                           │ │
│  │     ▼                                                                    │ │
│  │  ┌─────────────────────────────────────────────┐    ┌─────────────────┐ │ │
│  │  │  llm-d-epp Pod (2 containers)               │    │ payload-        │ │ │
│  │  │                                             │    │ processor (IPP) │ │ │
│  │  │  ┌─────────────┐   gRPC    ┌─────────────┐ │ ext │   :9004 (h2)    │ │ │
│  │  │  │   Envoy     │◄─────────►│    EPP      │ │proc │  body→header    │ │ │
│  │  │  │   Proxy     │  :9002    │  (Endpoint  │ │◄───►│  X-Gateway-     │ │ │
│  │  │  │   :8081     │           │   Picker)   │ │     │  Model-Name     │ │ │
│  │  │  └──┬───────┬──┘           └──────┬──────┘ │     └────────┬────────┘ │ │
│  │  └─────┼───────┼─────────────────────┼────────┘              │          │ │
│  │        │       │ root span + traceparent                     │ OTLP     │ │
│  │        │       └──────────────┐      │ OTLP traces            │          │ │
│  │        │ route to pod         ▼      ▼                        ▼          │ │
│  │        │              ┌────────────────────┐ ◄───────────────┘          │ │
│  │        │              │   OTel Collector   │                            │ │
│  │        │              │      :4317         │──── OTLP ──► ┌───────────┐  │ │
│  │        │              └────────────────────┘             │  Jaeger   │  │ │
│  │        │                        ▲                         │  :16686   │  │ │
│  │        ▼  InferencePool "llm-d" │ OTLP traces             └───────────┘  │ │
│  │   ┌──────────┐  ┌──────────┐    │                                        │ │
│  │   │ decode-0 │  │ decode-1 │────┘   (inference-sim, port 8000)           │ │
│  │   └──────────┘  └──────────┘                                            │ │
│  │                                                                          │ │
│  │   WVA controller ── reads vLLM/queue/KV metrics ──► VariantAutoscaling   │ │
│  │                  ── emits wva_desired_replicas ──► HPA ──► scales decode  │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  llm-d-monitoring namespace                                              │ │
│  │  Prometheus (HTTPS/TLS) ◄── ServiceMonitor (EPP :9090)                   │ │
│  │                         ◄── PodMonitor (model servers :8000)             │ │
│  │  Grafana ◄── 5 llm-d dashboards                                          │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────┘
```

The request path is: **Client → Envoy `:8081` → IPP `ext_proc` `:9004` → EPP `ext_proc` `:9002` → selected decode pod `:8000`.** Envoy calls the IPP first (it enriches the request — e.g. `model` body field → `X-Gateway-Model-Name`), then the EPP (which picks the target pod), then proxies to that pod.

## llm-d Component Coverage

Every key llm-d component is represented. "Baseline" components are wired into the always-on demo; "opt-in" require an extra documented step; "advanced" ship as caveated overlays under [`manifests/optional/`](./manifests/optional/).

| Component | Repo / source | In this demo | No-GPU functional? |
|---|---|---|---|
| **Inference Gateway (Envoy)** | self-managed sidecar (router chart `proxy`) | Baseline — also the trace root | Yes |
| **EPP / llm-d Router** | `llm-d-router` | Baseline | Yes |
| **InferencePool / InferenceObjective** | GAIE + `llm-d.ai` CRDs | Baseline | Yes |
| **Inference Payload Processor (IPP)** | `llm-d-inference-payload-processor` | Baseline (2nd `ext_proc`) | Yes |
| **Model server (vLLM)** | `llm-d-inference-sim` | Baseline | Yes (simulated) |
| **KV-cache indexer** | `llm-d-kv-cache` (library in EPP) | Baseline as prefix-cache index; precise KV-events routing is **advanced** | Prefix index yes; KV-events needs real vLLM |
| **Workload Variant Autoscaler (WVA)** | `llm-d-workload-variant-autoscaler` | Opt-in (Step 9) | Yes (saturation scaling) |
| **Routing sidecar / P/D disaggregation** | `llm-d-routing-sidecar` | Advanced overlay | Topology only (needs vLLM + NIXL) |
| **Prometheus / Grafana** | kube-prometheus-stack | Baseline | Yes |
| **Jaeger / OTel Collector** | upstream | Baseline | Yes |

---

### Component Roles

**`llm-d-epp` Pod — the routing core (2 containers in 1 pod)**

| Container | Role |
|---|---|
| **Envoy Proxy** (`:8081`) | Layer-7 HTTP gateway. Receives every inbound request and calls two `ext_proc` servers in order — first the **IPP** (`:9004`) to enrich the request, then the **EPP** (`:9002`) to ask "which pod should handle this?" Once EPP replies with a target pod IP, Envoy proxies the request directly to that pod and streams the response back. Also has **OpenTelemetry tracing** enabled: it emits an `ingress` span plus one `ext_proc ... Process` child span per processor call, so the IPP and EPP hops are visible and timed from the proxy's side. (Envoy's spans form their own trace; the EPP/IPP do not adopt this context — see [Observed tracing behavior](#observed-tracing-behavior).) |
| **EPP — Endpoint Picker** (`:9002`) | The scheduling brain. Runs a 4-plugin scoring pipeline on every request to select the best decode pod. Also owns the **Prefix Cache Index** (see KV Cache section below). Exposes Prometheus metrics on `:9090` and sends OTLP traces to the OTel Collector. |

**`payload-processor` Pod — the Inference Payload Processor (IPP, `:9004`)**

A separate Deployment running an Envoy `ext_proc` gRPC server (TLS/h2). It sits **before** the EPP in the filter chain and inspects/mutates the request payload. The default plugins extract the request body `model` field into the `X-Gateway-Model-Name` header (`body-field-to-header`) and resolve the base model (`base-model-to-header`), giving the gateway model-aware routing inputs without the EPP having to parse the body. It exports OTLP traces, so it appears as the `llm-d-inference-payload-processor` span in each request's trace. Envoy wires to it with `failure_mode_allow: true`, so an IPP outage degrades (no enrichment, no IPP span) rather than breaking requests.

**EPP 4-plugin scoring pipeline (executed per request, in order):**

1. `queue-scorer` — reads each pod's current queue depth; prefers pods with headroom.
2. `kv-cache-utilization-scorer` — reads each pod's KV cache fill level; avoids pods under memory pressure.
3. `prefix-cache-scorer` — hashes the incoming prompt prefix and checks the in-memory Prefix Cache Index; prefers pods that already have the prefix cached (lower TTFT).
4. `no-hit-lru-scorer` — fallback when no prefix cache hit; routes via Least-Recently-Used across remaining candidates.

**`optimized-baseline-decode` Deployment (2 replicas = `decode-0`, `decode-1`)**

Each pod runs `inference-sim`, a lightweight simulator that mimics the vLLM HTTP API and metric surface without GPU. It:
- Serves `/v1/chat/completions` on port `8000`.
- Exposes vLLM-compatible Prometheus metrics on port `8000` (`vllm:generation_tokens_total`, `vllm:gpu_cache_usage_perc`, etc.).
- Holds its own local **KV cache** in memory and reports utilization back to EPP via metrics.
- Sends OTLP traces to the OTel Collector.

**`InferencePool / llm-d`** — Kubernetes CR that defines which pods belong to the model server pool (selected by label `llm-d.ai/guide=optimized-baseline`). EPP watches this CR to maintain a live view of pod state.

**`InferenceObjective / llm-d-standard`** — Defines QoS priority (`Priority=0`) for flow-control decisions within the EPP scheduler.

**`otel-collector`** — Centralized telemetry hub. Receives OTLP gRPC on `:4317` from both EPP and decode pods. Runs a filter processor to drop noisy `/metrics` HTTP polling spans, batches remaining spans, and forwards to Jaeger.

**`jaeger`** — All-in-one distributed tracing backend (in-memory, dev mode). Stores spans and provides a query UI on `:16686`.

**`ServiceMonitor / llm-d-epp-monitor`** — Prometheus Operator CR. Instructs Prometheus to scrape EPP's `/metrics` on `:9090` every 30 s.

**`PodMonitor / llm-d-model-servers`** — Prometheus Operator CR. Instructs Prometheus to scrape each decode pod's `/metrics` on `:8000` by label selector.

**Prometheus** (HTTPS/TLS, `llm-d-monitoring` ns) — Scrapes both monitors, stores time-series data, and provides a PromQL API.

**Grafana** (`llm-d-monitoring` ns) — Visualizes Prometheus data through 5 pre-built llm-d dashboards.

---

## KV Cache in the Architecture

KV cache operates at **two distinct levels** in this stack, and both are observable:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LEVEL 1 — Per-pod KV Cache  (inside each decode pod)                       │
│                                                                             │
│   decode-0                         decode-1                                 │
│  ┌──────────────────────┐         ┌──────────────────────┐                  │
│  │  inference-sim / vLLM│         │  inference-sim / vLLM│                  │
│  │                      │         │                      │                  │
│  │  ┌────────────────┐  │         │  ┌────────────────┐  │                  │
│  │  │  KV Cache      │  │         │  │  KV Cache      │  │                  │
│  │  │  (paged attn)  │  │         │  │  (paged attn)  │  │                  │
│  │  │  blocks: N     │  │         │  │  blocks: N     │  │                  │
│  │  └───────┬────────┘  │         │  └───────┬────────┘  │                  │
│  │          │ metric     │         │          │ metric     │                  │
│  │  vllm:gpu_cache_      │         │  vllm:gpu_cache_      │                  │
│  │  usage_perc           │         │  usage_perc           │                  │
│  └──────────┼────────────┘         └──────────┼────────────┘                  │
│             │                                 │                             │
│             └──────────┬──────────────────────┘                             │
│                        │ scraped by PodMonitor → Prometheus → Grafana        │
└────────────────────────┼────────────────────────────────────────────────────┘
                         │
                         │ EPP reads KV cache utilization
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  LEVEL 2 — Cross-pod Prefix Cache Index  (inside EPP)                       │
│                                                                             │
│   EPP in-memory state:                                                      │
│                                                                             │
│   Prefix Cache Index (hash map)                                             │
│   ┌──────────────────────────────────────┐                                  │
│   │  hash("What is llm-d?")  → decode-0  │                                  │
│   │  hash("Explain KV cache") → decode-1 │                                  │
│   │  hash("How does Envoy…")  → decode-0  │                                  │
│   │  ...                                 │                                  │
│   └──────────────────────────────────────┘                                  │
│   size tracked as: inference_extension_prefix_indexer_size                  │
│                                                                             │
│   Per-request scoring flow:                                                 │
│                                                                             │
│   New request arrives                                                       │
│        │                                                                    │
│        ▼                                                                    │
│   hash(prompt prefix)                                                       │
│        │                                                                    │
│        ├─── Index HIT  ──► route to pod with warm KV cache                 │
│        │                   (cache reuse → lower TTFT)                       │
│        │                                                                    │
│        └─── Index MISS ──► kv-cache-utilization-scorer picks least-loaded  │
│                            pod → LRU fallback → EPP records new prefix     │
│                            in index for future requests                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

**How KV cache state flows into metrics and routing:**

```
decode pod KV cache fill
        │
        │ /metrics (port 8000)
        ▼
PodMonitor → Prometheus
        │
        │ PromQL (EPP reads via informer/metrics watch)
        ▼
EPP kv-cache-utilization-scorer
        │
        ├─ avoids overloaded pods (high fill → deprioritized)
        └─ combined with prefix-cache-scorer to prefer pods
           with BOTH headroom AND the right cached prefix
```

**Where to observe KV cache in this demo:**

| Signal | Where to look | What it tells you |
|---|---|---|
| `vllm:gpu_cache_usage_perc{pod="decode-0"}` | Prometheus / Grafana "KV Cache" dashboard | Current fill level per pod |
| `inference_extension_prefix_indexer_size` | Prometheus TC-5 query | How many unique prefixes EPP has indexed — grows as traffic diversifies |
| `inference_extension_plugin_duration_seconds{plugin_type="prefix-cache-scorer"}` | Prometheus TC-2 query | Time EPP spends on prefix cache lookups per request |
| Jaeger `gateway.request_orchestration` span | Jaeger UI | Full scheduling decision including which pod was selected and why |

---

## Data Flow Diagram

```
                        ┌─────────────────────────────────────────────────────┐
                        │              OBSERVABILITY DATA FLOWS               │
                        └─────────────────────────────────────────────────────┘

  ┌──────────┐  HTTP    ┌──────────┐  ext_proc  ┌──────────┐  HTTP    ┌──────────┐
  │  Client  │─────────►│  Envoy   │────────────►│   EPP   │─────────►│ decode-N │
  │          │◄─────────│  :8081   │◄────────────│  :9002  │◄─────────│  :8000   │
  └──────────┘  resp    └──────────┘  routing    └──────────┘  resp   └──────────┘
                             │                        │                    │
                             │                        │                    │
              ───────────────┼────── METRICS ─────────┼────────────────────┼──────
                             │                        │                    │
                             │                   ┌────▼────┐          ┌────▼────┐
                             │                   │Service  │          │  Pod    │
                             │                   │Monitor  │          │Monitor  │
                             │                   │(EPP)    │          │(model   │
                             │                   └────┬────┘          │servers) │
                             │                        │               └────┬────┘
                             │                        ▼                    ▼
                             │                   ┌─────────────────────────────┐
                             │                   │   Prometheus (HTTPS :9090)  │
                             │                   │   llm-d-monitoring ns       │
                             │                   └──────────────┬──────────────┘
                             │                                  │
                             │                                  ▼
                             │                   ┌─────────────────────────────┐
                             │                   │     Grafana (:3000)         │
                             │                   │   5 llm-d dashboards        │
                             │                   └─────────────────────────────┘
                             │
              ───────────────┼────── TRACES ──────────────────────────────────
                             │                        │                    │
                             │                   OTLP gRPC            OTLP gRPC
                             │                   (EPP spans)          (sim spans)
                             │                        │                    │
                             │                        ▼                    ▼
                             │                   ┌─────────────────────────────┐
                             │                   │   OTel Collector (:4317)    │
                             │                   │   - filter /metrics spans   │
                             │                   │   - batch & forward         │
                             │                   └──────────────┬──────────────┘
                             │                                  │ OTLP
                             │                                  ▼
                             │                   ┌─────────────────────────────┐
                             │                   │     Jaeger (:16686)         │
                             │                   │   - gateway.request          │
                             │                   │   - gateway.request_         │
                             │                   │     orchestration            │
                             │                   └─────────────────────────────┘
```

### Step-by-Step: Request Path (Control Plane + Data Plane)

```
Step 1  Client → Envoy (:80)
        HTTP POST /v1/chat/completions arrives at Envoy on port 80.
        Envoy starts an `ingress` span (its own trace).

Step 2  Envoy → IPP ext_proc call (gRPC :9004, TLS/h2)
        Envoy first calls the Inference Payload Processor, passing request
        headers/body. The IPP runs its request plugins:
        - body-field-to-header: copies the body `model` field into the
                                X-Gateway-Model-Name header
        - base-model-to-header: resolves the base model name
        The IPP returns the (possibly mutated) headers to Envoy. Envoy records
        this call as an `ext_proc ... Process egress` child span. The IPP also
        emits its own span (service llm-d-inference-payload-processor) in a
        SEPARATE trace.
        failure_mode_allow=true: if the IPP is down, Envoy continues without it.

Step 3  Envoy → EPP ext_proc call (gRPC :9002)
        Envoy then calls the EPP (another `ext_proc ... Process egress` child
        span), which runs the 4-plugin scoring pipeline:

        a. queue-scorer         reads each pod's live queue depth
        b. kv-cache-scorer      reads each pod's KV cache fill level
        c. prefix-cache-scorer  hashes the prompt prefix → looks up Prefix
                                Cache Index → finds pod(s) with warm KV cache
        d. no-hit-lru-scorer    fallback if no prefix match

        EPP returns the winning pod's IP to Envoy and records the request
        in the Prefix Cache Index. The EPP emits gateway.request +
        gateway.request_orchestration in its OWN trace, and injects a fresh
        traceparent DOWNSTREAM toward the selected pod.

Step 4  Envoy → decode pod (:8000)
        Envoy forwards the request directly to the selected pod (bypassing
        any kube-proxy load balancer) and streams the response back to the client.

Step 5  Each component → OTel Collector (OTLP gRPC :4317)
        Envoy (ingress + 2 ext_proc spans), IPP (gateway.request), and EPP
        (gateway.request + gateway.request_orchestration) export their spans.
        These are THREE separate traces (different trace IDs). The decode pod
        (inference-sim) does NOT export traces.

Step 6  OTel Collector processes & forwards
        Filter drops /metrics HTTP-polling spans (noise reduction).
        Batcher groups remaining spans → forwards to Jaeger over OTLP.

Step 7  Jaeger stores + displays
        Spans land in Jaeger's in-memory store. UI at :16686 shows three llm-d
        services (llm-d-envoy-proxy, llm-d-inference-payload-processor,
        llm-d-router/epp). Envoy's trace is the one that shows BOTH ext_proc
        hops in a single view. See "Observed tracing behavior".
```

### Step-by-Step: Metrics Path

```
Every 30 s:

  Prometheus → ServiceMonitor → scrapes EPP :9090/metrics
                                  35+ inference_extension_* counters/histograms
                                  (scheduler latency, plugin durations,
                                   prefix indexer size, running requests…)

  Prometheus → PodMonitor    → scrapes decode-0 :8000/metrics
                             → scrapes decode-1 :8000/metrics
                                  41 vllm:* metrics
                                  (gpu_cache_usage_perc, generation_tokens_total,
                                   e2e_request_latency_seconds, queue_size…)

  Grafana polls Prometheus (PromQL) → renders 5 dashboards in real-time
```

---

## Observed tracing behavior

This section records what the tracing pipeline **actually does**, verified end-to-end on a live Kind cluster (not the idealized version).

**What you get:** three llm-d services in Jaeger, each emitting its own trace per request:

| Service | Spans per request | Notes |
|---|---|---|
| `llm-d-envoy-proxy` | `ingress` + 2× `async ...ExternalProcessor.Process egress` | The two ext_proc spans are the IPP call and the EPP call. This is the one trace that shows both hops together. |
| `llm-d-inference-payload-processor` | `gateway.request` | IPP body/header processing. |
| `llm-d-router/epp` | `gateway.request` + `gateway.request_orchestration` | EPP routing + scheduling decision. |
| `llm-d-model-server` | (none) | `inference-sim:v0.8.0` does not export traces. |

**Why they are NOT one stitched trace:**

- The llm-d EPP starts `gateway.request` from the ext_proc **gRPC stream context** (`llm-d-router` `pkg/epp/handlers/server.go`), so it roots its own trace and never adopts an incoming `traceparent`. It then injects a fresh `traceparent` **downstream** toward the model server. Verified: sending a client `traceparent` does not pull the EPP (or IPP) into that trace.
- The IPP likewise roots its own trace.
- Envoy's OTLP tracing produces an independent trace for the proxy hop. Envoy only writes `traceparent` to the request when forwarding **upstream** (after the ext_proc filters), so the ext_proc servers never receive Envoy's context.

**What it would take to get a single stitched trace** (out of scope for this demo — needs upstream changes): the EPP and IPP ext_proc servers would have to extract the incoming `traceparent` (from the ext_proc request headers) and parent their spans to it. The one stitch that *does* work by design is **EPP → model server** (EPP injects downstream), so swapping the sim for a trace-exporting vLLM (`--otlp-traces-endpoint`) yields a 2-service EPP+model trace.

**Practical takeaway:** to follow a single request, open its **Envoy** trace — it shows the proxy hop plus the IPP and EPP ext_proc calls with timings — then jump to the IPP and EPP services for their internal detail.

---

## Components

| Component | Namespace | Kind | Description |
|---|---|---|---|
| `llm-d-epp` | `llm-d` | Pod (2 containers) | **Envoy proxy** (port 80→8081, trace root, 2× ext_proc) + **EPP** (gRPC ext_proc :9002) |
| `payload-processor` | `llm-d` | Deployment | **IPP** — Envoy ext_proc (:9004, TLS/h2); body→header enrichment |
| `InferencePool/llm-d` | `llm-d` | CR | Watches pods with label `llm-d.ai/guide=optimized-baseline` |
| `InferenceObjective/llm-d-standard` | `llm-d` | CR | Priority=0 flow-control objective |
| `optimized-baseline-decode` | `llm-d` | Deployment (2 replicas) | inference-sim acting as vLLM model server |
| `otel-collector` | `llm-d` | Deployment | Receives OTLP traces, filters noise, forwards to Jaeger |
| `jaeger` | `llm-d` | Deployment | Trace storage + UI (port 16686) |
| `ServiceMonitor/llm-d-epp-monitor` | `llm-d` | CR | Prometheus scrapes EPP metrics (:9090) |
| `PodMonitor/decode` | `llm-d` | CR | Prometheus scrapes model server metrics (:8000) — from `guides/recipes/modelserver/components/monitoring/` |
| `VariantAutoscaling/optimized-baseline-decode` | `llm-d` | CR (opt-in) | **WVA** target; emits `wva_desired_replicas` → HPA |
| Prometheus (HTTPS/TLS) | `llm-d-monitoring` | StatefulSet | Metrics storage |
| Grafana | `llm-d-monitoring` | Deployment | 5 pre-loaded llm-d dashboards |

### Observability Coverage

| Signal | Tool | Sources | Count |
|---|---|---|---|
| **Metrics** | Prometheus + Grafana | EPP (ServiceMonitor) + model servers (PodMonitor) | 35+ EPP + 41 vLLM |
| **Traces** | Jaeger + OTel Collector | Envoy (`llm-d-envoy-proxy`) + IPP (`llm-d-inference-payload-processor`) + EPP (`llm-d-router/epp`); model server does not export (sim) | 3 services / 3 separate traces per request |

---

## Component Internals

### Traffic Generator (`03-traffic-generator.yaml`)

The traffic generator is a `curlimages/curl` container running a shell script stored in a ConfigMap. It is entirely self-contained — no additional tooling required.

**What it does:**

```
ConfigMap: llm-d-traffic-gen-script
  └── generate.sh  (shell script, chmod 0755)
        │
        └── mounted into Deployment llm-d-traffic-gen at /scripts/generate.sh
              └── executed as: /bin/sh /scripts/generate.sh
```

**Script logic (`generate.sh`):**

```sh
# 1. Target: EPP service at http://llm-d-epp:80  (Envoy proxy, port 80)
ROUTER_URL="http://llm-d-epp:80"
MODEL="Qwen/Qwen2.5-0.5B-Instruct"
INTERVAL=3   # seconds between requests

# 2. Fixed prompt pool — 8 prompts, cycled in round-robin order
PROMPTS="What is Kubernetes?|Explain distributed inference.|
         How does KV cache work?|What is prefix caching?|..."

# 3. Main loop
while true; do
  req++
  prompt = PROMPTS[ (req-1) % 8 ]

  # Normal request — POST to /v1/chat/completions
  curl -X POST $ROUTER_URL/v1/chat/completions \
    -d '{"model":"Qwen/...","messages":[...],"max_tokens":64}'

  # Every 8th request: inject a deliberate error (bad model name)
  # → generates a failed trace in Jaeger and increments error rate metrics
  if req % 8 == 0:
    curl -X POST $ROUTER_URL/v1/chat/completions \
      -d '{"model":"nonexistent-model",...}'

  sleep 3
done
```

**Key design choices:**

| Choice | Reason |
|---|---|
| Round-robin over 8 fixed prompts | Generates repeating prefix patterns so `prefix-cache-scorer` gets real cache hits over time |
| Every 8th request is an error | Populates error rate dashboards and error traces in Jaeger without flooding them |
| `max_tokens: 64` | Short enough to complete quickly; long enough to generate meaningful token throughput metrics |
| Sends to `:80` (not `:8081`) | `:80` is the EPP Service's external port mapping to Envoy's `:8081` inside the pod |
| 3-second interval | Produces ~20 req/min — steady signal in Prometheus without overwhelming a Kind cluster |

---

### PodMonitor — how it works

This demo reuses the existing recipe component at `guides/recipes/modelserver/components/monitoring/`, applied with:

```bash
kubectl apply -k guides/recipes/modelserver/components/monitoring/ -n llm-d
```

**The CR it creates:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: decode
  namespace: llm-d
spec:
  selector:
    matchLabels:
      llm-d.ai/role: decode      # ← all decode pods have this label
  podMetricsEndpoints:
  - port: modelserver            # ← named port on the pod (containerPort 8000)
    path: /metrics
    interval: 30s
```

The decode pods in this demo carry both `llm-d.ai/role: decode` and `llm-d.ai/guide: optimized-baseline` labels, so the recipe's role-based selector works without any customization.

**Who is the controller?**

`PodMonitor` is a CRD owned by the **Prometheus Operator** (installed as part of `kube-prometheus-stack`). The Prometheus Operator is a controller that watches PodMonitor and ServiceMonitor CRs and dynamically rewrites Prometheus's scrape configuration — you never edit `prometheus.yml` by hand.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  llm-d-monitoring namespace                                              │
│                                                                          │
│  Prometheus Operator (controller)                                        │
│       │                                                                  │
│       │  watches (list/watch)                                            │
│       ▼                                                                  │
│  PodMonitor/llm-d-model-servers  ──────────────────────────────────────► │
│       │                          translates to scrape config             │
│       ▼                                                                  │
│  Prometheus StatefulSet                                                  │
│       │  (reloaded config: scrape_configs now includes decode pods)      │
│       │                                                                  │
│       │  HTTP GET /metrics every 15 s                                    │
│       ▼                                                                  │
│  decode-0 :8000/metrics                                                  │
│  decode-1 :8000/metrics                                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

**How Prometheus finds the right pods:**

1. PodMonitor specifies `selector.matchLabels: llm-d.ai/guide: optimized-baseline`.
2. Prometheus Operator lists all pods in the cluster matching that label.
3. For each matching pod it resolves the named port `modelserver` → `containerPort: 8000`.
4. Prometheus scrapes `http://<pod-ip>:8000/metrics` directly (bypasses the Service/kube-proxy).

**Why named port instead of a number?**

Using `port: modelserver` (a name, not `8000`) decouples the monitor from the actual port number. If the port ever changes, only the container spec needs updating — the PodMonitor stays unchanged.

**Cross-namespace scraping:**

The PodMonitor lives in `llm-d` but Prometheus lives in `llm-d-monitoring`. The kube-prometheus-stack Helm chart configures Prometheus with `podMonitorNamespaceSelector: {}` (match all namespaces), so it discovers PodMonitors cluster-wide.

---

### InferenceObjective (`02-inferenceobjective.yaml`) — what it does and who controls it

**The CR:**

```yaml
apiVersion: inference.networking.x-k8s.io/v1alpha2
kind: InferenceObjective
metadata:
  name: llm-d-standard
  namespace: llm-d
spec:
  poolRef:
    name: llm-d        # ← references the InferencePool created by Helm
  priority: 0          # ← scheduling priority (0 = standard, higher = more urgent)
```

**What it does:**

`InferenceObjective` is a flow-control policy object from the [Gateway API Inference Extension (GAIE)](https://gateway-api-inference-extension.sigs.k8s.io/) project. It attaches a **priority level** to a traffic flow for a given InferencePool. The EPP reads this priority when deciding how to handle queued requests under load:

- **`priority: 0`** — standard traffic; treated as best-effort when the pool is under pressure.
- Higher values (e.g. `priority: 10`) — higher-urgency flows that get preference in queue-scorer decisions.

In this demo there is only one objective at priority 0, so all traffic is treated equally. The object is still required because EPP's scheduling API expects at least one InferenceObjective bound to each pool.

**Who is the controller?**

> **Short answer: the EPP itself.**

This is the key architectural point that differs from a standalone GAIE deployment:

```
Standard GAIE deployment:
  GAIE controller (separate process) ──reconciles──► InferencePool, InferenceObjective
  EPP (separate process)             ──reads────────► InferencePool status

llm-d router deployment (this demo):
  EPP pod ──────────────────────────────────────────► watches InferencePool,
                                                       reads InferenceObjective,
                                                       NO separate GAIE controller needed
```

The llm-d EPP embeds the InferencePool/InferenceObjective controller logic directly. When the EPP starts, it:
1. Lists and watches `InferencePool` objects in its namespace.
2. Lists and watches `InferenceObjective` objects referencing those pools.
3. Lists and watches pods matching each pool's selector.
4. Builds an internal state table of pod health, queue depth, and KV cache state.
5. Uses InferenceObjective's `priority` field in the `queue-scorer` plugin's weighting logic.

---

### Model Server OpenTelemetry Configuration (`01-model-servers.yaml`)

> [!NOTE]
> Verified on a live cluster: `llm-d-inference-sim:v0.8.0` does **not** act on these `OTEL_*` variables — no `llm-d-model-server` service ever appears in Jaeger. The variables are kept because they are correct and forward-looking: a real vLLM (or a future sim build) that honors them will export an inference span that joins the EPP's downstream-propagated trace. The explanation below describes that intended behavior.

The five `OTEL_*` environment variables in the model server manifest are meant to wire the model-server pods into the distributed tracing pipeline. Each variable maps to a standard OpenTelemetry SDK configuration knob.

```yaml
# OpenTelemetry distributed tracing
- name: OTEL_SERVICE_NAME
  value: "llm-d-model-server"
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: "http://otel-collector:4317"
- name: OTEL_TRACES_EXPORTER
  value: "otlp"
- name: OTEL_TRACES_SAMPLER
  value: "parentbased_traceidratio"
- name: OTEL_TRACES_SAMPLER_ARG
  value: "1.0"
```

**Variable-by-variable explanation:**

**`OTEL_SERVICE_NAME=llm-d-model-server`**

The logical name of this service in the tracing backend. Jaeger uses it as the value of the `service.name` resource attribute on every span. In the Jaeger UI, this is what you select in the **Service** dropdown to filter traces. Both decode pods (`decode-0` and `decode-1`) share this name; Jaeger distinguishes individual pods via the `k8s.pod.name` attribute injected by the OTel SDK automatically.

**`OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`**

The destination for exported spans. `otel-collector` resolves via in-cluster Kubernetes DNS to the OTel Collector Service in the same namespace. Port `4317` is the standard gRPC OTLP receiver port. The OTel SDK opens a persistent gRPC connection to this endpoint and streams span data without per-request TCP overhead.

> Using `http://` (not `https://`) here is intentional for a local Kind cluster. In production, this endpoint should use mutual TLS.

**`OTEL_TRACES_EXPORTER=otlp`**

Selects the OTLP exporter from the SDK's exporter registry (alternatives include `zipkin`, `jaeger`, `console`). `otlp` uses the OpenTelemetry Protocol — the vendor-neutral wire format that OTel Collector natively understands. By exporting to a collector rather than directly to Jaeger, the pipeline gains a processing layer (filtering, batching, tail sampling) without changing any application code.

**`OTEL_TRACES_SAMPLER=parentbased_traceidratio`**

This is a **composite sampler** — the most important of the five variables to understand. It combines two sampling strategies:

```
parentbased_traceidratio
│
├── outer: parentbased
│     Checks the incoming request for a W3C traceparent header.
│     ├── header present, parent SAMPLED    → sample this span  (inherit)
│     ├── header present, parent NOT SAMPLED → drop this span   (inherit)
│     └── no header (root span)             → delegate to inner sampler ▼
│
└── inner: traceidratio
      Deterministically sample based on the trace ID hash.
      Rate set by OTEL_TRACES_SAMPLER_ARG (1.0 = always sample root spans).
```

**Why this matters in the llm-d flow:**

The **EPP is the trace originator for the routing path** (this is by design in `llm-d-router`). For each request it starts `gateway.request` from the ext_proc gRPC stream — it does **not** read an incoming `traceparent` — and then **injects a fresh `traceparent` downstream** to the selected model server. So the EPP's trace is meant to extend to the model server, not back to Envoy:

```
EPP (root span creator for the routing trace)
  │  creates: gateway.request  [traceID=abc, spanID=001]
  │  injects: traceparent: 00-abc-001-01  into the request forwarded to the model server
  │
  ▼
decode-0 (would-be child span creator)
  IF the model server exports traces (real vLLM with --otlp-traces-endpoint),
  its OTel SDK reads traceparent → inference span under traceID=abc.
  The no-GPU inference-sim does NOT export traces, so this child never appears.
```

This is why the EPP and a trace-exporting model server share a trace ID, while **Envoy and the IPP each produce their own independent traces** — Envoy starts `ingress` and the two `ext_proc` client spans on its own trace, and the IPP starts its `gateway.request` on its own trace. None of these three adopt each other's context. The `OTEL_TRACES_SAMPLER_ARG=1.0` below applies to whichever component is the root of its trace.

**`OTEL_TRACES_SAMPLER_ARG=1.0`**

The ratio argument for the inner `traceidratio` sampler, used only when there is no parent span (i.e., the model server receives a request with no `traceparent` header). `1.0` means 100% — all root-level spans are sampled. In practice, model server pods in this demo always receive a traceparent from the EPP, so this path is rarely hit. The value is set to `1.0` to catch any requests that bypass the EPP directly (e.g. health checks or manual test curls without a trace header).

**End-to-end trace topology:**

```
Three independent traces in Jaeger per request (verified on a live cluster):

  Trace A  service=llm-d-envoy-proxy
    └── ingress                                   (the proxy hop)
        ├── async ...ExternalProcessor.Process egress   (the IPP ext_proc call)
        └── async ...ExternalProcessor.Process egress   (the EPP ext_proc call)

  Trace B  service=llm-d-inference-payload-processor
    └── gateway.request                           (IPP body/header processing)

  Trace C  service=llm-d-router/epp
    ├── gateway.request                           (full request lifecycle)
    └── gateway.request_orchestration             (EPP scheduling detail)
    (would extend to the model server if it exported traces; the sim does not)
```

Three services, three trace IDs. Trace A (Envoy) is the single view that shows BOTH ext_proc hops together, which is the practical way to see and time the IPP → EPP ordering for one request.

---

### GAIE CRDs — who reconciles them?

**Step 3 in the install installs these CRDs:**

```bash
kubectl apply -k "https://github.com/llm-d/llm-d-router/config/crd"
```

This kustomization pulls two sources and registers all necessary CRDs in one shot:

| CRD | API Group | Purpose |
|---|---|---|
| `InferencePool` | `inference.networking.k8s.io` | Defines a pool of model server pods (label selector + failure mode) |
| `InferenceObjective` | `llm-d.ai` | Attaches priority/flow-control policy to a pool |
| `InferenceModelRewrite` | `llm-d.ai` | (not used in this demo) Model name rewrite rules |

> **Why `llm-d.ai` and not `inference.networking.x-k8s.io`?** In May 2026 llm-d migrated
> `InferenceObjective` and `InferenceModelRewrite` to its own `llm-d.ai` API group
> (PR [#1169](https://github.com/llm-d/llm-d-router/pull/1169)).
> The old `inference.networking.x-k8s.io` CRDs are no longer installed by the unified
> `llm-d-router/config/crd` kustomization. The EPP still accepts objects under the old group
> but logs a deprecation warning.

**Why install CRDs without the GAIE controller?**

CRDs are just **schema registrations** — they tell the Kubernetes API server "objects of this type are valid". Installing them does not start any controller. The Kubernetes API will accept `kubectl apply -f 02-inferenceobjective.yaml` only if the `InferenceObjective` CRD is already registered; otherwise it returns `no matches for kind "InferenceObjective"`.

In a standard GAIE deployment you would also deploy the `inference-extension-controller` pod, which reconciles InferencePool status. In this llm-d demo that controller is **not installed** because the llm-d EPP subsumes its responsibilities:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  What the GAIE controller normally does     Who does it in this demo    │
├─────────────────────────────────────────────────────────────────────────┤
│  Watch InferencePool, discover member pods  EPP (built-in)              │
│  Watch pod Ready/NotReady events            EPP (built-in)              │
│  Update InferencePool .status.conditions    EPP (built-in)              │
│  Read InferenceObjective priority           EPP queue-scorer plugin      │
│  Enforce flow-control under load            EPP scheduling pipeline      │
└─────────────────────────────────────────────────────────────────────────┘
```

The only reason the CRDs are installed from the upstream GAIE repo (rather than bundled in the Helm chart) is that CRDs are cluster-scoped resources — a Helm chart managing a single namespace cannot own or upgrade them safely. Installing them separately ensures they exist before the Helm chart's objects (ServiceMonitor, InferencePool) are applied, and avoids ownership conflicts if multiple Helm releases use the same CRDs.

---

## Prerequisites

- **Kind** v0.29+ and **Docker Desktop** (14+ CPUs, 20+ GB RAM allocated)
- **kubectl**, **Helm** v3.10+
- **jq**, **python3**
- llm-d repo cloned: `git clone https://github.com/llm-d/llm-d.git && cd llm-d`

---

## Installation Steps

Set the version variables first — they are referenced in multiple steps below:

```bash
export GAIE_VERSION=v1.5.0
export ROUTER_CHART_VERSION=v0
```

### Step 1: Create Kind Cluster

```bash
mkdir -p /tmp/llm-d-cache

kind create cluster \
  --config docs/monitoring/llm-d-full-demo/kind/kind-config.yaml
```

Verify:
```bash
kubectl get nodes
# NAME                  STATUS   ROLES           AGE
# llm-d-control-plane   Ready    control-plane   ...
```

---

### Step 2: Pull & Load the Inference-Sim Image

On **Apple Silicon (arm64)**:
```bash
ARM64_DIGEST=$(docker manifest inspect ghcr.io/llm-d/llm-d-inference-sim:v0.8.0 2>/dev/null | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  [print(m['digest']) for m in d.get('manifests',[]) \
  if m.get('platform',{}).get('architecture')=='arm64']")

docker pull ghcr.io/llm-d/llm-d-inference-sim@${ARM64_DIGEST}
docker tag ghcr.io/llm-d/llm-d-inference-sim@${ARM64_DIGEST} \
  ghcr.io/llm-d/llm-d-inference-sim:v0.8.0-arm64

kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.8.0-arm64 --name llm-d
```

On **x86_64**:
```bash
docker pull ghcr.io/llm-d/llm-d-inference-sim:v0.8.0
kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.8.0 --name llm-d
# Also update the image tag in manifests/01-model-servers.yaml to v0.8.0
```

---

### Step 3: Install CRDs

**Important:** Monitoring CRDs must be installed before the llm-d router Helm chart.

```bash
# 3a. Monitoring CRDs (ServiceMonitor, PodMonitor) — MUST BE FIRST
bash docs/monitoring/scripts/install-prometheus-grafana.sh --crds-only

# 3b. llm-d router CRDs — installs both GAIE CRDs (InferencePool) and
#     llm-d.ai CRDs (InferenceObjective, InferenceModelRewrite)
kubectl apply -k \
  "https://github.com/llm-d/llm-d-router/config/crd?ref=${ROUTER_CHART_VERSION}"
```

> **Why `llm-d-router/config/crd` instead of the upstream GAIE repo?**
> As of May 2026 llm-d migrated `InferenceObjective` to its own `llm-d.ai/v1alpha2` API group.
> The kustomization at `llm-d-router/config/crd` installs everything in one shot:
> the upstream GAIE CRDs (`inference.networking.k8s.io` InferencePool) **plus**
> the llm-d-owned CRDs (`llm-d.ai` InferenceObjective, InferenceModelRewrite).

Verify:
```bash
kubectl get crd | grep -E "inferencep|monitoring.coreos|llm-d.ai"
# Expected output:
# inferencemodelrewrites.llm-d.ai                    ...
# inferenceobjectives.llm-d.ai                       ...
# inferencepools.inference.networking.k8s.io         ...
# podmonitors.monitoring.coreos.com                  ...
# prometheusrules.monitoring.coreos.com              ...
# servicemonitors.monitoring.coreos.com              ...
```

---

### Step 4: Install Prometheus + Grafana

```bash
bash docs/monitoring/scripts/install-prometheus-grafana.sh --enable-tls
```

Verify:
```bash
kubectl get pods -n llm-d-monitoring
# NAME                                                           READY   STATUS
# alertmanager-llmd-kube-prometheus-stack-alertmanager-0        2/2     Running
# llmd-grafana-xxx                                              3/3     Running
# llmd-kube-prometheus-stack-operator-xxx                       1/1     Running
# prometheus-llmd-kube-prometheus-stack-prometheus-0            2/2     Running
```

---

### Step 5: Install llm-d Router (with Tracing)

```bash
kubectl create namespace llm-d

helm install llm-d \
  oci://ghcr.io/llm-d/charts/llm-d-router-standalone-dev \
  -f guides/recipes/router/base.values.yaml \
  -f guides/optimized-baseline/router/optimized-baseline.values.yaml \
  -f guides/recipes/router/features/monitoring.values.yaml \
  -f docs/monitoring/llm-d-full-demo/helm-values/kind-overrides.values.yaml \
  -f docs/monitoring/llm-d-full-demo/helm-values/tracing.values.yaml \
  -f docs/monitoring/llm-d-full-demo/helm-values/proxy-tracing-ipp.values.yaml \
  -n llm-d \
  --version ${ROUTER_CHART_VERSION}
```

- `tracing.values.yaml` enables the **EPP** to export spans to `http://otel-collector:4317`.
- `proxy-tracing-ipp.values.yaml` overrides the chart's **Envoy** config to (a) add the **IPP** as a second `ext_proc` filter in front of the EPP, (b) make Envoy the **OpenTelemetry trace root**, and (c) add the `ipp_ext_proc` and `otel_collector` clusters. It is a verbatim copy of the chart's Envoy preset plus those additions; re-sync it if you bump `ROUTER_CHART_VERSION`.

> Envoy starts referencing the `payload-processor` Service before the IPP exists (Step 6b). Because the IPP filter is configured `failure_mode_allow: true`, requests still succeed in the meantime — the IPP simply doesn't contribute a span until it is running.

Verify:
```bash
kubectl get deploy,svc,inferencepool,servicemonitor -n llm-d
# NAME                          READY   UP-TO-DATE   AVAILABLE
# deployment.apps/llm-d-epp     1/1     1            1
#
# NAME                TYPE        CLUSTER-IP   PORT(S)
# service/llm-d-epp   ClusterIP   ...          80/TCP,9002/TCP,9090/TCP
#
# NAME                                               AGE
# inferencepool.inference.networking.k8s.io/llm-d   ...
#
# NAME                                              AGE
# servicemonitor.monitoring.coreos.com/llm-d-epp   ...
```

---

### Step 6: Deploy OTel Collector + Jaeger

Both must run in the same namespace (`llm-d`) so components can reach the collector at `http://otel-collector:4317`.

```bash
bash docs/monitoring/scripts/install-otel-collector-jaeger.sh -n llm-d
```

This deploys:
- **OTel Collector** — receives OTLP gRPC on :4317, filters `/metrics` scrape spans, batches and forwards to Jaeger
- **Jaeger** (all-in-one, in-memory) — trace storage + UI on :16686

Verify:
```bash
kubectl get deploy,svc -n llm-d | grep -E "otel|jaeger"
# NAME                              READY   UP-TO-DATE   AVAILABLE
# deployment.apps/jaeger            1/1     1            1
# deployment.apps/otel-collector    1/1     1            1
#
# NAME                       TYPE        CLUSTER-IP   PORT(S)
# service/jaeger-collector   ClusterIP   ...          16686/TCP,4317/TCP
# service/otel-collector     ClusterIP   ...          4317/TCP,4318/TCP
```

---

### Step 6b: Deploy the Inference Payload Processor (IPP)

The IPP is the second `ext_proc` server in the Envoy chain (wired in Step 5). Deploy the workload now so Envoy's `ipp_ext_proc` cluster becomes healthy and IPP spans start appearing.

Install from the chart in the [`llm-d-inference-payload-processor`](https://github.com/llm-d/llm-d-inference-payload-processor) repo:

```bash
git clone https://github.com/llm-d/llm-d-inference-payload-processor.git /tmp/ipp

helm install payload-processor /tmp/ipp/config/charts/payload-processor \
  -f docs/monitoring/llm-d-full-demo/helm-values/ipp.values.yaml \
  -n llm-d
```

> If the published OCI chart is available in your environment, you can instead use
> `helm install payload-processor oci://ghcr.io/llm-d/charts/payload-processor --version v0 -f ... -n llm-d`.

`ipp.values.yaml` sets `provider.name=none` (the chart deploys only the IPP workload — Deployment, Service, ConfigMap, RBAC; Envoy wiring is done on the router side) and enables OTLP tracing to `http://otel-collector:4317`.

> [!NOTE]
> The IPP image `ghcr.io/llm-d/llm-d-inference-payload-processor:main` is currently **not anonymously pullable** (403). If the pod shows `ImagePullBackOff`, build it from the cloned repo and load it into Kind. On Apple Silicon, build for arm64:
> ```bash
> docker run --rm -v /tmp/ipp:/src -w /src/cmd -e CGO_ENABLED=0 -e GOOS=linux -e GOARCH=arm64 \
>   golang:1.25 go build -o /src/payload-processor-bin .
> printf 'FROM gcr.io/distroless/static:nonroot\nCOPY payload-processor-bin /payload-processor\nENTRYPOINT ["/payload-processor"]\n' > /tmp/ipp/Dockerfile.local
> docker build --platform linux/arm64 -f /tmp/ipp/Dockerfile.local -t ghcr.io/llm-d/llm-d-inference-payload-processor:main /tmp/ipp
> kind load docker-image ghcr.io/llm-d/llm-d-inference-payload-processor:main --name llm-d
> kubectl delete pod -n llm-d -l app=payload-processor   # let it restart onto the loaded image
> ```
> (drop `--platform`/`GOARCH=arm64` for x86_64.)

Verify:
```bash
kubectl get deploy,svc -n llm-d | grep payload-processor
# NAME                                       READY   UP-TO-DATE   AVAILABLE
# deployment.apps/payload-processor          1/1     1            1
#
# NAME                        TYPE        CLUSTER-IP   PORT(S)
# service/payload-processor   ClusterIP   ...          9004/TCP
```

---

### Step 7: Deploy Model Servers

```bash
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/01-model-servers.yaml
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/02-inferenceobjective.yaml

# PodMonitor — reuse the existing recipe component (selects pods by llm-d.ai/role=decode)
kubectl apply -k guides/recipes/modelserver/components/monitoring/ -n llm-d
```

The model server manifest includes OTEL env vars so inference-sim exports traces:
```yaml
env:
- name: OTEL_SERVICE_NAME
  value: "llm-d-model-server"
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: "http://otel-collector:4317"
- name: OTEL_TRACES_SAMPLER_ARG
  value: "1.0"   # 100% sampling rate for development
```

Wait for ready:
```bash
kubectl wait --for=condition=Ready pods --all -n llm-d --timeout=120s
kubectl get pods -n llm-d
```

Expected:
```
NAME                                        READY   STATUS
jaeger-xxx                                  1/1     Running
llm-d-epp-xxx                               2/2     Running
optimized-baseline-decode-xxx (x2)          1/1     Running
otel-collector-xxx                          1/1     Running
```

Verify all resources:
```bash
kubectl get deploy,inferenceobjective,podmonitor -n llm-d
# NAME                                           READY   UP-TO-DATE   AVAILABLE
# deployment.apps/jaeger                         1/1     1            1
# deployment.apps/llm-d-epp                      1/1     1            1
# deployment.apps/optimized-baseline-decode      2/2     2            2
# deployment.apps/otel-collector                 1/1     1            1
#
# NAME                                         AGE
# inferenceobjective.llm-d.ai/llm-d-standard  ...
#
# NAME                                    AGE
# podmonitor.monitoring.coreos.com/decode  ...
```

---

### Step 8: Deploy Traffic Generator

```bash
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/03-traffic-generator.yaml
```

Verify:
```bash
kubectl get deploy,configmap -n llm-d | grep traffic
# NAME                               READY   UP-TO-DATE   AVAILABLE
# deployment.apps/llm-d-traffic-gen  1/1     1            1
#
# NAME                              DATA
# configmap/llm-d-traffic-gen-script  1
```

```bash
kubectl logs -n llm-d deploy/llm-d-traffic-gen -f
# req=5 [200] Describe transformer architecture.
# req=6 [200] How does load balancing work?
```

---

### Step 9: Workload Variant Autoscaler (WVA) — opt-in

WVA is a global autoscaler for inference model servers. It watches the decode Deployment, reads vLLM/queue/KV-cache metrics from Prometheus, computes a desired replica count, and publishes it as the Prometheus metric `wva_desired_replicas`. A standard HPA consumes that metric and drives the scale subresource. On no-GPU Kind it runs in **saturation-scaling** mode (KV-cache + queue depth); GPU cost-optimization is illustrative only.

WVA has more moving parts than the rest of the demo, so install its controller, CRDs, and service-class/accelerator ConfigMaps from the [`llm-d-workload-variant-autoscaler`](https://github.com/llm-d/llm-d-workload-variant-autoscaler) repo (the `kind-emulator` profile is purpose-built for this). Then apply the demo's glue:

```bash
# 9a. Controller + CRDs + config (from the WVA repo; kind-emulator profile)
#     git clone https://github.com/llm-d/llm-d-workload-variant-autoscaler && cd it
ENVIRONMENT=kind-emulator ./deploy/install.sh        # or: kubectl apply -k config/overlays/cluster-scoped/kubernetes

# 9b. Point WVA's controller at this demo's Prometheus
#     (PROMETHEUS_BASE_URL in its manager ConfigMap → the llm-d-monitoring Prometheus svc)

# 9c. Expose wva_desired_replicas to the HPA as an external metric
#     install prometheus-adapter (or KEDA) and map the series — see the WVA repo

# 9d. Apply the VariantAutoscaling + HPA for the decode pool
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/05-variantautoscaling.yaml
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/06-hpa.yaml
```

Verify:
```bash
kubectl get variantautoscaling,hpa -n llm-d
# NAME                                                      TARGET                       MIN   MAX
# variantautoscaling.llmd.ai/optimized-baseline-decode      optimized-baseline-decode    1     4
#
# NAME                                                              REFERENCE
# horizontalpodautoscaler.autoscaling/optimized-baseline-decode-hpa Deployment/optimized-baseline-decode
```

Raise traffic (lower the generator's `INTERVAL`, or loop `curl`) and watch the decode replica count move as `wva_desired_replicas` rises.

---

## Advanced layers (optional)

The remaining components — **P/D disaggregation** (with the `llm-d-routing-sidecar`) and **precise prefix-cache / KV-cache-aware routing** (the embedded KV-cache indexer fed by ZMQ KV-events) — ship as caveated overlays under [`manifests/optional/`](./manifests/optional/). They deploy the topology and control/observability plane on the simulator, but the data-plane KV mechanics (real NIXL transfer, real KV-events, tokenization) require CPU/GPU vLLM. See [`manifests/optional/README.md`](./manifests/optional/README.md) for the exact steps, references to the canonical llm-d guides, and the no-GPU caveats.

---

## Accessing the Observability Stack

### Prometheus (Metrics)

```bash
kubectl port-forward -n llm-d-monitoring \
  svc/llmd-kube-prometheus-stack-prometheus 9090:9090
```

Open: [https://localhost:9090](https://localhost:9090) *(accept self-signed cert)*

---

### Grafana (Dashboards)

```bash
kubectl port-forward -n llm-d-monitoring svc/llmd-grafana 3000:80
```

Open: [http://localhost:3000](http://localhost:3000) — login: `admin` / `admin`

| Dashboard | Content |
|---|---|
| **llm-d vLLM Overview** | Token throughput, request rates, TTFT |
| **llm-d Failure & Saturation** | Error rates, queue depth, preemptions |
| **llm-d Diagnostic Drill-Down** | Per-pod detailed metrics |
| **llm-d Performance (KV Cache)** | KV cache utilization over time |
| **P/D Coordinator Metrics** | Prefill/Decode disaggregation |

---

### Jaeger (Distributed Traces)

```bash
kubectl port-forward -n llm-d svc/jaeger-collector 16686:16686
```

Open: [http://localhost:16686](http://localhost:16686)

In the Jaeger UI the **Service** dropdown lists three llm-d services:
`llm-d-envoy-proxy` (Envoy), `llm-d-inference-payload-processor` (IPP), and
`llm-d-router/epp` (EPP). Each request produces one trace **per service** (they
are not stitched together — see [Observed tracing behavior](#observed-tracing-behavior)).

1. **Service** → select `llm-d-envoy-proxy`, **Find Traces**, open one. It has:
   - `ingress` — the proxy hop
   - two `async ...ExternalProcessor.Process egress` spans — the IPP call and the EPP call.
     This is the single view that shows both ext_proc hops for one request.
2. **Service** → `llm-d-inference-payload-processor` → the IPP's `gateway.request` span.
3. **Service** → `llm-d-router/epp` → `gateway.request` + `gateway.request_orchestration`
   (the scheduling decision).
4. `llm-d-model-server` is absent — the no-GPU `inference-sim` does not export traces.

---

### Send a Test Request

```bash
kubectl port-forward -n llm-d svc/llm-d-epp 8081:80 &
curl -s -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct",
       "messages":[{"role":"user","content":"What is llm-d?"}],
       "max_tokens":50}' | jq
```

Then go to Jaeger → find the trace for that request.

---

## Test Cases

### Metrics (Prometheus / Grafana)

#### TC-1: EPP Scheduling Latency P99

```promql
histogram_quantile(0.99, sum by(le) (
  rate(inference_extension_scheduler_e2e_duration_seconds_bucket[5m])
))
```
**Expected:** P99 < 1ms

#### TC-2: Plugin Processing Breakdown

```promql
histogram_quantile(0.99, sum by(le, plugin_type) (
  rate(inference_extension_plugin_duration_seconds_bucket[5m])
))
```
**Expected:** Each plugin (queue-scorer, kv-cache-utilization-scorer, prefix-cache-scorer, no-hit-lru-scorer) < 0.5ms P99

#### TC-3: Request Throughput Through EPP

```promql
sum(rate(inference_objective_request_total[5m]))
```

#### TC-4: Token Generation Rate Per Model Server

```promql
sum by(pod) (rate(vllm:generation_tokens_total[5m]))
```
**Expected:** Both decode pods show roughly equal rates.

#### TC-5: Prefix Cache Indexer Size

```promql
inference_extension_prefix_indexer_size
```
**Expected:** Grows over time as unique prompts are processed.

#### TC-6: vLLM E2E Request Latency P90

```promql
histogram_quantile(0.90, sum by(le, pod) (
  rate(vllm:e2e_request_latency_seconds_bucket[5m])
))
```

#### TC-7: Running Requests

```promql
inference_objective_running_requests
```

---

### Traces (Jaeger)

#### TC-8: EPP Trace Verification

Verify each request through the EPP produces a trace with 2 spans:

```bash
# Query Jaeger API
curl -s "http://localhost:16686/api/traces?service=llm-d-router%2Fepp&limit=5" | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
for t in d.get('data', []):
    spans = t.get('spans', [])
    ops = [s['operationName'] for s in spans]
    dur = spans[0].get('duration', 0) / 1000 if spans else 0
    print(f'traceID={t[\"traceID\"][:16]}  spans={len(spans)}  duration={dur:.1f}ms')
    for op in ops:
        print(f'  - {op}')
"
```

**Expected output:**
```
traceID=222f257fb8243b01  spans=2  duration=0.1ms
  - gateway.request
  - gateway.request_orchestration
```

#### TC-9: Trace Latency vs Metric Consistency

Compare EPP scheduling latency from both sources — they should match:

**From Prometheus:**
```promql
histogram_quantile(0.99, sum by(le) (
  rate(inference_extension_scheduler_e2e_duration_seconds_bucket[5m])
))
```

**From Jaeger:** Select a trace → inspect `gateway.request_orchestration` span duration.

#### TC-10: Error Trace

Verify error requests also produce traces:

```bash
curl -s -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"bad-model","messages":[{"role":"user","content":"test"}],"max_tokens":5}'
# Then check Jaeger for the failed trace
```

#### TC-11: Three trace sources + Envoy shows both ext_proc hops

Verify all three llm-d services appear, and that Envoy's trace contains the two
`ext_proc` calls (IPP and EPP).

```bash
# All three services should be listed
curl -s "http://localhost:16686/api/services" | python3 -c "import sys,json; print(sorted(json.load(sys.stdin)['data']))"
# Expected to include: llm-d-envoy-proxy, llm-d-inference-payload-processor, llm-d-router/epp

# Envoy's trace = ingress + two ext_proc 'Process egress' spans
curl -s "http://localhost:16686/api/traces?service=llm-d-envoy-proxy&limit=3&lookback=1h" | \
  python3 -c "
import sys, json
for t in (json.load(sys.stdin).get('data') or []):
    ops = [s['operationName'] for s in t.get('spans', [])]
    n_extproc = sum('ExternalProcessor.Process' in o for o in ops)
    print(f'traceID={t[\"traceID\"][:16]}  spans={len(ops)}  ext_proc_calls={n_extproc}')
"
```

**Expected:** each Envoy trace has 3 spans with `ext_proc_calls=2` (the IPP and EPP calls). These are **separate** traces from the IPP's and EPP's own traces — a single 4-service trace is not produced (see [Observed tracing behavior](#observed-tracing-behavior)). If the IPP service is missing, confirm Step 6b is deployed and the `ipp_ext_proc` cluster is healthy (`curl -s localhost:19000/clusters | grep ipp_ext_proc` against an Envoy admin port-forward).

#### TC-12: IPP Header Enrichment

Confirm the IPP processes each request body (extracting `model` → `X-Gateway-Model-Name`):

```bash
kubectl logs -n llm-d deploy/payload-processor | grep -iE "parsed field from body|base model header" | tail
```

**Expected** (verified on a live cluster) — one pair per request:
```
... "msg":"parsed field from body","field":"model","value":"Qwen/Qwen2.5-0.5B-Instruct"
... "msg":"updated base model header based on the request target model","targetModel":"Qwen/Qwen2.5-0.5B-Instruct"
```

#### TC-13: WVA Desired Replicas (opt-in)

If WVA is installed (Step 9), confirm it publishes a scaling signal:

```promql
wva_desired_replicas{variant_name="optimized-baseline-decode", exported_namespace="llm-d"}
```
**Expected:** a value ≥ 1 that rises with load; the HPA tracks it.

---

## Helm Values Layer Reference

```
guides/recipes/router/base.values.yaml
  └── EPP image, proxy defaults, shared settings

guides/optimized-baseline/router/optimized-baseline.values.yaml
  └── 4-plugin scoring: queue + kv-cache + prefix-cache + no-hit-lru

guides/recipes/router/features/monitoring.values.yaml
  └── ServiceMonitor for EPP metrics (Prometheus scraping)

docs/monitoring/llm-d-full-demo/helm-values/tracing.values.yaml
  └── EPP OTLP tracing → http://otel-collector:4317 (100% sampling)

docs/monitoring/llm-d-full-demo/helm-values/kind-overrides.values.yaml
  └── Reduced EPP/proxy resources for local kind cluster

docs/monitoring/llm-d-full-demo/helm-values/proxy-tracing-ipp.values.yaml
  └── Full Envoy config override: IPP ext_proc filter (before EPP),
      OpenTelemetry trace root, ipp_ext_proc + otel_collector clusters

docs/monitoring/llm-d-full-demo/helm-values/ipp.values.yaml   (payload-processor chart)
  └── IPP workload only (provider.name=none) + OTLP tracing
```

---

## Configuration Reference

### tracing.values.yaml

| Parameter | Value | Description |
|---|---|---|
| `router.tracing.enabled` | `true` | Enable EPP OTLP tracing |
| `router.tracing.otelExporterEndpoint` | `http://otel-collector:4317` | OTel Collector endpoint |
| `router.tracing.sampling.sampler` | `parentbased_traceidratio` | Sampler type |
| `router.tracing.sampling.samplerArg` | `1.0` | 100% sampling (dev); use `0.1` in production |

### Model Server OTEL Env Vars

| Variable | Value | Description |
|---|---|---|
| `OTEL_SERVICE_NAME` | `llm-d-model-server` | Service name shown in Jaeger UI service dropdown |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | gRPC OTLP destination (in-cluster DNS, port 4317) |
| `OTEL_TRACES_EXPORTER` | `otlp` | Wire format: OpenTelemetry Protocol (vendor-neutral) |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | Composite sampler: inherit parent's decision; fall back to ratio for root spans |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | Ratio for root spans (100%); in practice model server pods always have an EPP parent |

See [Model Server OpenTelemetry Configuration](#model-server-opentelemetry-configuration-01-model-serversyaml) for a full explanation of each variable and the trace propagation flow.

### OTel Collector Pipeline

```yaml
receivers:  otlp (gRPC :4317, HTTP :4318)
processors:
  - filter/drop-metrics-scraping   # drop /metrics HTTP polling spans (Prometheus noise)
  - batch (1024 spans, 1s timeout) # buffer before forwarding to reduce Jaeger write load
exporters:  otlp/jaeger → jaeger-collector:4317
```

The filter processor is important: Prometheus scrapes `/metrics` every 15–30 s, and those HTTP requests would appear as hundreds of low-value spans in Jaeger per minute if not dropped here.

---

## Cleanup

```bash
# Remove the helm releases (router + IPP)
helm uninstall llm-d -n llm-d
helm uninstall payload-processor -n llm-d

# Remove WVA if installed (Step 9) — from the WVA repo checkout:
#   ENVIRONMENT=kind-emulator ./deploy/install.sh --uninstall
#   (or: kubectl delete -k config/overlays/cluster-scoped/kubernetes)

# Remove all remaining workloads (OTel + Jaeger + model servers + VA/HPA)
kubectl delete namespace llm-d

# Remove monitoring stack
bash docs/monitoring/scripts/install-prometheus-grafana.sh --uninstall

# Delete kind cluster
kind delete cluster --name llm-d

# Stop all port-forwards
pkill -f "kubectl port-forward" 2>/dev/null || true
```

---

## Troubleshooting

### No traces in Jaeger

1. Verify OTel Collector is running: `kubectl get pods -n llm-d -l app=otel-collector`
2. Check EPP tracing is enabled: `kubectl get deployment llm-d-epp -n llm-d -o yaml | grep -A5 tracing`
3. Check OTel Collector logs for errors: `kubectl logs -n llm-d deploy/otel-collector`
4. Send a manual request and wait ~5s before checking Jaeger

### EPP pod crashes immediately

Install monitoring CRDs before the Helm chart (`--crds-only` in Step 3).

### Model server pods stuck in `ImagePullBackOff`

```bash
kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.8.0-arm64 --name llm-d
```

### Traffic generator returns 404

EPP Service HTTP port is **80** (not 8081): set `ROUTER_URL=http://llm-d-epp:80`.

### Prometheus not scraping EPP

```bash
kubectl get servicemonitor -n llm-d
kubectl port-forward -n llm-d svc/llm-d-epp 9090:9090
curl http://localhost:9090/metrics | grep inference_extension | head -5
```
