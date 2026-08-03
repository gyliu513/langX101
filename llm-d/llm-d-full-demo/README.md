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

Images are **built from `upstream/main`** of the respective llm-d repos (arm64).
Only the **EPP** image is required by this Gateway-mode demo; the sidecar and the
payload processor belong to the optional P/D and IPP paths and are listed here
because Step 3.1 builds them:

```console
gyliu-cary@Mac llm-d % docker images | grep main
ghcr.io/llm-d/llm-d-router-endpoint-picker-dev    main   51b24ccadc27   94.4MB
ghcr.io/llm-d/llm-d-routing-sidecar               main   3d43472e4bb9   58.3MB
ghcr.io/llm-d/llm-d-inference-payload-processor   main   9ba6034f43ec   74.4MB
```

> Last verified against `llm-d@4093435f`, `llm-d-router@a86cc45a`,
> `llm-d-inference-payload-processor@cf5d475` (2026-08-03).

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
      [llm-d-router/epp] HTTP POST                      # token-producer -> vllm-render
      [llm-d-router/epp] produce_precise_prefix_cache
        [llm-d-router/epp] llm_d.kv_cache.index
      [llm-d-router/epp] run_scheduler_profile
        [llm-d-router/epp] filter_endpoints
        [llm-d-router/epp] pick_endpoints
      [llm-d-router/epp] llm_d.kv_cache.index.add
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
  -t ghcr.io/llm-d/llm-d-router-endpoint-picker-dev:main .        # required
gyliu-cary@Mac llm-d % docker build --platform linux/arm64 -f Dockerfile.sidecar \
  -t ghcr.io/llm-d/llm-d-routing-sidecar:main .                   # optional (P/D path)
gyliu-cary@Mac llm-d % cd $IPP_REPO && git fetch upstream && git checkout upstream/main
gyliu-cary@Mac llm-d % docker build --platform linux/arm64 -f Dockerfile \
  -t ghcr.io/llm-d/llm-d-inference-payload-processor:main .       # optional (IPP path)
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
gyliu-cary@Mac llm-d % kubectl apply -k "$ROUTER_REPO/config/crd"
# or, without a local checkout:
# kubectl apply -k "https://github.com/llm-d/llm-d-router/config/crd?ref=v0.9.0"
```

> The git ref `v0` does not exist on `llm-d-router` — use a local checkout or `ref=v0.9.0`
> (or any recent release tag).

> llm-d also ships an installer that pins both CRD sets
> (`bash $LLMD_REPO/guides/recipes/gateway/install-gateway-crds.sh`, Gateway API `v1.5.1`
> + GAIE `v1.5.0`). It does **not** install the `llm-d.ai` CRDs
> (`InferenceObjective`, `InferenceModelRewrite`) that the router's `config/crd` adds,
> so prefer the two commands above for this demo.

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

Use **`precise-prefix-router.values.yaml`** (not `optimized-baseline.values.yaml`) so the
EPP runs `precise-prefix-cache-producer` + `token-producer` against the real vLLM KV-events
on ZMQ `:5556`. The chart deploys a `vllm-render` sidecar in the EPP pod for tokenization.

> **Important ordering:** the chart deploys the `vllm-render` sidecar in the EPP pod, which
> needs the vLLM image **and** the `llm-d-hf-token` secret at startup. Load/create both
> **before** installing the chart, otherwise the EPP pod stays at
> `1/2 CreateContainerConfigError` (`secret "llm-d-hf-token" not found`).

```console
gyliu-cary@Mac llm-d % # (a) vLLM image -- kind load fails for this multi-arch manifest list,
gyliu-cary@Mac llm-d %  #     so import it into the node via ctr:
gyliu-cary@Mac llm-d % docker pull --platform linux/arm64 docker.io/vllm/vllm-openai-cpu:v0.19.1
gyliu-cary@Mac llm-d % docker save docker.io/vllm/vllm-openai-cpu:v0.19.1 | \
  docker exec -i llm-d-control-plane ctr -n k8s.io images import -
