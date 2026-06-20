# llm-d on Kind —— Gateway API 模式 + 完整可观测性（Tracing + Metrics）

本文记录在 **无 GPU、Apple Silicon（arm64）的 Kind** 上，以 **Gateway API 模式**（agentgateway）
部署 llm-d，并打通完整可观测性闭环：

- **分布式追踪**：把 gateway 这一跳和 EPP 串进**同一条** Jaeger trace。
- **指标**：从 EPP 和 vLLM 模型服务抓取到 Prometheus，并在 Grafana 可视化。

> 为什么用 Gateway API 模式而不是 standalone（自管 Envoy）chart？standalone 的 Envoy 自己当
> trace root，并且**不会把 W3C trace context 传播给它的 `ext_proc` 服务**，所以 EPP 的
> `gateway.request` span 永远是孤立的 root。真正的 Gateway（agentgateway / Istio）会把 trace
> context 传给 EPP 的 `ext_proc`，EPP 再 adopt（PR #1514）——于是 gateway 这一跳和 EPP 落到
> **同一条** trace 里。

---

## 1. 系统架构 / System Architecture

```text
                          ┌──────────────────────── 可观测性 ────────────────────────┐
                          │                                                          │
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

| 组件 | Namespace | 角色 |
| --- | --- | --- |
| `agentgateway`（控制面） | `agentgateway-system` | Gateway API + Inference Extension 控制器；provision 数据面代理，通过 xDS 下发配置 |
| `llm-d-inference-gateway`（数据面） | `llm-d` | 代理本体。trace **root** span `POST /*`；把 W3C `traceparent` 注入到对 EPP 的 `ext_proc` 调用 |
| `llm-d-epp` | `llm-d` | llm-d Router **Endpoint Picker**（Gateway API Inference Extension / `ext_proc`）。发 `gateway.request` + 调度 span，暴露 `llm_d_epp_*` 指标 |
| `precise-prefix-vllm` | `llm-d` | 真实 **vLLM CPU** 模型服务（`Qwen2.5-0.5B-Instruct`）；暴露 `vllm:*` 指标，在 ZMQ `:5556` 发 KV-events |
| `otel-collector` + `jaeger` | `llm-d` | 追踪管道（OTLP gRPC → Jaeger） |
| `kube-prometheus-stack`（`llmd` release） | `llm-d-monitoring` | Prometheus + Grafana + operator；抓取 `ServiceMonitor`/`PodMonitor` |
| `HTTPRoute` / `InferencePool` | `llm-d` | Gateway → InferencePool 连线；InferencePool 把 EPP 作为它的 endpoint-picker 扩展 |

镜像均从各 llm-d 仓库的 **`upstream/main`** 构建（arm64）：

```console
gyliu-cary@Mac llm-d % docker images | grep main
ghcr.io/llm-d/llm-d-router-endpoint-picker-dev    main   40e47a2df975   93.5MB
ghcr.io/llm-d/llm-d-routing-sidecar               main   496cd2e510a0   57.9MB
ghcr.io/llm-d/llm-d-inference-payload-processor   main   a66f2f6a7250   74.2MB
```

---

## 2. Workflow

**请求路径**

1. 客户端 `POST /v1/chat/completions` → `llm-d-inference-gateway`（ClusterIP `:80`）。
2. agentgateway 起 **root span** `POST /*`，注入 W3C `traceparent`，通过 `ext_proc` 调用 EPP。
3. EPP extract 出 `traceparent`（PR #1514），把 `gateway.request` 作为 gateway span 的**子 span** 启动，跑调度（`gateway.request_orchestration`），从 `InferencePool` 选一个 endpoint。
4. agentgateway 把请求代理到选中的 vLLM pod；vLLM 返回结果。

**Trace 路径** —— agentgateway 的 span 和 EPP 的 span 都导出（OTLP gRPC `:4317`）到 `otel-collector` → `jaeger`，共享同一个 trace ID：

```console
gyliu-cary@Mac llm-d % # 一条 trace，两个 service，父子关系
[llm-d-inference-gateway] POST /*
  [llm-d-router/epp] gateway.request
    [llm-d-router/epp] gateway.request_orchestration
```

**Metric 路径** —— `ServiceMonitor`（EPP）和 `PodMonitor`（vLLM）被 Prometheus operator 发现；Prometheus 抓取 EPP 的 `:9090/metrics` 和 vLLM 的 `/metrics`，存入 TSDB，Grafana 渲染 llm-d 看板。

---

## 3. 安装步骤 / Installation Steps

设置共享变量（按你的 checkout 调整）：

```console
gyliu-cary@Mac llm-d % export LLMD_REPO=$HOME/go/src/github.com/llm-d/llm-d
gyliu-cary@Mac llm-d % export ROUTER_REPO=$HOME/go/src/github.com/llm-d/llm-d-router
gyliu-cary@Mac llm-d % export IPP_REPO=$HOME/go/src/github.com/llm-d/llm-d-inference-payload-processor
gyliu-cary@Mac llm-d % export DEMO=$HOME/go/src/github.com/gyliu513/langX101/llm-d/llm-d-full-demo
```

### 3.1 从 `upstream/main` 构建镜像（arm64）

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

> 注意：`llm-d-kv-cache` 是 Go 库（在 router 的 `go.mod` 里 pin 为 `v0.9.0`，等于它的
> `upstream/main`），不是独立镜像——构建 EPP 时就已经包含了它的 observability 修复。

### 3.2 创建 Kind 集群并加载镜像

```console
gyliu-cary@Mac llm-d % kind create cluster --config $DEMO/kind/kind-config.yaml
gyliu-cary@Mac llm-d % kind load docker-image ghcr.io/llm-d/llm-d-router-endpoint-picker-dev:main --name llm-d
gyliu-cary@Mac llm-d % kubectl create namespace llm-d
```

### 3.3 安装 Gateway API + GAIE CRDs

```console
gyliu-cary@Mac llm-d % kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml
gyliu-cary@Mac llm-d % kubectl apply -k "https://github.com/llm-d/llm-d-router/config/crd?ref=v0"
```

### 3.4 安装 agentgateway 控制面

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

### 3.5 部署 Gateway

```console
gyliu-cary@Mac llm-d % kubectl apply -k $LLMD_REPO/guides/recipes/gateway/agentgateway -n llm-d
gyliu-cary@Mac llm-d % kubectl get gateway -n llm-d
NAME                      CLASS          ADDRESS   PROGRAMMED   AGE
llm-d-inference-gateway   agentgateway             True         8s
```

### 3.6 部署 OTel Collector + Jaeger

```console
gyliu-cary@Mac llm-d % bash $LLMD_REPO/guides/recipes/observability/install-otel-collector-jaeger.sh -n llm-d
```

### 3.7 以 Gateway API 模式安装 router（`llm-d-router-gateway-dev`）

`tracing.values.yaml` 打开 EPP span 导出；override 文件把 EPP 镜像设为
`pullPolicy: IfNotPresent`（让 Kind 用本地构建的镜像）并设置模型服务 selector。
chart 还会创建到 Gateway 的 `HTTPRoute`。

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

`$DEMO/helm-values/gw-kind.values.yaml`：

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

### 3.8 部署真实 vLLM CPU 模型服务（arm64）

`vllm/vllm-openai-cpu:v0.19.1` 镜像有 **arm64** 变体（原生，无需模拟）。
服务 `Qwen2.5-0.5B-Instruct`，block-size 64，在 ZMQ `:5556` 发 KV-events。

```console
gyliu-cary@Mac llm-d % docker pull --platform linux/arm64 docker.io/vllm/vllm-openai-cpu:v0.19.1
gyliu-cary@Mac llm-d % kind load docker-image docker.io/vllm/vllm-openai-cpu:v0.19.1 --name llm-d
gyliu-cary@Mac llm-d % kubectl create secret generic llm-d-hf-token -n llm-d --from-literal=HF_TOKEN=<your-hf-token>
gyliu-cary@Mac llm-d % kubectl apply -f $DEMO/manifests/optional/cpu-vllm/model-server.yaml
gyliu-cary@Mac llm-d % kubectl rollout status deploy/precise-prefix-vllm -n llm-d --timeout=300s
```

> **Kind / Docker-on-Mac 的坑：** vLLM CPU 会崩
> `AssertionError: Not enough allowed NUMA nodes ... Allowed NUMA nodes are []`，
> 因为容器里看不到 NUMA 拓扑。修复：在 pod env 里手动绑核
> `VLLM_CPU_OMP_THREADS_BIND="0-3"`。

### 3.9 打开 gateway 的 tracing 导出（AgentgatewayPolicy）

让 agentgateway 把**自己的** span 导出到 `otel-collector`，并且对没有入站
`traceparent` 的请求也新建 root trace（`randomSampling: "true"`）。

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

### 3.10 安装 Prometheus + Grafana

```console
gyliu-cary@Mac llm-d % bash $LLMD_REPO/guides/recipes/observability/install-prometheus-grafana.sh
gyliu-cary@Mac llm-d % kubectl get pods -n llm-d-monitoring
NAME                                                     READY   STATUS    RESTARTS   AGE
llmd-grafana-c855676f5-rrsh6                             3/3     Running   0          75s
llmd-kube-prometheus-stack-operator-cdc8d9876-vjc4v      1/1     Running   0          75s
prometheus-llmd-kube-prometheus-stack-prometheus-0       2/2     Running   0          66s
```

### 最终状态

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

## 4. 测试步骤 / Test Steps

### 4.1 触发一个请求（产生一条连起来的 trace）

```console
gyliu-cary@Mac llm-d % GWIP=$(kubectl get svc llm-d-inference-gateway -n llm-d -o jsonpath='{.spec.clusterIP}')
gyliu-cary@Mac llm-d % kubectl run trig --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
  curl -sS -o /dev/null -w "http=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","messages":[{"role":"user","content":"hi"}],"max_tokens":8}'
http=200
```

### 4.2 在 Jaeger 验证串起来的 trace

```console
gyliu-cary@Mac llm-d % kubectl port-forward -n llm-d svc/jaeger-collector 16686:16686 &
gyliu-cary@Mac llm-d % # 打开 http://localhost:16686 → Service 选 llm-d-inference-gateway → Find Traces
gyliu-cary@Mac llm-d % # trace 里同时有两个 service，gateway → EPP：
[llm-d-inference-gateway] POST /*
  [llm-d-router/epp] gateway.request
    [llm-d-router/epp] gateway.request_orchestration
```

确认 EPP 的 span 不再是孤立 root（它的 parent 是 gateway）：

```console
gyliu-cary@Mac llm-d % curl -s "http://localhost:16686/api/services" | python3 -c "import sys,json;print(sorted(json.load(sys.stdin)['data']))"
['jaeger', 'llm-d-inference-gateway', 'llm-d-router/epp', ...]
```

### 4.3 在 Prometheus 验证 metrics 抓取闭环

```console
gyliu-cary@Mac llm-d % kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9091:9090 &
gyliu-cary@Mac llm-d % # Status → Targets：两个都 UP
gyliu-cary@Mac llm-d % curl -s "http://localhost:9091/api/v1/targets?state=active" | grep -o 'serviceMonitor/llm-d/llm-d-epp-monitor\|podMonitor/llm-d/decode'
serviceMonitor/llm-d/llm-d-epp-monitor
podMonitor/llm-d/decode

gyliu-cary@Mac llm-d % curl -s "http://localhost:9091/api/v1/query?query=llm_d_epp_request_total" | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['result'][0]['value'][1])"
12
gyliu-cary@Mac llm-d % curl -s "http://localhost:9091/api/v1/query?query=vllm:num_requests_running" | python3 -c "import sys,json;print(len(json.load(sys.stdin)['data']['result']),'series')"
1 series
```

### 4.4 查看 Grafana 看板

```console
gyliu-cary@Mac llm-d % kubectl port-forward -n llm-d-monitoring svc/llmd-grafana 3000:80 &
gyliu-cary@Mac llm-d % # 打开 http://localhost:3000  (admin / admin)
gyliu-cary@Mac llm-d % # 看板："llm-d vLLM Overview"、"llm-d Performance Dashboard" ...
```

---

## 可观测性验证总结

| 项 | 验证方式 | 结果 |
| --- | --- | --- |
| EPP 指标改名（`llm_d_router_epp` → `llm_d_epp`，#1661） | Prometheus TSDB 里的 `llm_d_epp_request_total` | ✅ 运行时 |
| IPP 标准化 OTel 命名（#164） | Jaeger service `llm-d-inference-payload-processor` | ✅ 运行时 |
| EPP span 命名空间 `llm_d.epp.*`（#1670） | `produce_precise_prefix_cache` span 属性（precise-prefix 路径） | ✅ 运行时 |
| kv-cache index 追踪（#653 / #637） | 真实 vLLM KV-events 下的 `llm_d.kv_cache.index{,.add}` span | ✅ 运行时 |
| 上游 traceparent adoption（#1514） | gateway → EPP 串起来的 trace（Gateway API 模式） | ✅ 运行时 |
| Metrics 抓取闭环 | Prometheus targets UP + TSDB + Grafana 看板 | ✅ 闭环 |

> standalone（自管 Envoy）chart **无法**把代理这一跳和 EPP 串起来（Envoy 只在 router——
> 即 `ext_proc` 之后——才注入 `traceparent`；它不向 EPP 传任何 trace context，HTTP 头和
> gRPC metadata 里都没有）。这就是本 demo 用 Gateway API 模式的原因，它也是 llm-d 推荐的
> 生产拓扑。
