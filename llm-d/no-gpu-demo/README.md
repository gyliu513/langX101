# llm-d Observability End-to-End Demo (No GPU)

This guide walks through a complete llm-d observability setup on a local Kind cluster **without any GPU**. It uses [llm-d-inference-sim](https://github.com/llm-d/llm-d-inference-sim) to simulate vLLM prefill and decode pods, exposing real Prometheus-compatible metrics that are scraped by the monitoring stack.

> **Chinese version:** [README-zh.md](./README-zh.md)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Kind Cluster                                               │
│                                                             │
│  ┌─────────────────┐     ┌──────────────────────────────┐  │
│  │  llm-d-demo ns  │     │  llm-d-monitoring ns          │  │
│  │                 │     │                              │  │
│  │  [prefill pod]  │◄────│  Prometheus (HTTPS/TLS)      │  │
│  │  [decode pod 1] │◄────│  Grafana                     │  │
│  │  [decode pod 2] │◄────│  Alertmanager                │  │
│  │  [traffic-gen]  │     │                              │  │
│  │                 │     │  PodMonitor CRDs             │  │
│  │  PodMonitors    │────►│  (auto-discovery)            │  │
│  └─────────────────┘     └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Components

| Component | Namespace | Description |
|---|---|---|
| `llm-d-sim-prefill` | `llm-d-demo` | Simulated prefill inference pod (1 replica) |
| `llm-d-sim-decode` | `llm-d-demo` | Simulated decode inference pods (2 replicas) |
| `llm-d-traffic-gen` | `llm-d-demo` | Continuous traffic generator |
| `PodMonitor` (x2) | `llm-d-demo` | Prometheus scrape configuration |
| Prometheus (HTTPS) | `llm-d-monitoring` | Metrics storage (pre-installed) |
| Grafana | `llm-d-monitoring` | Visualization (pre-installed) |

---

## Prerequisites

- **Kind cluster** (tested with Kind v0.31.0, Kubernetes v1.35)
- **kubectl** configured to point at your Kind cluster
- **Helm** v3.10+
- **Docker** (or compatible container runtime)
- **Prometheus + Grafana** already installed in `llm-d-monitoring` (see [prometheus-grafana-stack.md](../prometheus-grafana-stack.md))

### Verify prerequisites

```bash
kubectl cluster-info
kubectl get pods -n llm-d-monitoring
# Should show prometheus and grafana pods Running
```

---

## Step 1: Pull and Load the Simulator Image

The inference simulator image must be loaded into the Kind cluster nodes. On Apple Silicon (arm64), pull the architecture-specific image:

```bash
# Pull the arm64 manifest for Apple Silicon Kind nodes
docker pull ghcr.io/llm-d/llm-d-inference-sim:v0.8.0
ARM64_DIGEST=$(docker manifest inspect ghcr.io/llm-d/llm-d-inference-sim:v0.8.0 2>/dev/null | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  [print(m['digest']) for m in d.get('manifests',[]) \
  if m.get('platform',{}).get('architecture')=='arm64']")

docker pull ghcr.io/llm-d/llm-d-inference-sim@${ARM64_DIGEST}
docker tag ghcr.io/llm-d/llm-d-inference-sim@${ARM64_DIGEST} \
  ghcr.io/llm-d/llm-d-inference-sim:v0.8.0-arm64
```

> **Note:** On x86_64 hosts, use `v0.8.0` directly without the `-arm64` suffix, and skip the manifest inspection step.

Load the image into all Kind nodes (replace `kueue-demo` with your Kind cluster name):

```bash
kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.8.0-arm64 \
  --name kueue-demo
```

---

## Step 2: Deploy the Simulator Pods

Apply the manifests in the `manifests/` directory:

```bash
cd docs/monitoring/no-gpu-demo/manifests

# Create namespace
kubectl apply -f 00-namespace.yaml

# Deploy prefill simulator (1 replica)
kubectl apply -f 01-prefill.yaml

# Deploy decode simulator (2 replicas)
kubectl apply -f 02-decode.yaml

# Create PodMonitors (Prometheus scrape config)
kubectl apply -f 03-podmonitors.yaml

# Deploy traffic generator
kubectl apply -f 04-traffic-generator.yaml
```

Wait for all pods to be ready:

```bash
kubectl wait --for=condition=Ready pods --all -n llm-d-demo --timeout=120s
kubectl get pods -n llm-d-demo
```

Expected output:

```
NAME                                 READY   STATUS    RESTARTS   AGE
llm-d-sim-decode-76b759d585-2zkh8    1/1     Running   0          60s
llm-d-sim-decode-76b759d585-l6tbk    1/1     Running   0          60s
llm-d-sim-prefill-658677fd5c-vngsv   1/1     Running   0          60s
llm-d-traffic-gen-69c68bdfd4-x9x8j   1/1     Running   0          60s
```

---

## Step 3: Verify Metrics Endpoints

The simulator exposes Prometheus-compatible metrics on port 8000 at `/metrics`:

```bash
# Port-forward to prefill pod
kubectl port-forward -n llm-d-demo deploy/llm-d-sim-prefill 18000:8000 &

# Check available metrics
curl -s http://localhost:18000/metrics | grep '^# HELP'
```

Expected metrics:

```
# HELP vllm:cache_config_info Information of the LLMEngine CacheConfig.
# HELP vllm:e2e_request_latency_seconds Histogram of end to end request latency in seconds.
# HELP vllm:generation_tokens_total Total number of generated tokens.
# HELP vllm:inter_token_latency_seconds Histogram of inter-token latency in seconds.
# HELP vllm:kv_cache_usage_perc Fraction of KV-cache blocks currently in use (from 0 to 1).
# HELP vllm:num_requests_running Number of requests currently running on GPU.
# HELP vllm:num_requests_waiting Number of requests waiting to be processed.
# HELP vllm:prompt_tokens_total Total number of prefill tokens processed.
# HELP vllm:request_decode_time_seconds Histogram of request decode time.
# HELP vllm:request_prefill_time_seconds Histogram of request prefill time.
# HELP vllm:request_success_total Total number of successful requests.
# HELP vllm:time_to_first_token_seconds Histogram of time to first token.
```

Kill the port-forward when done:

```bash
kill %1
```

---

## Step 4: Verify Prometheus Scraping

Prometheus (with TLS) should auto-discover the PodMonitors. Verify:

```bash
# Port-forward Prometheus (HTTPS)
kubectl port-forward -n llm-d-monitoring \
  svc/llmd-kube-prometheus-stack-prometheus 19090:9090 &

# Check targets (note: -k for self-signed cert)
curl -sk https://localhost:19090/api/v1/targets | python3 -c "
import sys, json
d = json.load(sys.stdin)
targets = d.get('data',{}).get('activeTargets',[])
llmd = [t for t in targets if 'llm-d-demo' in str(t)]
print(f'llm-d-demo targets: {len(llmd)}')
for t in llmd:
    print(f'  {t[\"labels\"][\"job\"]} | {t[\"labels\"][\"pod\"]} | {t[\"health\"]}')
"
```

Expected output:

```
llm-d-demo targets: 3
  llm-d-demo/llm-d-sim-decode | llm-d-sim-decode-xxx-yyy | up
  llm-d-demo/llm-d-sim-decode | llm-d-sim-decode-xxx-zzz | up
  llm-d-demo/llm-d-sim-prefill | llm-d-sim-prefill-xxx-yyy | up
```

---

## Step 5: Load Grafana Dashboards

```bash
# From the repo root
cd docs/monitoring/scripts
bash load-llm-d-dashboards.sh llm-d-monitoring
```

This loads the following dashboards into Grafana:

| Dashboard | Description |
|---|---|
| `llm-d-vllm-overview` | vLLM metrics overview: request rates, token throughput, latency |
| `llm-d-failure-saturation-dashboard` | Error rates, queue saturation, preemptions |
| `llm-d-diagnostic-drilldown-dashboard` | Per-pod drill-down diagnostics |
| `llm-performance-kv-cache` | KV cache utilization over time |
| `pd-coordinator-metrics` | Prefill/Decode disaggregation metrics |

---

## Step 6: Access Grafana

```bash
kubectl port-forward -n llm-d-monitoring svc/llmd-grafana 3000:80 &
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

- **Username:** `admin`
- **Password:** `admin`

Navigate to **Dashboards** → select any `llm-d` dashboard. You should see live metrics from the 3 simulated pods.

---

## Step 7: Access Prometheus

```bash
kubectl port-forward -n llm-d-monitoring \
  svc/llmd-kube-prometheus-stack-prometheus 19090:9090 &
```

Open [https://localhost:19090](https://localhost:19090) (accept the self-signed certificate).

---

## Test Cases

### Test Case 1: Token Throughput

**Goal:** Verify token generation metrics are flowing.

**PromQL query:**

```promql
sum by(pod) (rate(vllm:generation_tokens_total[5m]))
```

**Expected:** Non-zero values for all 3 pods, decode pods should show higher throughput than prefill.

```bash
curl -sk "https://localhost:19090/api/v1/query?query=sum+by(pod)+(rate(vllm%3Ageneration_tokens_total%5B5m%5D))" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'{r[\"metric\"].get(\"pod\",\"\")[-30:]}: {float(r[\"value\"][1]):.3f} tok/s') for r in d['data']['result']]"
```

---

### Test Case 2: KV Cache Utilization

**Goal:** Monitor KV cache usage across prefill and decode pods.

**PromQL query:**

```promql
avg by(pod) (vllm:kv_cache_usage_perc)
```

**Expected:** Values between 0 and 1 for all pods; higher traffic → higher cache utilization.

---

### Test Case 3: Request Latency P99

**Goal:** Measure P99 end-to-end request latency.

**PromQL query:**

```promql
histogram_quantile(0.99, sum by(le, pod) (rate(vllm:e2e_request_latency_seconds_bucket[5m])))
```

**Expected:** P99 latency for prefill pods ≈ TTFT (prefill phase only). Decode pods show full E2E latency.

---

### Test Case 4: Prefill vs Decode Throughput

**Goal:** Compare prefill and decode pod behavior.

**PromQL queries:**

```promql
# Prefill pods only
sum by(pod) (rate(vllm:prompt_tokens_total[5m]))