gyliu-cary@Mac llm-d % # (b) HF token secret (copy .env.example -> .env, set HF_TOKEN)
gyliu-cary@Mac llm-d % cp $DEMO/.env.example $DEMO/.env   # then edit HF_TOKEN
gyliu-cary@Mac llm-d % set -a && source $DEMO/.env && set +a
gyliu-cary@Mac llm-d % kubectl create secret generic llm-d-hf-token -n llm-d \
  --from-literal=HF_TOKEN="$HF_TOKEN" --dry-run=client -o yaml | kubectl apply -f -
gyliu-cary@Mac llm-d % # (c) monitoring CRDs (the chart creates a ServiceMonitor)
gyliu-cary@Mac llm-d % bash $LLMD_REPO/guides/recipes/observability/install-prometheus-grafana.sh --crds-only
gyliu-cary@Mac llm-d % helm install llm-d oci://ghcr.io/llm-d/charts/llm-d-router-gateway-dev \
  -f $LLMD_REPO/guides/recipes/router/base.values.yaml \
  -f $DEMO/manifests/optional/precise-prefix/precise-prefix-router.values.yaml \
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
gyliu-cary@Mac llm-d % kubectl get pod -n llm-d -l llm-d-router-gateway=llm-d-epp \
  -o jsonpath='EPP containers: {.items[0].spec.containers[*].name}{"\n"}'
EPP containers: epp vllm-render
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
The image and the `llm-d-hf-token` secret were already prepared in Step 3.7; here we only
pre-seed the model cache, then create the ServiceAccount and the Deployment.

**(a) Pre-seed the model cache (strongly recommended).** The pod pulls ~1 GB of weights
from HuggingFace on first start. `kind/kind-config.yaml` mounts host `/tmp/llm-d-cache`
into the node at `/root/.cache`, and the model-server manifest mounts that node path as
`HF_HOME`, so a cache you fill once is reused by every pod restart *and* by a re-created
cluster. Fill it from the host, where the download gets the full link bandwidth:

```console
gyliu-cary@Mac llm-d % mkdir -p /tmp/llm-d-cache/huggingface
gyliu-cary@Mac llm-d % docker run --rm -e HF_HOME=/hf -e HF_TOKEN="$HF_TOKEN" \
  -v /tmp/llm-d-cache/huggingface:/hf --entrypoint hf \
  docker.io/vllm/vllm-openai-cpu:v0.19.1 download Qwen/Qwen2.5-0.5B-Instruct
Fetching 10 files: 100%|██████████| 10/10 [22:10<00:00, 133.04s/it]
✓ Downloaded
gyliu-cary@Mac llm-d % du -sh /tmp/llm-d-cache/huggingface
960M	/tmp/llm-d-cache/huggingface
```

**(b) Deploy the model server.**

```console
gyliu-cary@Mac llm-d % # Model-server manifest references serviceAccountName: sa -- create it
gyliu-cary@Mac llm-d %  #     first (the gateway chart with provider.name=none does not):
gyliu-cary@Mac llm-d % kubectl apply -f $LLMD_REPO/guides/recipes/modelserver/common/sa.yaml -n llm-d
gyliu-cary@Mac llm-d % kubectl apply -f $DEMO/manifests/optional/cpu-vllm/model-server.yaml
gyliu-cary@Mac llm-d % kubectl rollout status deploy/precise-prefix-vllm -n llm-d --timeout=600s
deployment "precise-prefix-vllm" successfully rolled out
gyliu-cary@Mac llm-d % kubectl logs -n llm-d deploy/precise-prefix-vllm | grep -E 'Loading weights|startup complete'
(EngineCore pid=75) INFO 08-03 14:02:52 [default_loader.py:384] Loading weights took 1.51 seconds
(APIServer pid=1) INFO:     Application startup complete.
```

With the cache pre-seeded the pod is serving ~35 s after it starts; the `--timeout=600s`
above is then plenty.

> **Skipped the pre-seed and the pod keeps restarting?** This is the failure mode to know
> about. A cold HF download of the weights takes ~50 min on a slow link, and the HF
> downloader **restarts from zero** after every container restart — so if the `startupProbe`
> budget is shorter than the download, the pod loops forever and never converges. The
> manifest therefore sets `failureThreshold: 360` (60 min) *and* a persistent cache mount;
> both matter. Watch progress with
> `kubectl exec -n llm-d deploy/precise-prefix-vllm -c modelserver -- du -sh /root/.cache/huggingface`.

