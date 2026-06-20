# llm-d on Kind — Gateway API Mode with Full Observability (Tracing + Metrics)

This document records a **no-GPU, Apple-Silicon (arm64) Kind** deployment of llm-d in
**Gateway API mode** (agentgateway) with a closed observability loop:

- **Distributed tracing** stitched across the gateway hop and the EPP into one Jaeger trace.
- **Metrics** scraped from the EPP and the vLLM model server into Prometheus and visualized in Grafana.

> Why Gateway API mode and not the standalone (self-managed Envoy) chart? The standalone
> Envoy roots its own trace and **does not propagate W3C trace context to its `ext_proc`
> servers**, so the EPP span (`gateway.request`) is always an orphan root. A real
> Gateway (agentgateway / Istio) propagates the trace context to the EPP `ext_proc`,
> which the EPP adopts (PR #1514) — so the gateway hop and the EPP land in **one** trace.

---

## 1. System Architecture / 系统架构

```text
                          ┌──────────────────────── observability ────────────────────────┐
                          │                                                                │
 client ─HTTP─▶ agentgateway ──ext_proc(W3C traceparent)──▶  EPP  ──route──▶ vLLM (Qwen2.5-0.5B, CPU)
              (Gateway API,        (endpoint picker /                 │
               trace ROOT)          InferencePool ext)                │  KV-events (ZMQ :5556)
                   │                      │                           │
   spans ──────────┼──────────────────────┼──────────── metrics ──────┼─────────────
                   ▼                      ▼                           ▼
         OTLP gRPC :4317           OTLP gRPC :4317            ServiceMonitor / PodMonitor
                   └────────▶ otel-collector ───▶ Jaeger          │
                                                                   ▼
                                                            Prometheus ───▶ Grafana
```

| Component | Namespace | Role |
| --- | --- | --- |
| `agentgateway` (control plane) | `agentgateway-system` | Gateway API + Inference Extension controller; provisions the data-plane proxy and pushes config via xDS |
| `llm-d-inference-gateway` (data plane) | `llm-d` | The proxy. Trace **root** span `POST /*`; propagates W3C `traceparent` into the EPP `ext_proc` call |
| `llm-d-epp` | `llm-d` | llm-d Router **Endpoint Picker** (Gateway API Inference Extension / `ext_proc`). Emits `gateway.request` + scheduling spans, exposes `llm_d_epp_*` metrics |
| `precise-prefix-vllm` | `llm-d` | Real **vLLM CPU** model server (`Qwen2.5-0.5B-Instruct`); exposes `vllm:*` metrics, publishes KV-events on ZMQ `:5556` |
| `otel-collector` + `jaeger` | `llm-d` | Trace pipeline (OTLP gRPC → Jaeger) |
| `kube-prometheus-stack` (`llmd` release) | `llm-d-monitoring` | Prometheus + Grafana + operator; scrapes the `ServiceMonitor`/`PodMonitor` |
| `HTTPRoute` / `InferencePool` | `llm-d` | Gateway → InferencePool wiring; the InferencePool references the EPP as its endpoint-picker extension |

Images are **built from `upstream/main`** of the respective llm-d repos (arm64):

```console
gyliu-cary@Mac llm-d % docker images | grep main
ghcr.io/llm-d/llm-d-router-endpoint-picker-dev    main   40e47a2df975   93.5MB
ghcr.io/llm-d/llm-d-routing-sidecar               main   496cd2e510a0   57.9MB
ghcr.io/llm-d/llm-d-inference-payload-processor   main   a66f2f6a7250   74.2MB
```

---

## 2. Workflow

**Request path**

1. Client `POST /v1/chat/completions` → `llm-d-inference-gateway` (ClusterIP `:80`).
2. agentgateway starts the **root span** `POST /*`, injects a W3C `traceparent`, and calls the EPP via `ext_proc`.
3. EPP extracts the `traceparent` (PR #1514), starts `gateway.request` **as a child** of the gateway span, runs scheduling (`gateway.request_orchestration`), and picks an endpoint from the `InferencePool`.
4. agentgateway proxies the request to the chosen vLLM pod; vLLM returns the completion.

**Trace path** — agentgateway span and EPP spans are both exported (OTLP gRPC `:4317`) to `otel-collector` → `jaeger`, sharing one trace ID:

```console
gyliu-cary@Mac llm-d % # one trace, two services, parent→child
[llm-d-inference-gateway] POST /*
  [llm-d-router/epp] gateway.request
    [llm-d-router/epp] gateway.request_orchestration
```

**Metric path** — the `ServiceMonitor` (EPP) and `PodMonitor` (vLLM) are discovered by the Prometheus operator; Prometheus scrapes `:9090/metrics` (EPP) and the vLLM `/metrics`, stores them in its TSDB, and Grafana renders the llm-d dashboards.

---

## 3. Installation Steps / 安装步骤

Set up shared variables (adjust to your checkouts):

```console
gyliu-cary@Mac llm-d % export LLMD_REPO=$HOME/go/src/github.com/llm-d/llm-d
gyliu-cary@Mac llm-d % export ROUTER_REPO=$HOME/go/src/github.com/llm-d/llm-d-router
gyliu-cary@Mac llm-d % export IPP_REPO=$HOME/go/src/github.com/llm-d/llm-d-inference-payload-processor
gyliu-cary@Mac llm-d % export DEMO=$HOME/go/src/github.com/gyliu513/langX101/llm-d/llm-d-full-demo
```

### 3.1 Build images from `upstream/main` (arm64)

```console
gyliu-cary@Mac llm-d % cd $ROUTER_REPO && git fetch upstream && git checkout upstream/main
gyliu-cary@Mac llm-d % docker build --platform linux/arm64 -f Dockerfile.epp \
  -t ghcr.io/llm-d/llm-d-router-endpoint-picker-dev:main .
gyliu-cary@Mac llm-d % docker build --platform linux/arm64 -f Dockerfile.sidecar \
  -t ghcr.io/llm-d/llm-d-routing-sidecar:main .
gyliu-cary@Mac llm-d % cd $IPP_REPO && git fetch upstream && git checkout upstream/main
gyliu-cary@Mac llm-d % docker build --platform linux/arm64 -f Dockerfile \
  -t ghcr.io/llm-d/llm-d-inference-payload-processor:main .
```

> Note: `llm-d-kv-cache` is a Go library (pinned in the router `go.mod` at `v0.9.0`, which
> equals its `upstream/main`), not a separate image — building the EPP already includes its
> observability fixes.

### 3.2 Create the Kind cluster and load images

```console
gyliu-cary@Mac llm-d % kind create cluster --config $DEMO/kind/kind-config.yaml
gyliu-cary@Mac llm-d % kind load docker-image ghcr.io/llm-d/llm-d-router-endpoint-picker-dev:main --name llm-d
gyliu-cary@Mac llm-d % kubectl create namespace llm-d
```

### 3.3 Install Gateway API + GAIE CRDs

```console
gyliu-cary@Mac llm-d % kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml
gyliu-cary@Mac llm-d % kubectl apply -k "https://github.com/llm-d/llm-d-router/config/crd?ref=v0"
```

### 3.4 Install the agentgateway control plane

```console
gyliu-cary@Mac llm-d % helm upgrade --install agentgateway-crds \
  oci://cr.agentgateway.dev/charts/agentgateway-crds \
  --namespace agentgateway-system --create-namespace --version v1.1.0
gyliu-cary@Mac llm-d % helm upgrade --install agentgateway \
  oci://cr.agentgateway.dev/charts/agentgateway \
  --namespace agentgateway-system --create-namespace --version v1.1.0 \
  --set inferenceExtension.enabled=true
gyliu-cary@Mac llm-d % kubectl get gatewayclass agentgateway
NAME           CONTROLLER                      ACCEPTED   AGE
agentgateway   agentgateway.dev/agentgateway   True       2s
```

### 3.5 Deploy the Gateway

```console
gyliu-cary@Mac llm-d % kubectl apply -k $LLMD_REPO/guides/recipes/gateway/agentgateway -n llm-d
gyliu-cary@Mac llm-d % kubectl get gateway -n llm-d
NAME                      CLASS          ADDRESS   PROGRAMMED   AGE
llm-d-inference-gateway   agentgateway             True         8s
```

### 3.6 Deploy OTel Collector + Jaeger

```console
gyliu-cary@Mac llm-d % bash $LLMD_REPO/guides/recipes/observability/install-otel-collector-jaeger.sh -n llm-d
```

### 3.7 Install the router in Gateway API mode (`llm-d-router-gateway-dev`)

`tracing.values.yaml` turns on EPP span export; the override file sets the EPP image
`pullPolicy: IfNotPresent` (so Kind uses the locally-built image) and the model-server
selector. The chart also creates the `HTTPRoute` to the Gateway.

```console
gyliu-cary@Mac llm-d % helm install llm-d oci://ghcr.io/llm-d/charts/llm-d-router-gateway-dev \
  -f $LLMD_REPO/guides/recipes/router/base.values.yaml \
  -f $LLMD_REPO/guides/optimized-baseline/router/optimized-baseline.values.yaml \
  -f $LLMD_REPO/guides/recipes/router/features/monitoring.values.yaml \
  -f $DEMO/helm-values/tracing.values.yaml \
  -f $DEMO/helm-values/gw-kind.values.yaml \
  --set provider.name=none \
  --set httpRoute.create=true \
  --set httpRoute.inferenceGatewayName=llm-d-inference-gateway \
  -n llm-d --version v0
gyliu-cary@Mac llm-d % kubectl get httproute,inferencepool -n llm-d
NAME                                        HOSTNAMES   AGE
httproute.gateway.networking.k8s.io/llm-d               5s
NAME                                              AGE
inferencepool.inference.networking.k8s.io/llm-d   5s
```

`$DEMO/helm-values/gw-kind.values.yaml`:

```yaml
router:
  epp:
    replicas: 1
    image:
      registry: ghcr.io/llm-d
      repository: llm-d-router-endpoint-picker-dev
      tag: main
      pullPolicy: IfNotPresent
    resources:
      requests: { cpu: "500m", memory: "512Mi" }
      limits:   { cpu: "2", memory: "2Gi" }
  modelServers:
    matchLabels:
      llm-d.ai/guide: "precise-prefix-cache-routing"
```

### 3.8 Deploy a real vLLM CPU model server (arm64)

The `vllm/vllm-openai-cpu:v0.19.1` image has an **arm64** variant (native, no emulation).
Serves `Qwen2.5-0.5B-Instruct`, block-size 64, publishing KV-events on ZMQ `:5556`.

```console
gyliu-cary@Mac llm-d % docker pull --platform linux/arm64 docker.io/vllm/vllm-openai-cpu:v0.19.1
gyliu-cary@Mac llm-d % kind load docker-image docker.io/vllm/vllm-openai-cpu:v0.19.1 --name llm-d
gyliu-cary@Mac llm-d % kubectl create secret generic llm-d-hf-token -n llm-d --from-literal=HF_TOKEN=<your-hf-token>
gyliu-cary@Mac llm-d % kubectl apply -f $DEMO/manifests/optional/cpu-vllm/model-server.yaml
gyliu-cary@Mac llm-d % kubectl rollout status deploy/precise-prefix-vllm -n llm-d --timeout=300s
```

> **Kind/Docker-on-Mac gotcha:** vLLM CPU crashes with
> `AssertionError: Not enough allowed NUMA nodes ... Allowed NUMA nodes are []`
> because containers expose no NUMA topology. Fix by pinning OMP threads in the pod env:
> `VLLM_CPU_OMP_THREADS_BIND="0-3"`.

### 3.9 Enable gateway tracing export (AgentgatewayPolicy)

This makes agentgateway export **its own** spans to `otel-collector` and root a trace even
for requests without an incoming `traceparent` (`randomSampling: "true"`).

```console
gyliu-cary@Mac llm-d % kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: gateway-tracing
  namespace: llm-d
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: llm-d-inference-gateway
  frontend:
    tracing:
      backendRef:
        kind: Service
        name: otel-collector
        port: 4317
      protocol: GRPC
      randomSampling: "true"
EOF
```

### 3.10 Install Prometheus + Grafana

```console
gyliu-cary@Mac llm-d % bash $LLMD_REPO/guides/recipes/observability/install-prometheus-grafana.sh
gyliu-cary@Mac llm-d % kubectl get pods -n llm-d-monitoring
NAME                                                     READY   STATUS    RESTARTS   AGE
llmd-grafana-c855676f5-rrsh6                             3/3     Running   0          75s
llmd-kube-prometheus-stack-operator-cdc8d9876-vjc4v      1/1     Running   0          75s
prometheus-llmd-kube-prometheus-stack-prometheus-0       2/2     Running   0          66s
```

### Final state

```console
gyliu-cary@Mac llm-d % kubectl get pod -A
NAMESPACE             NAME                                          READY   STATUS    RESTARTS   AGE
agentgateway-system   agentgateway-5448f46756-ksp8r                 1/1     Running   0          3h10m
llm-d                 jaeger-587f6c758f-2x59j                       1/1     Running   0          5h32m
llm-d                 llm-d-epp-f9594fc45-p9bqb                     1/1     Running   0          3h9m
llm-d                 llm-d-inference-gateway-7b99465d6-9bp2w       1/1     Running   0          3h10m
llm-d                 otel-collector-7fd7c98767-whnpn               1/1     Running   0          5h32m
llm-d                 precise-prefix-vllm-6b75f49d4c-69m4x          1/1     Running   0          3h49m
llm-d-monitoring      llmd-grafana-c855676f5-rrsh6                  3/3     Running   0          6m38s
llm-d-monitoring      prometheus-llmd-kube-prometheus-stack-...-0   2/2     Running   0          6m29s

gyliu-cary@Mac llm-d % helm list -A
NAME                NAMESPACE             CHART                          STATUS
agentgateway        agentgateway-system   agentgateway-v1.1.0            deployed
agentgateway-crds   agentgateway-system   agentgateway-crds-v1.1.0       deployed
llm-d               llm-d                 llm-d-router-gateway-dev-v0     deployed
llmd                llm-d-monitoring      kube-prometheus-stack-86.1.0   deployed
```

---

## 4. Test Steps / 测试步骤

### 4.1 Trigger a request (and a connected trace)

```console
gyliu-cary@Mac llm-d % GWIP=$(kubectl get svc llm-d-inference-gateway -n llm-d -o jsonpath='{.spec.clusterIP}')
gyliu-cary@Mac llm-d % kubectl run trig --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
  curl -sS -o /dev/null -w "http=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","messages":[{"role":"user","content":"hi"}],"max_tokens":8}'
http=200
```

### 4.2 Verify the stitched trace in Jaeger

```console
gyliu-cary@Mac llm-d % kubectl port-forward -n llm-d svc/jaeger-collector 16686:16686 &
gyliu-cary@Mac llm-d % # open http://localhost:16686 → Service = llm-d-inference-gateway → Find Traces
gyliu-cary@Mac llm-d % # the trace contains both services, gateway → EPP:
[llm-d-inference-gateway] POST /*
  [llm-d-router/epp] gateway.request
    [llm-d-router/epp] gateway.request_orchestration
```

Confirm the EPP span is no longer an orphan root (it has the gateway as parent):

```console
gyliu-cary@Mac llm-d % curl -s "http://localhost:16686/api/services" | python3 -c "import sys,json;print(sorted(json.load(sys.stdin)['data']))"
['jaeger', 'llm-d-inference-gateway', 'llm-d-router/epp', ...]
```

### 4.3 Verify the metrics scrape loop in Prometheus

```console
gyliu-cary@Mac llm-d % kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9091:9090 &
gyliu-cary@Mac llm-d % # Status → Targets: both UP
gyliu-cary@Mac llm-d % curl -s "http://localhost:9091/api/v1/targets?state=active" | grep -o 'serviceMonitor/llm-d/llm-d-epp-monitor\|podMonitor/llm-d/decode'
serviceMonitor/llm-d/llm-d-epp-monitor
podMonitor/llm-d/decode

gyliu-cary@Mac llm-d % curl -s "http://localhost:9091/api/v1/query?query=llm_d_epp_request_total" | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['result'][0]['value'][1])"
12
gyliu-cary@Mac llm-d % curl -s "http://localhost:9091/api/v1/query?query=vllm:num_requests_running" | python3 -c "import sys,json;print(len(json.load(sys.stdin)['data']['result']),'series')"
1 series
```

### 4.4 View the Grafana dashboards

```console
gyliu-cary@Mac llm-d % kubectl port-forward -n llm-d-monitoring svc/llmd-grafana 3000:80 &
gyliu-cary@Mac llm-d % # open http://localhost:3000  (admin / admin)
gyliu-cary@Mac llm-d % # Dashboards: "llm-d vLLM Overview", "llm-d Performance Dashboard", ...
```

---

## Observability verification summary

| Item | How verified | Result |
| --- | --- | --- |
| EPP metric rename (`llm_d_router_epp` → `llm_d_epp`, #1661) | `llm_d_epp_request_total` in Prometheus TSDB | ✅ live |
| IPP standardized OTel naming (#164) | Jaeger service `llm-d-inference-payload-processor` | ✅ live |
| EPP span namespace `llm_d.epp.*` (#1670) | `produce_precise_prefix_cache` span attrs (precise-prefix path) | ✅ live |
| kv-cache index tracing (#653 / #637) | `llm_d.kv_cache.index{,.add}` spans with real vLLM KV-events | ✅ live |
| Upstream traceparent adoption (#1514) | gateway → EPP stitched trace (Gateway API mode) | ✅ live |
| Metrics scrape loop | Prometheus targets UP + TSDB + Grafana dashboards | ✅ closed loop |

> The standalone (self-managed Envoy) chart **cannot** stitch the proxy hop to the EPP
> (Envoy injects `traceparent` only at the router, after `ext_proc`; it sends no trace
> context — neither HTTP header nor gRPC metadata — to the EPP). This is why this demo
> uses the Gateway API mode, which is also llm-d's recommended production topology.
