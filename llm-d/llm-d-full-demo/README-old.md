# llm-d Full Stack Observability Demo (No GPU)

This guide deploys the **complete llm-d stack** on a local Kind cluster **without GPU**, covering every key llm-d component: the **Envoy** data-plane proxy, the **EPP / llm-d Router** (Endpoint Picker), the **Inference Payload Processor (IPP)**, **InferencePool / InferenceObjective**, **inference-sim** model servers, the embedded **KV-cache indexer**, the **Workload Variant Autoscaler (WVA)**, and the optional **P/D disaggregation** path. It provides end-to-end observability with **Prometheus** (metrics), **Grafana** (dashboards), and **Jaeger** (distributed tracing).

Each request is observable in Jaeger across **three trace sources** — the **Envoy** proxy, the **IPP**, and the **EPP** — so you can see and time every hop of the gateway. Envoy's own trace contains the `ingress` span plus **both `ext_proc` calls** (to the IPP and the EPP) as child spans, which is what proves the request really flows `Envoy → IPP → EPP → model server`.

> [!IMPORTANT]
> These are **separate traces**, not one stitched trace. The EPP and IPP each root their own trace (the llm-d EPP starts `gateway.request` from the gRPC stream and injects `traceparent` *downstream* to the model server by design; it does not adopt Envoy's `ext_proc` trace context). So you correlate the three by time and by the ext_proc spans in Envoy's trace, not by a shared trace ID. The EPP→model-server hop *would* share a trace ID with a trace-exporting model server (real vLLM with `--otlp-traces-endpoint`); the no-GPU `inference-sim` does not export traces. This behavior was verified on a live Kind cluster — see [Observed tracing behavior](#observed-tracing-behavior).

> Envoy was always part of this stack; it runs as a sidecar inside the `llm-d-epp` pod (the standalone router chart's `proxy`). This revision makes it explicit, adds the IPP as a second `ext_proc` filter in front of the EPP, and enables Envoy's own OpenTelemetry tracing so the proxy hop (and the two ext_proc calls) become visible.

> **中文版本：** [README-zh.md](./README-zh.md)

---

## Re-verified against llm-d `main` (2026-08-02)

The whole guide was re-run from scratch on a fresh Kind cluster against current `main` of
`llm-d`, `llm-d-router`, `llm-d-inference-payload-processor`, and
`llm-d-workload-variant-autoscaler`. Everything below is what actually changed. If you are
following an older copy of this demo, these are the breaking points:

| # | What changed | Impact |
|---|---|---|
| 1 | `docs/monitoring/` was **deleted** from the llm-d repo (PR #1542). Install scripts and dashboards now live in `guides/recipes/observability/`. | Step 3/4/6 commands 404. Paths are now `$LLMD/guides/recipes/observability/...`. |
| 2 | `llm-d-router`'s floating **`v0` git branch was deleted** (release tags only). | `kubectl apply -k '...?ref=v0'` fails with `couldn't find remote ref v0`. New `ROUTER_CRD_REF` var, set to a release tag. `v0` is still valid as a *Helm* tag. |
| 3 | **inference-sim v0.8.0 → v0.9.2**, and v0.9.x's default `--mode random` needs a tokenizer render service. | Model servers **crash-loop** without the new `--force-dummy-tokenizer` flag. |
| 4 | The IPP chart now defaults to the released **`:v0.1.0`**, which *is* anonymously pullable. | The old build-from-source workaround for the 403 on `:main` is no longer needed. |
| 5 | The router chart's Envoy preset drifted (IPv6 `additional_addresses`, explicit `failure_mode_allow`) **under the same floating `v0` tag**. | `helm-values/proxy-tracing-ipp.values.yaml` was re-synced. Re-sync it even when you don't bump the version. |
| 6 | The EPP now emits **5 spans instead of 2**, with `llm_d.epp.*` attributes on the plain optimized-baseline path. | Strictly better — see [Observed tracing behavior](#observed-tracing-behavior). |
| 7 | WVA's **`VariantAutoscaling` CRD is deprecated** and no longer shipped; discovery is via `llm-d.ai/*` annotations on the HPA. Its published `:latest` image is stale and crash-loops. | `manifests/05-variantautoscaling.yaml` is now legacy; `manifests/06-hpa.yaml` carries the annotations. Step 9 has a full verified recipe. |
| 8 | The observability installer now loads **7** Grafana dashboards, not 5. | Two new dashboards: Inference Gateway, SGLang Overview. |

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
| `llm-d-router/epp` | `gateway.request` → `gateway.request_orchestration` → `run_scheduler_profile` → (`filter_endpoints`, `pick_endpoints`) | EPP routing **and the full scheduling pipeline** — 5 spans, properly nested. |
| `llm-d-model-server` | (none) | `inference-sim` does not export traces at any version tested (v0.8.0–v0.9.2). |

> [!TIP]
> **The EPP is much better instrumented than it used to be.** This guide previously recorded
> only 2 EPP spans (`gateway.request` + `gateway.request_orchestration`), and noted that the
> `llm_d.epp.*` attributes were reachable *only* on the precise-prefix-cache path. That is no
> longer true: on the **plain optimized-baseline path used by this demo**, the scheduler
> emits `run_scheduler_profile`, `filter_endpoints`, and `pick_endpoints`, carrying the
> `llm_d.epp.*` namespace directly. Observed on this run:
>
> ```
> gateway.request
> └─ gateway.request_orchestration      request_prio=0  target_model=Qwen/Qwen2.5-0.5B-Instruct
>    └─ run_scheduler_profile           llm_d.epp.scheduling.profile.name=default
>       ├─ filter_endpoints             llm_d.epp.filter.candidate_endpoints=2
>       │                               llm_d.epp.filter.filtered_endpoints=1
>       └─ pick_endpoints               llm_d.epp.picker.candidate_endpoints=1
>                                       llm_d.epp.picker.top_endpoints=["llm-d/optimized-baseline-decode-...-rank-0"]
>                                       llm_d.epp.picker.top_scores=[0.999997615814209]
> ```
> `filter_endpoints` and `pick_endpoints` also carry `gen_ai.request.id` and
> `gen_ai.request.model`, so a single EPP trace now explains *which* endpoint was chosen and
> *why* — no P/D or precise-prefix setup required.

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
| `PodMonitor/decode` | `llm-d` | CR | Prometheus scrapes model server metrics (:8000) — from `$LLMD/guides/recipes/modelserver/components/monitoring/` |
| `HorizontalPodAutoscaler/optimized-baseline-decode-hpa` | `llm-d` | HPA (opt-in) | **WVA** target, discovered via `llm-d.ai/*` annotations; WVA emits `wva_desired_replicas` → prometheus-adapter → this HPA. Replaces the deprecated `VariantAutoscaling` CR. |
| Prometheus (HTTPS/TLS) | `llm-d-monitoring` | StatefulSet | Metrics storage |
| Grafana | `llm-d-monitoring` | Deployment | 5 pre-loaded llm-d dashboards |

### Observability Coverage

| Signal | Tool | Sources | Count |
|---|---|---|---|
| **Metrics** | Prometheus + Grafana | EPP (ServiceMonitor) + model servers (PodMonitor) | 35+ EPP + 41 vLLM |
| **Traces** | Jaeger + OTel Collector | Envoy (`llm-d-envoy-proxy`) + IPP (`llm-d-inference-payload-processor`) + EPP (`llm-d-router/epp`); model server does not export (sim) | 3 services / 3 separate traces per request (3 + 1 + 5 = 9 spans) |

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

This demo reuses the existing recipe component at `$LLMD/guides/recipes/modelserver/components/monitoring/`, applied with:

```bash
kubectl apply -k $LLMD/guides/recipes/modelserver/components/monitoring/ -n llm-d
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
> Verified on a live cluster: `llm-d-inference-sim` (tested at both v0.8.0 and v0.9.2) does **not** act on these `OTEL_*` variables — no `llm-d-model-server` service ever appears in Jaeger. The variables are kept because they are correct and forward-looking: a real vLLM (or a future sim build) that honors them will export an inference span that joins the EPP's downstream-propagated trace. The explanation below describes that intended behavior.

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
- **jq**, **python3**, **yq** (`yq` is only needed by the optional WVA installer in Step 9)
- llm-d repo cloned: `git clone https://github.com/llm-d/llm-d.git && cd llm-d`

---

## Installation Steps

Set the path and version variables first — they are referenced in every step below:

```bash
# Where you cloned llm-d/llm-d, and where THIS demo directory lives.
export LLMD=/path/to/llm-d          # the llm-d/llm-d clone
export DEMO=/path/to/llm-d-full-demo # this directory

export GAIE_VERSION=v1.5.0
export ROUTER_CHART_VERSION=v0      # Helm chart tag (floating; still published)
export ROUTER_CRD_REF=v0.9.0        # git ref for the router CRD kustomization
```

> [!IMPORTANT]
> **Two paths that used to be one.** This demo is *not* part of the llm-d repo — it lives
> on its own, so its manifests and values are referenced through `$DEMO`. Earlier revisions
> of this guide assumed the demo sat at `llm-d/docs/monitoring/llm-d-full-demo/`; that
> directory no longer exists upstream. The runnable monitoring assets it used to hold
> (install scripts, Grafana dashboards, tracing manifests) moved to
> `guides/recipes/observability/` in llm-d PR #1542, which is where `$LLMD` references
> point now.

> [!NOTE]
> `ROUTER_CHART_VERSION` and `ROUTER_CRD_REF` are deliberately separate. `v0` is still a
> valid **Helm/OCI** tag for the router chart, but it is no longer a **git** ref in
> `llm-d/llm-d-router` — the floating `v0` branch was deleted in favour of real release
> tags, so `kubectl apply -k '...?ref=v0'` now fails with
> `couldn't find remote ref v0`. Use a release tag for the CRD kustomization.

### Step 1: Create Kind Cluster

```bash
mkdir -p /tmp/llm-d-cache

kind create cluster --config $DEMO/kind/kind-config.yaml
```

Verify:
```bash
kubectl get nodes
# NAME                  STATUS   ROLES           AGE
# llm-d-control-plane   Ready    control-plane   ...
```

---

### Step 2: Pull & Load the Inference-Sim Image

```bash
export SIM_VERSION=v0.9.2
```

On **Apple Silicon (arm64)**:
```bash
ARM64_DIGEST=$(docker manifest inspect ghcr.io/llm-d/llm-d-inference-sim:${SIM_VERSION} 2>/dev/null | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  [print(m['digest']) for m in d.get('manifests',[]) \
  if m.get('platform',{}).get('architecture')=='arm64']")

docker pull ghcr.io/llm-d/llm-d-inference-sim@${ARM64_DIGEST}
docker tag ghcr.io/llm-d/llm-d-inference-sim@${ARM64_DIGEST} \
  ghcr.io/llm-d/llm-d-inference-sim:${SIM_VERSION}-arm64

kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:${SIM_VERSION}-arm64 --name llm-d
```

On **x86_64**:
```bash
docker pull ghcr.io/llm-d/llm-d-inference-sim:${SIM_VERSION}
kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:${SIM_VERSION} --name llm-d
# Also drop the `-arm64` suffix from the image tag in manifests/01-model-servers.yaml
```

> [!IMPORTANT]
> **`--force-dummy-tokenizer` is required from v0.9.x on.** The sim's default `--mode random`
> builds its response bank at startup by tokenizing sentences against a *tokenizer render
> service* at `--render-url` (default `http://localhost:8082`). This demo runs no such
> service, so without the flag every model-server pod crash-loops on:
> ```
> failed to create vLLM simulator ... dataset initialization error:
> RenderRequest: post /v1/completions/render: dial tcp [::1]:8082: connect: connection refused
> ```
> `manifests/01-model-servers.yaml` already passes `--force-dummy-tokenizer`, which keeps
> the sim self-contained. (This is also why the sim can't be bumped by editing the tag alone
> if you are upgrading an older copy of this demo.)

---

### Step 3: Install CRDs

**Important:** Monitoring CRDs must be installed before the llm-d router Helm chart.

```bash
# 3a. Monitoring CRDs (ServiceMonitor, PodMonitor) — MUST BE FIRST
bash $LLMD/guides/recipes/observability/install-prometheus-grafana.sh --crds-only

# 3b. llm-d router CRDs — installs both GAIE CRDs (InferencePool) and
#     llm-d.ai CRDs (InferenceObjective, InferenceModelRewrite)
kubectl apply -k \
  "https://github.com/llm-d/llm-d-router/config/crd?ref=${ROUTER_CRD_REF}"
```

> **Why `llm-d-router/config/crd` instead of the upstream GAIE repo?**
> As of May 2026 llm-d migrated `InferenceObjective` to its own `llm-d.ai/v1alpha2` API group.
> The kustomization at `llm-d-router/config/crd` installs everything in one shot:
> the upstream GAIE CRDs (`inference.networking.k8s.io` InferencePool) **plus**
> the llm-d-owned CRDs (`llm-d.ai` InferenceObjective, InferenceModelRewrite).

> **Note the `ref=${ROUTER_CRD_REF}`, not `ref=${ROUTER_CHART_VERSION}`.** See the variable
> block at the top of this section — `v0` is a Helm tag, not a git ref. Pick the newest
> release tag with:
> ```bash
> git ls-remote --tags https://github.com/llm-d/llm-d-router | grep -v '\^{}' \
>   | sed 's|.*refs/tags/||' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1
> ```

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
bash $LLMD/guides/recipes/observability/install-prometheus-grafana.sh --enable-tls
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
  -f $LLMD/guides/recipes/router/base.values.yaml \
  -f $LLMD/guides/optimized-baseline/router/optimized-baseline.values.yaml \
  -f $LLMD/guides/recipes/router/features/monitoring.values.yaml \
  -f $DEMO/helm-values/kind-overrides.values.yaml \
  -f $DEMO/helm-values/tracing.values.yaml \
  -f $DEMO/helm-values/proxy-tracing-ipp.values.yaml \
  -n llm-d \
  --version ${ROUTER_CHART_VERSION}
```

- `tracing.values.yaml` enables the **EPP** to export spans to `http://otel-collector:4317`.
- `proxy-tracing-ipp.values.yaml` overrides the chart's **Envoy** config to (a) add the **IPP** as a second `ext_proc` filter in front of the EPP, (b) make Envoy the **OpenTelemetry trace root**, and (c) add the `ipp_ext_proc` and `otel_collector` clusters. It is a verbatim copy of the chart's Envoy preset plus those additions, with the chart's Go-template placeholders resolved for **sidecar mode + TLS EPP serving** (`STATIC` ext_proc cluster, `127.0.0.1`, `tls_options`/`transport_socket` present, `failure_mode_allow: false`).

> [!WARNING]
> **Re-sync this file whenever the chart's Envoy preset moves — including when you *don't*
> change `ROUTER_CHART_VERSION`.** `v0` is a *floating* tag: the same version string
> resolves to a new chart over time. Re-syncing on this run picked up two upstream drifts
> (IPv6 `additional_addresses` on both listeners, and an explicit `failure_mode_allow` on
> the EPP `ext_proc` filter). To diff your copy against the live chart:
> ```bash
> helm pull oci://ghcr.io/llm-d/charts/llm-d-router-standalone-dev \
>   --version $ROUTER_CHART_VERSION --untar --untardir /tmp/chart
> python3 -c "import yaml;print(yaml.safe_load(open('/tmp/chart/llm-d-router-standalone-dev/values.yaml'))['router']['proxy']['presets']['envoy']['configMap']['data']['envoy.yaml'])" > /tmp/chart-envoy.yaml
> python3 -c "import yaml;print(yaml.safe_load(open('$DEMO/helm-values/proxy-tracing-ipp.values.yaml'))['router']['proxy']['configMap']['data']['envoy.yaml'])" > /tmp/demo-envoy.yaml
> diff -u /tmp/chart-envoy.yaml /tmp/demo-envoy.yaml   # expect ONLY the `### llm-d-full-demo:` additions
> ```

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
bash $LLMD/guides/recipes/observability/install-otel-collector-jaeger.sh -n llm-d
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
  -f $DEMO/helm-values/ipp.values.yaml \
  -n llm-d
```

> If the published OCI chart is available in your environment, you can instead use
> `helm install payload-processor oci://ghcr.io/llm-d/charts/payload-processor --version v0 -f ... -n llm-d`.

`ipp.values.yaml` sets `provider.name=none` (the chart deploys only the IPP workload — Deployment, Service, ConfigMap, RBAC; Envoy wiring is done on the router side) and enables OTLP tracing to `http://otel-collector:4317`.

> [!NOTE]
> **No image workaround is needed any more.** The chart's default image is now the released
> `ghcr.io/llm-d/llm-d-inference-payload-processor:v0.1.0`, which **is** anonymously pullable —
> earlier revisions of this guide defaulted to `:main`, which returned 403 and forced a
> local build. Kind pulls `v0.1.0` directly; no `kind load` step.
>
> <details><summary>Fallback: build the IPP locally (only if you hit <code>ImagePullBackOff</code>)</summary>
>
> On Apple Silicon, build for arm64:
> ```bash
> docker run --rm -v /tmp/ipp:/src -w /src/cmd -e CGO_ENABLED=0 -e GOOS=linux -e GOARCH=arm64 \
>   golang:1.25 go build -o /src/payload-processor-bin .
> printf 'FROM gcr.io/distroless/static:nonroot\nCOPY payload-processor-bin /payload-processor\nENTRYPOINT ["/payload-processor"]\n' > /tmp/ipp/Dockerfile.local
> docker build --platform linux/arm64 -f /tmp/ipp/Dockerfile.local -t ghcr.io/llm-d/llm-d-inference-payload-processor:main /tmp/ipp
> kind load docker-image ghcr.io/llm-d/llm-d-inference-payload-processor:main --name llm-d
> helm upgrade payload-processor ... --set payloadProcessor.image.tag=main   # then point the chart at it
> ```
> (drop `--platform`/`GOARCH=arm64` for x86_64.)
> </details>

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
kubectl apply -f $DEMO/manifests/01-model-servers.yaml
kubectl apply -f $DEMO/manifests/02-inferenceobjective.yaml

# PodMonitor — reuse the existing recipe component (selects pods by llm-d.ai/role=decode)
kubectl apply -k $LLMD/guides/recipes/modelserver/components/monitoring/ -n llm-d
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
kubectl apply -f $DEMO/manifests/03-traffic-generator.yaml
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

> [!IMPORTANT]
> **The `VariantAutoscaling` CRD is deprecated — this step is now annotation-based.**
> WVA discovers workloads from `llm-d.ai/*` **annotations on the HPA** (or on a KEDA
> `ScaledObject`); see the WVA repo's `docs/developer-guide/migrating-from-va-crd.md`.
> Two consequences:
> - `manifests/06-hpa.yaml` now carries those annotations and is **sufficient on its own**.
> - `manifests/05-variantautoscaling.yaml` is **legacy** and is no longer applied. WVA's
>   current manifests don't even ship the CRD, so applying it fails with
>   `no matches for kind "VariantAutoscaling" in version "llmd.ai/v1alpha1"`.

> [!WARNING]
> **Use the `:main` image, not `:latest`.** The published `:latest` tag lags `main` by weeks
> and still expects the removed `VariantAutoscaling` CRD, so it crash-loops on a current
> install with `unable to setup indexes ... no matches for kind "VariantAutoscaling"`.

Full recipe, verified against this demo's cluster:

```bash
git clone https://github.com/llm-d/llm-d-workload-variant-autoscaler /tmp/wva && cd /tmp/wva

# 9a. WVA expects a Prometheus TLS secret in ITS monitoring namespace. This demo already
#     created one (Step 4 used --enable-tls), so copy it across rather than standing up a
#     second Prometheus.
kubectl create ns workload-variant-autoscaler-monitoring --dry-run=client -o yaml | kubectl apply -f -
kubectl get secret prometheus-web-tls -n llm-d-monitoring -o yaml \
  | python3 -c "import sys,yaml; d=yaml.safe_load(sys.stdin); \
      d['metadata']={'name':'prometheus-web-tls','namespace':'workload-variant-autoscaler-monitoring'}; \
      print(yaml.safe_dump(d))" \
  | kubectl apply -f -

# 9b. Controller + RBAC + config. Reuse this demo's cluster and Prometheus.
ENVIRONMENT=kind-emulator CREATE_CLUSTER=false CLUSTER_NAME=llm-d \
DEPLOY_PROMETHEUS=false DEPLOY_OPERATIONAL_DASHBOARD=false \
SCALER_BACKEND=keda KEDA_HELM_INSTALL=true \
  ./deploy/install.sh

# 9c. Pin the controller to :main (see the warning above).
kubectl set image -n workload-variant-autoscaler-system \
  deploy/wva-controller-manager manager=ghcr.io/llm-d/llm-d-workload-variant-autoscaler:main

# 9d. Point WVA at THIS demo's Prometheus.
kubectl get cm wva-manager-config -n workload-variant-autoscaler-system \
  -o jsonpath='{.data.config\.yaml}' > /tmp/wva-cfg.yaml
sed -i '' 's|https://kube-prometheus-stack-prometheus.workload-variant-autoscaler-monitoring.svc.cluster.local:9090|https://llmd-kube-prometheus-stack-prometheus.llm-d-monitoring.svc.cluster.local:9090|' /tmp/wva-cfg.yaml
kubectl create cm wva-manager-config -n workload-variant-autoscaler-system \
  --from-file=config.yaml=/tmp/wva-cfg.yaml --dry-run=client -o yaml \
  | python3 -c "import sys,yaml; d=yaml.safe_load(sys.stdin); \
      d['metadata']['labels']={'app.kubernetes.io/name':'workload-variant-autoscaler'}; \
      print(yaml.safe_dump(d))" \
  | kubectl apply -f -
kubectl rollout restart deploy/wva-controller-manager -n workload-variant-autoscaler-system

# 9e. Expose wva_desired_replicas to the HPA as an external metric.
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts && helm repo update
helm install prometheus-adapter prometheus-community/prometheus-adapter -n llm-d-monitoring \
  --set prometheus.url=https://llmd-kube-prometheus-stack-prometheus.llm-d-monitoring.svc.cluster.local \
  --set prometheus.port=9090 \
  -f $LLMD/guides/workload-autoscaling/components/prometheus-adapter/wva-adapter-values.yaml \
  -f $LLMD/guides/workload-autoscaling/components/prometheus-adapter/tls-adapter-values.yaml

# 9f. The annotated HPA for the decode pool (no VariantAutoscaling CR).
kubectl apply -f $DEMO/manifests/06-hpa.yaml
```

> The `sed -i ''` above is BSD/macOS syntax; on GNU/Linux use `sed -i`.
> `deploy/install.sh` needs **`yq`** on your PATH — without it the run dies at
> "Enabling scale-to-zero in WVA ConfigMap" with `yq: command not found`, *after* the
> controller has already been applied.

Verify the whole chain:
```bash
# 1. WVA discovered the annotated HPA and made a decision
kubectl logs -n workload-variant-autoscaler-system deploy/wva-controller-manager | grep scaling-decision
# ...{"name":"optimized-baseline-decode-hpa","curr":2,"tgt":1,"action":"scale-down"}

# 2. The metric reached Prometheus
#    wva_desired_replicas{variant_name="optimized-baseline-decode-hpa",exported_namespace="llm-d"} 1

# 3. prometheus-adapter re-published it as an external metric
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/llm-d/wva_desired_replicas"

# 4. The HPA consumed it and moved the Deployment
kubectl get hpa -n llm-d
# NAME                            REFERENCE                              TARGETS        MINPODS MAXPODS REPLICAS
# optimized-baseline-decode-hpa   Deployment/optimized-baseline-decode   500m/1 (avg)   1       4       2
```

> [!NOTE]
> On no-GPU Kind, WVA logs an `AcceleratorNotResolved` warning ("Cannot resolve accelerator
> type from Deployment nodeSelector/nodeAffinity"). This is **expected and non-fatal** —
> `wva_desired_replicas` is still emitted (with `accelerator_type="unresolved"`) so the HPA
> scales normally; only accelerator-specific capacity metrics are withheld.

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

The install script now loads **seven** dashboards (it previously shipped five — `llm-d Inference Gateway` and `llm-d SGLang Overview` were added upstream):

| Dashboard | Content |
|---|---|
| **llm-d vLLM Overview** | Token throughput, request rates, TTFT |
| **llm-d Failure & Saturation** | Error rates, queue depth, preemptions |
| **llm-d Diagnostic Drill-Down** | Per-pod detailed metrics |
| **llm-d Performance (KV Cache)** | KV cache utilization over time |
| **P/D Coordinator Metrics** | Prefill/Decode disaggregation |
| **llm-d Inference Gateway** | Gateway-level request/routing metrics |
| **llm-d SGLang Overview** | SGLang backend equivalent of the vLLM overview (empty in this demo — the sim exposes `vllm:*`) |

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
3. **Service** → `llm-d-router/epp` → a 5-span tree: `gateway.request` →
   `gateway.request_orchestration` → `run_scheduler_profile` → `filter_endpoints` +
   `pick_endpoints`. Open `pick_endpoints` to see `llm_d.epp.picker.top_endpoints` /
   `top_scores` — the actual routing decision for that request.
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
$LLMD/guides/recipes/router/base.values.yaml
  └── EPP image, proxy defaults, shared settings

$LLMD/guides/optimized-baseline/router/optimized-baseline.values.yaml
  └── 4-plugin scoring: queue + kv-cache + prefix-cache + no-hit-lru

$LLMD/guides/recipes/router/features/monitoring.values.yaml
  └── ServiceMonitor for EPP metrics (Prometheus scraping)

$DEMO/helm-values/tracing.values.yaml
  └── EPP OTLP tracing → http://otel-collector:4317 (100% sampling)

$DEMO/helm-values/kind-overrides.values.yaml
  └── Reduced EPP/proxy resources for local kind cluster

$DEMO/helm-values/proxy-tracing-ipp.values.yaml
  └── Full Envoy config override: IPP ext_proc filter (before EPP),
      OpenTelemetry trace root, ipp_ext_proc + otel_collector clusters

$DEMO/helm-values/ipp.values.yaml   (payload-processor chart)
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
bash $LLMD/guides/recipes/observability/install-prometheus-grafana.sh --uninstall

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
kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.9.2-arm64 --name llm-d
```

### Traffic generator returns 404

EPP Service HTTP port is **80** (not 8081): set `ROUTER_URL=http://llm-d-epp:80`.

### Prometheus not scraping EPP

```bash
kubectl get servicemonitor -n llm-d
kubectl port-forward -n llm-d svc/llm-d-epp 9090:9090
curl http://localhost:9090/metrics | grep inference_extension | head -5
```