> **Rollout stuck at `0 out of 1 new replicas`?** Check events:
> `kubectl get events -n llm-d | grep precise-prefix`. If you see
> `serviceaccount "sa" not found`, apply `sa.yaml` above, then
> `kubectl rollout restart deploy/precise-prefix-vllm -n llm-d`.

> **Why `strategy: Recreate`?** A second vLLM pod (4 CPU / 6 Gi requested) does not fit
> beside the first one on a single Kind node, so the default rolling update deadlocks with
> the new pod `Pending` and the old one never terminating.

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
gyliu-cary@Mac llm-d % kubectl apply -k $LLMD_REPO/guides/recipes/modelserver/components/monitoring/ -n llm-d
podmonitor.monitoring.coreos.com/decode created
gyliu-cary@Mac llm-d % kubectl get pods -n llm-d-monitoring
NAME                                                     READY   STATUS    RESTARTS   AGE
alertmanager-llmd-kube-prometheus-stack-alertmanager-0   2/2     Running   0          125m
llmd-grafana-5c77cd47b4-nsnnt                            3/3     Running   0          126m
llmd-kube-prometheus-stack-operator-f96fc6d6c-6qpkq      1/1     Running   0          126m
llmd-kube-state-metrics-77cb8dbcf9-j7nbg                 1/1     Running   0          126m
llmd-prometheus-node-exporter-xjqbl                      1/1     Running   0          126m
prometheus-llmd-kube-prometheus-stack-prometheus-0       2/2     Running   0          125m
```

> **`podMonitor/llm-d/decode` missing from the Prometheus targets?** If the `PodMonitor` is
> created in the same moment the operator regenerates the scrape config, it can be left out
> of the generated config and nothing retriggers a sync. Touch it to force a resync:
> `kubectl annotate podmonitor -n llm-d decode resync="$(date +%s)" --overwrite`.
> Confirm with
> `curl -s http://localhost:9091/api/v1/status/config | grep -c 'podMonitor/llm-d/decode'`.

### Final state

```console
gyliu-cary@Mac llm-d % kubectl get pod -A   # kube-system omitted
NAMESPACE             NAME                                                     READY   STATUS    RESTARTS   AGE
agentgateway-system   agentgateway-5448f46756-g7zmb                            1/1     Running   0          144m
llm-d                 jaeger-587f6c758f-rdvp6                                  1/1     Running   0          142m
llm-d                 llm-d-epp-7dc5b7f9f-qdl77                                2/2     Running   0          128m
llm-d                 llm-d-inference-gateway-6bbf846c56-qxjhs                 1/1     Running   0          142m
llm-d                 otel-collector-7fd7c98767-ng6nn                          1/1     Running   0          142m
llm-d                 precise-prefix-vllm-5dfb5c8c89-49s6z                     1/1     Running   0          43m
llm-d-monitoring      alertmanager-llmd-kube-prometheus-stack-alertmanager-0   2/2     Running   0          125m
llm-d-monitoring      llmd-grafana-5c77cd47b4-nsnnt                            3/3     Running   0          126m
llm-d-monitoring      llmd-kube-prometheus-stack-operator-f96fc6d6c-6qpkq      1/1     Running   0          126m
llm-d-monitoring      llmd-kube-state-metrics-77cb8dbcf9-j7nbg                 1/1     Running   0          126m
llm-d-monitoring      llmd-prometheus-node-exporter-xjqbl                      1/1     Running   0          126m
llm-d-monitoring      prometheus-llmd-kube-prometheus-stack-prometheus-0       2/2     Running   0          125m

gyliu-cary@Mac llm-d % helm list -A
NAME                NAMESPACE             CHART                          APP VERSION   STATUS
agentgateway        agentgateway-system   agentgateway-v1.1.0            v1.1.0        deployed
agentgateway-crds   agentgateway-system   agentgateway-crds-v1.1.0       v1.1.0        deployed
llm-d               llm-d                 llm-d-router-gateway-dev-v0    v0            deployed
llmd                llm-d-monitoring      kube-prometheus-stack-88.1.3   v0.93.0       deployed
```