# Decode pods only
sum by(pod) (rate(vllm:generation_tokens_total[5m]))
```

---

### Test Case 5: Request Queue Depth

**Goal:** Detect request queuing (capacity issues).

**PromQL query:**

```promql
sum by(pod) (vllm:num_requests_waiting)
```

**Expected:** Near-zero in normal operation. Under heavy load, decode pods may show queuing first.

---

### Test Case 6: Time to First Token (TTFT)

**Goal:** Measure TTFT latency distribution.

**PromQL query:**

```promql
histogram_quantile(0.90, sum by(le, pod) (rate(vllm:time_to_first_token_seconds_bucket[5m])))
```

---

### Test Case 7: Error Rate

**Goal:** Verify error metrics appear when bad requests are sent. The traffic generator injects a bad request every 7th request.

**PromQL query:**

```promql
rate(vllm:request_success_total{finished_reason!="stop"}[5m])
```

Or use the traffic generator error injection directly:

```bash
# Manually inject an error request
kubectl port-forward -n llm-d-demo svc/llm-d-sim-decode-svc 18000:8000 &
curl -s -X POST http://localhost:18000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"nonexistent","messages":[{"role":"user","content":"test"}],"max_tokens":10}'
kill %1 2>/dev/null
```

---

### Test Case 8: Multi-Pod Request Distribution

**Goal:** Verify load is distributed across decode replicas.

**PromQL query:**

```promql
sum by(pod) (rate(vllm:request_success_total[5m]))
```

**Expected:** Roughly equal distribution between the 2 decode pods.

---

## Traffic Generation

The `llm-d-traffic-gen` Deployment runs continuously, sending requests every 3 seconds:

- **Normal requests** → decode pods (200 OK)
- **Prefill requests** → prefill pod every 3rd request (simulates P/D routing)
- **Error requests** → nonexistent model every 7th request (generates error metrics)

Monitor traffic generation:

```bash
kubectl logs -n llm-d-demo deploy/llm-d-traffic-gen -f
```

### Manual traffic generation

You can also run the existing script against the simulator:

```bash
kubectl port-forward -n llm-d-demo svc/llm-d-sim-decode-svc 18000:8000 &

