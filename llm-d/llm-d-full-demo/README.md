# llm-d Full Stack Observability Demo (No GPU)

This guide deploys the **complete llm-d stack** — real EPP router, Envoy proxy, InferencePool, and inference-sim as model server — on a local Kind cluster **without GPU**. It provides end-to-end observability with **Prometheus** (metrics), **Grafana** (dashboards), and **Jaeger** (distributed tracing).

> **中文版本：** [README-zh.md](./README-zh.md)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Kind Cluster (single node, 14 CPU / 23 GB)                                │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  llm-d namespace                                                     │   │
│  │                                                                      │   │
│  │   Client                                                             │   │
│  │     │ HTTP :80                                                       │   │
│  │     ▼                                                                │   │
│  │  ┌─────────────────────────────────────────────┐                    │   │
│  │  │  llm-d-epp Pod (2 containers)               │                    │   │
│  │  │                                             │                    │   │
│  │  │  ┌─────────────┐   gRPC    ┌─────────────┐ │                    │   │
│  │  │  │   Envoy     │◄─────────►│    EPP      │ │                    │   │
│  │  │  │   Proxy     │  :9002    │  (Endpoint  │ │                    │   │
│  │  │  │   :8081     │           │   Picker)   │ │                    │   │
│  │  │  └──────┬──────┘           └──────┬──────┘ │                    │   │
│  │  └─────────┼───────────────────────── ┼────────┘                    │   │
│  │            │ route to selected pod    │ OTLP traces                 │   │
│  │            │                          ▼                             │   │
│  │            │              ┌────────────────────┐                   │   │
│  │            │              │   OTel Collector   │                   │   │
│  │            │              │      :4317         │                   │   │
│  │            │              └─────────┬──────────┘                   │   │
│  │            │                        │ OTLP forward                 │   │
│  │            │                        ▼                             │   │
│  │            │              ┌────────────────────┐                   │   │
│  │            │              │      Jaeger        │                   │   │
│  │            │              │    UI :16686       │                   │   │
│  │            │              └────────────────────┘                   │   │
│  │            │                                                       │   │
│  │            ▼  InferencePool "llm-d"                                │   │
│  │     ┌──────────┐    ┌──────────┐                                   │   │
│  │     │ decode-0 │    │ decode-1 │  (inference-sim, port 8000)       │   │
│  │     └──────────┘    └──────────┘                                   │   │
│  │          │ OTLP traces                                              │   │
│  │          └──────────────► OTel Collector ──► Jaeger               │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  llm-d-monitoring namespace                                          │   │
│  │                                                                      │   │
│  │  Prometheus (HTTPS/TLS) ◄── ServiceMonitor (EPP :9090)              │   │
│  │                         ◄── PodMonitor (model servers :8000)        │   │
│  │  Grafana ◄── 5 llm-d dashboards                                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

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

---

## Components

| Component | Namespace | Kind | Description |
|---|---|---|---|
| `llm-d-epp` | `llm-d` | Pod (2 containers) | **Envoy proxy** (port 80→8081) + **EPP** (gRPC ext_proc :9002) |
| `InferencePool/llm-d` | `llm-d` | CR | Watches pods with label `llm-d.ai/guide=optimized-baseline` |
| `InferenceObjective/llm-d-standard` | `llm-d` | CR | Priority=0 flow-control objective |
| `optimized-baseline-decode` | `llm-d` | Deployment (2 replicas) | inference-sim acting as vLLM model server |
| `otel-collector` | `llm-d` | Deployment | Receives OTLP traces, filters noise, forwards to Jaeger |
| `jaeger` | `llm-d` | Deployment | Trace storage + UI (port 16686) |
| `ServiceMonitor/llm-d-epp-monitor` | `llm-d` | CR | Prometheus scrapes EPP metrics (:9090) |
| `PodMonitor/llm-d-model-servers` | `llm-d` | CR | Prometheus scrapes model server metrics (:8000) |
| Prometheus (HTTPS/TLS) | `llm-d-monitoring` | StatefulSet | Metrics storage |
| Grafana | `llm-d-monitoring` | Deployment | 5 pre-loaded llm-d dashboards |