> The EPP pod is `2/2` (`epp` + the `vllm-render` sidecar), and
> `llm-d-router-gateway-dev` only publishes the floating **`v0`** tag — there is no pinned
> release, so the chart content can change under you. This run pulled digest
> `sha256:4da0c96b8ecb4881ee72b29284f9da0b14d52494fd584f68c84f7d906f2eaab1`.

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
```

Confirm the EPP span is no longer an orphan root (it has the gateway as parent):

```console
gyliu-cary@Mac llm-d % curl -s "http://localhost:16686/api/services" | python3 -c "import sys,json;print(sorted(json.load(sys.stdin)['data']))"
['llm-d-inference-gateway', 'llm-d-router/epp']

gyliu-cary@Mac llm-d % curl -s "http://localhost:16686/api/traces?service=llm-d-inference-gateway&limit=1&lookback=1h" | python3 -c "
import sys, json
t = json.load(sys.stdin)['data'][0]
procs = t['processes']
span_by_id = {s['spanID']: s for s in t['spans']}
for s in t['spans']:
    svc = procs[s['processID']]['serviceName']
    refs = [r for r in (s.get('references') or []) if r.get('refType')=='CHILD_OF']
    parent = 'ROOT'
    if refs:
        ps = span_by_id.get(refs[0]['spanID'])
        if ps: parent = procs[ps['processID']]['serviceName']
    print(f'  [{svc}] {s[\"operationName\"]} <- {parent}')