ENDPOINT=http://localhost:18000/v1 \
MODEL_NAME=Qwen/Qwen2.5-0.5B-Instruct \
docs/monitoring/scripts/generate-traffic-basic.sh 5

kill %1 2>/dev/null
```

---

## Observability Summary

After running the demo, you should observe:

| Metric | Value Range | Notes |
|---|---|---|
| `vllm:kv_cache_usage_perc` | 0–1 | Increases with more traffic |
| `vllm:generation_tokens_total` | Monotonically increasing | Counter; use `rate()` for throughput |
| `vllm:num_requests_running` | 0–N | Spikes during active requests |
| `vllm:num_requests_waiting` | 0–N | Increases under load |
| `vllm:e2e_request_latency_seconds` | Histogram | P50/P90/P99 via `histogram_quantile()` |
| `vllm:time_to_first_token_seconds` | Histogram | Prefill phase timing |
| `vllm:request_success_total` | Counter | By `finished_reason` label |

---

## Cleanup

```bash
kubectl delete namespace llm-d-demo
pkill -f "port-forward" 2>/dev/null || true
```

To also remove the monitoring stack:

```bash
docs/monitoring/scripts/install-prometheus-grafana.sh --uninstall
```

---

## Troubleshooting

### Pods stuck in `ImagePullBackOff`

The image must be pre-loaded into Kind nodes:

```bash
kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.8.0-arm64 --name <your-cluster-name>
```

### Prometheus not scraping pods

Check that PodMonitors are visible in Prometheus:

```bash
kubectl get podmonitors -n llm-d-demo
# Prometheus must have podMonitorNamespaceSelector: {} (all namespaces)
kubectl get prometheus -n llm-d-monitoring -o yaml | grep -A5 podMonitor
```

### Metrics endpoint returns empty

Check simulator is running:

```bash
kubectl logs -n llm-d-demo deploy/llm-d-sim-prefill
kubectl port-forward -n llm-d-demo deploy/llm-d-sim-prefill 18000:8000 &
curl http://localhost:18000/health
```

### Grafana shows "No data"

Wait at least 1 minute after loading dashboards for the Grafana sidecar to pick them up. Check dashboard datasource is set to **Prometheus**.