### Observability Coverage

| Signal | Tool | Sources | Count |
|---|---|---|---|
| **Metrics** | Prometheus + Grafana | EPP (ServiceMonitor) + model servers (PodMonitor) | 35+ EPP + 41 vLLM |
| **Traces** | Jaeger + OTel Collector | EPP (`llm-d-router/epp`) + model servers | 2 spans/request |

---

## Prerequisites

- **Kind** v0.29+ and **Docker Desktop** (14+ CPUs, 20+ GB RAM allocated)
- **kubectl**, **Helm** v3.10+
- **jq**, **python3**
- llm-d repo cloned: `git clone https://github.com/llm-d/llm-d.git && cd llm-d`

---

## Installation Steps

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

# 3b. GAIE CRDs (InferencePool, InferenceObjective)
kubectl apply -k \
  "https://github.com/kubernetes-sigs/gateway-api-inference-extension/config/crd?ref=v1.5.0"
```

Verify:
```bash
kubectl get crd | grep -E "inferencep|monitoring.coreos"
```

---

### Step 4: Install Prometheus + Grafana

```bash
bash docs/monitoring/scripts/install-prometheus-grafana.sh --enable-tls
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
  -n llm-d \
  --version v0
```

The `tracing.values.yaml` enables EPP to export spans to `http://otel-collector:4317`.

---

### Step 6: Deploy OTel Collector + Jaeger

Both must run in the same namespace (`llm-d`) so components can reach the collector at `http://otel-collector:4317`.

```bash
bash docs/monitoring/scripts/install-otel-collector-jaeger.sh -n llm-d
```

This deploys:
- **OTel Collector** — receives OTLP gRPC on :4317, filters `/metrics` scrape spans, batches and forwards to Jaeger
- **Jaeger** (all-in-one, in-memory) — trace storage + UI on :16686

---

### Step 7: Deploy Model Servers

```bash
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/01-model-servers.yaml
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/02-inferencemodel.yaml
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/03-podmonitor.yaml
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
kubectl wait --for=condition=Ready pods --all -n llm-d --timeout=90s
kubectl get pods -n llm-d
```

Expected:
```
NAME                                        READY   STATUS
jaeger-xxx                                  1/1     Running
llm-d-epp-xxx                               2/2     Running
llm-d-traffic-gen-xxx                       1/1     Running
optimized-baseline-decode-xxx (x2)          1/1     Running
otel-collector-xxx                          1/1     Running
```

---

### Step 8: Deploy Traffic Generator

```bash
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/04-traffic-generator.yaml
```

```bash
kubectl logs -n llm-d deploy/llm-d-traffic-gen -f
# req=5 [200] Describe transformer architecture.
# req=6 [200] How does load balancing work?
```

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

In the Jaeger UI:
1. **Service** → select `llm-d-router/epp`
2. **Find Traces** → see real EPP routing spans
3. Click any trace to see span details:
   - `gateway.request` — full request lifecycle
   - `gateway.request_orchestration` — EPP scheduling decision

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
| `OTEL_SERVICE_NAME` | `llm-d-model-server` | Service name in Jaeger |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | OTel Collector endpoint |
| `OTEL_TRACES_EXPORTER` | `otlp` | Export protocol |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | Inherits parent trace decision |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | 100% sampling rate |

### OTel Collector Pipeline

```yaml
receivers:  otlp (gRPC :4317, HTTP :4318)
processors:
  - filter/drop-metrics-scraping   # remove /metrics polling spans
  - batch (1024 spans, 1s timeout)
exporters:  otlp/jaeger → jaeger-collector:4317
```

---

## Cleanup

```bash
# Remove all workloads (OTel + Jaeger + model servers + EPP)
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