"
  [llm-d-inference-gateway] POST /* <- ROOT
  [llm-d-router/epp] gateway.request <- llm-d-inference-gateway
  [llm-d-router/epp] gateway.request_orchestration <- llm-d-router/epp
  [llm-d-router/epp] HTTP POST <- llm-d-router/epp
  [llm-d-router/epp] produce_precise_prefix_cache <- llm-d-router/epp
  [llm-d-router/epp] llm_d.kv_cache.index <- llm-d-router/epp
  [llm-d-router/epp] run_scheduler_profile <- llm-d-router/epp
  [llm-d-router/epp] filter_endpoints <- llm-d-router/epp
  [llm-d-router/epp] pick_endpoints <- llm-d-router/epp
  [llm-d-router/epp] llm_d.kv_cache.index.add <- llm-d-router/epp
```

A single `/v1/chat/completions` now produces a **10-span** trace across the two services —
the gateway root, the EPP request/orchestration pair, the scheduler subtree
(`run_scheduler_profile` → `filter_endpoints`, `pick_endpoints`), the precise-prefix
producer with its kv-cache index spans, and the `HTTP POST` the `token-producer` makes to
the `vllm-render` sidecar.

### 4.2.1 Drive a prefix-cache hit

The kv-cache spans only carry interesting values once a prompt is at least one block
(64 tokens) long and is repeated. Send the same long prompt ~6 times, then inspect the
attributes:

```console
gyliu-cary@Mac llm-d % PROMPT="Explain in detail how a distributed key-value cache works in a large
language model inference system, covering block-based paging, prefix reuse across requests, eviction
policy, event publication over ZeroMQ, and how a router can use those events to steer traffic to the
replica that already holds the longest matching prefix. Please be thorough and specific."
gyliu-cary@Mac llm-d % kubectl run drive --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d \
  --command -- sh -c 'for i in 1 2 3 4 5 6; do curl -sS -o /dev/null -w "req$i http=%{http_code}\n" \
  -X POST http://'"$GWIP"':80/v1/chat/completions -H "Content-Type: application/json" \
  -d "{\"model\":\"Qwen/Qwen2.5-0.5B-Instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"'"$PROMPT"'\"}],\"max_tokens\":16}"; sleep 3; done'
req1 http=200
...
req6 http=200
gyliu-cary@Mac llm-d % # then the span attributes look like:
llm_d.kv_cache.index            {'llm_d.kv_cache.index.lookup.block_count': 1,
                                 'llm_d.kv_cache.lookup.blocks_found': 1,
                                 'llm_d.kv_cache.lookup.cache_hit': True,
                                 'llm_d.kv_cache.lookup.pod_filter_count': 1}
produce_precise_prefix_cache    {'llm_d.epp.producer.candidate_endpoints': 1,
                                 'llm_d.epp.producer.max_match_blocks': 1,
                                 'llm_d.epp.producer.total_blocks': 1}
pick_endpoints                  {'llm_d.epp.picker.candidate_endpoints': 1,
                                 'llm_d.epp.picker.top_endpoints': '["llm-d/precise-prefix-vllm-...-rank-0"]',
                                 'llm_d.epp.picker.top_scores': '[7]'}
```

`cache_hit: True` with `max_match_blocks: 1` is the real KV-cache-aware routing loop
closing: vLLM published the block over ZMQ, the EPP indexed it, and the next request
matched it. An `llm_d.kv_cache.index.evict` span also appears once blocks age out.

The gateway hop (`llm-d-inference-gateway`) and the EPP are stitched into one trace:

![Jaeger stitched gateway → EPP trace](docs/screenshots/jaeger-stitched-trace.png)

`Services 2 | Depth 5 | Total Spans 10` — one trace, rooted at the gateway.

### 4.3 Verify the metrics scrape loop in Prometheus

```console
gyliu-cary@Mac llm-d % kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9091:9090 &
gyliu-cary@Mac llm-d % # Status → Targets: both UP
gyliu-cary@Mac llm-d % curl -s "http://localhost:9091/api/v1/targets?state=active" | grep -o 'serviceMonitor/llm-d/llm-d-epp-monitor\|podMonitor/llm-d/decode'
serviceMonitor/llm-d/llm-d-epp-monitor
podMonitor/llm-d/decode

gyliu-cary@Mac llm-d % curl -s "http://localhost:9091/api/v1/query?query=llm_d_epp_request_total" | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['result'][0]['value'][1])"
7
gyliu-cary@Mac llm-d % curl -s "http://localhost:9091/api/v1/query?query=llm_d_epp_prefix_indexer_size" | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['result'][0]['value'][1])"
3
gyliu-cary@Mac llm-d % curl -s "http://localhost:9091/api/v1/query?query=vllm:num_requests_running" | python3 -c "import sys,json;print(len(json.load(sys.stdin)['data']['result']),'series')"
1 series
```

The EPP `ServiceMonitor` and the vLLM `PodMonitor` are scraped (targets `up`):

![Prometheus targets up](docs/screenshots/prometheus-targets.png)

### 4.4 View the Grafana dashboards

```console
gyliu-cary@Mac llm-d % kubectl port-forward -n llm-d-monitoring svc/llmd-grafana 3000:80 &
gyliu-cary@Mac llm-d % # open http://localhost:3000  (admin / admin)
gyliu-cary@Mac llm-d % curl -s -u admin:admin "http://localhost:3000/api/search?type=dash-db" | \
  python3 -c "import sys,json;[print('-',d['title']) for d in json.load(sys.stdin) if 'llm-d' in d['title'] or 'Inference' in d['title'] or 'P/D' in d['title']]"
- Inference Gateway
- llm-d Diagnostic Drill-Down
- llm-d Failure & Saturation Indicators
- llm-d Performance Dashboard
- llm-d SGLang Overview
- llm-d vLLM Overview
- P/D Coordinator Metrics
```

The installer now loads **7** llm-d dashboards (Inference Gateway and SGLang Overview were
added upstream).

**llm-d Performance Dashboard** (TTFT, inter-token latency, KV-cache hit rate, request
throughput) — this run reached a **68.9 % KV cache hit rate** after the repeated long
prompts of Step 4.2.1:

![Grafana llm-d Performance dashboard](docs/screenshots/grafana-performance.png)

**llm-d vLLM Overview** (E2E latency, token throughput, scheduler state, cache utilization):

![Grafana llm-d vLLM Overview dashboard](docs/screenshots/grafana-vllm-overview.png)

---

## Observability verification summary

| Item | How verified | Result |
| --- | --- | --- |
| EPP metric rename (`llm_d_router_epp` → `llm_d_epp`, #1661) | `llm_d_epp_request_total` in Prometheus TSDB | ✅ live |
| IPP standardized OTel naming (#164) | Jaeger service `llm-d-inference-payload-processor` | N/A — Gateway mode has no IPP |
| EPP span namespace `llm_d.epp.*` (#1670) | `produce_precise_prefix_cache` + `pick_endpoints` span attrs | ✅ live |
| kv-cache index tracing (#653 / #637) | `llm_d.kv_cache.index{,.add,.evict}` spans with real vLLM KV-events | ✅ live |
| kv-cache **hit** on the routing path | `llm_d.kv_cache.lookup.cache_hit=true`, `max_match_blocks=1` | ✅ live |
| Scheduler subtree spans | `run_scheduler_profile` → `filter_endpoints` / `pick_endpoints` | ✅ live |
| Upstream traceparent adoption (#1514) | gateway → EPP stitched trace (Gateway API mode) | ✅ live |
| Metrics scrape loop | Prometheus targets UP + TSDB + Grafana dashboards | ✅ closed loop |

> Requires `precise-prefix-router.values.yaml` in Step 3.7 (not `optimized-baseline`).
> Without it the vLLM KV-events ZMQ socket is wired but the EPP runs the baseline
> prefix-cache-scorer only — no `llm_d.kv_cache.*` or `produce_precise_prefix_cache` spans.

> The standalone (self-managed Envoy) chart **cannot** stitch the proxy hop to the EPP
> (Envoy injects `traceparent` only at the router, after `ext_proc`; it sends no trace
> context — neither HTTP header nor gRPC metadata — to the EPP). This is why this demo
> uses the Gateway API mode, which is also llm-d's recommended production topology.

---

## Re-run log — 2026-08-03 against `main`

Full clean re-run (fresh Kind cluster, images rebuilt from `upstream/main`). Everything in
this document was re-executed. What changed since the previous run:

| Area | Change |
| --- | --- |
| Upstream install flow | **No breaking changes.** Every path, chart, script and flag in Steps 3.1–3.10 still works verbatim. |
| Model cache | The vLLM pod used to download ~1 GB of weights into an `emptyDir` on every pod re-creation. It now mounts the Kind node cache (`hostPath /root/.cache/huggingface`, backed by host `/tmp/llm-d-cache` from `kind-config.yaml`) and Step 3.8 pre-seeds it — startup drops from ~50 min to ~35 s. |
| Startup probe | Raised to `failureThreshold: 360` (60 min). The HF downloader restarts from zero after each container restart, so a probe budget shorter than the download made the pod loop forever without converging. |
| Deployment strategy | `strategy: Recreate` — a rolling update deadlocks on a single Kind node (two 4 CPU / 6 Gi pods do not fit). |
| Trace shape | A request now yields **10** spans (was 6): `run_scheduler_profile` → `filter_endpoints` / `pick_endpoints`, plus the `token-producer`'s `HTTP POST` and an `llm_d.kv_cache.index.evict`. |
| Jaeger services | `jaeger` no longer self-reports as a service; only `llm-d-inference-gateway` and `llm-d-router/epp` appear. |
| Monitoring stack | `kube-prometheus-stack` 86.1.0 → **88.1.3** (operator v0.93.0); the install now also brings up Alertmanager, kube-state-metrics and node-exporter. 7 llm-d dashboards load. |
| PodMonitor race | `podMonitor/llm-d/decode` can be missing from the generated scrape config if it is created exactly when the operator syncs; annotate it to force a resync (Step 3.10). |
| Gateway CRDs | llm-d now ships `guides/recipes/gateway/install-gateway-crds.sh` (Gateway API v1.5.1 + GAIE v1.5.0) as an alternative to Step 3.3 — but it omits the `llm-d.ai` CRDs the router needs. |
| Chart tag | `llm-d-router-gateway-dev` still publishes only the floating `v0` tag (no pinned release); this run used digest `sha256:4da0c96b…`. |
| Screenshots | All four images under `docs/screenshots/` were re-captured from this run. |
