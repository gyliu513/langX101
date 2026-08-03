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

同一个 Gateway 上跑两条请求路径：普通请求进 **precise-prefix** 池（2 个真实 vLLM 副本），
带 `x-llm-d-pool: pd` 头的请求进 **P/D 分离** 池。两条路径前面都有 payload processor。

```text
                                    ┌──────── 默认路由 ────────▶ InferencePool llm-d
                                    │        (EPP: precise-prefix)      │
                                    │                                   ├──▶ vLLM 副本 1  ┐ KV-events
 client ─HTTP─▶ agentgateway ─ext_proc─▶ IPP ─▶ (route)                 └──▶ vLLM 副本 2  ┘ (ZMQ :5556)
              (Gateway API,          (PreRouting) │                                        │
               trace ROOT)                        └── x-llm-d-pool: pd ─▶ InferencePool llm-d-pd
                                                           (EPP: P/D)          │           │
                                                                               ▼           │
                                                        routing-sidecar ─prefill─▶ pd-prefill
                                                         (在 pd-decode 内) ─decode─▶ pd-decode
   spans ─────────────────────────── OTLP gRPC :4317 ─▶ otel-collector ──▶ Jaeger
   metrics ───────────────── ServiceMonitor / PodMonitor ─▶ Prometheus ──▶ Grafana ◀────────┘
```

| 组件 | Namespace | 角色 |
| --- | --- | --- |
| `agentgateway`（控制面） | `agentgateway-system` | Gateway API + Inference Extension 控制器；provision 数据面代理，通过 xDS 下发配置 |
| `llm-d-inference-gateway`（数据面） | `llm-d` | 代理本体。trace **root** span `POST /*`；把 W3C `traceparent` 注入每一个 `ext_proc` 调用 |
| `payload-processor`（IPP） | `llm-d` | llm-d **Inference Payload Processor**，以 `PreRouting` `ext_proc` 身份挂载。把 body 字段改写成路由 header（`model` → `X-Gateway-Model-Name`）；接住 gateway 的 trace context 并向下游重新注入 |
| `llm-d-epp` | `llm-d` | precise-prefix 池的 **Endpoint Picker**。发 `gateway.request` + 调度 span，暴露 `llm_d_epp_*` 指标 |
| `llm-d-pd-epp` | `llm-d` | **第二个** EPP release，跑 P/D 插件链（`disagg-profile-handler`、prefill/decode filter）。发 `pick_disagg_profile` / `prepare_disaggregation` span |
| `precise-prefix-vllm`（×2） | `llm-d` | 真实 **vLLM CPU** 模型服务（`Qwen2.5-0.5B-Instruct`）；暴露 `vllm:*` 指标，在 ZMQ `:5556` 发 KV-events。**2 副本**才能让前缀 scorer 真正有得选 |
| `pd-prefill` / `pd-decode` | `llm-d` | 基于 `llm-d-inference-sim` 的 P/D 池。`pd-decode` 用 **`llm-d-routing-sidecar`** 原生 sidecar 挡在 sim 前面，驱动远程 prefill 握手 |
| `otel-collector` + `jaeger` | `llm-d` | 追踪管道（OTLP gRPC → Jaeger） |
| `kube-prometheus-stack`（`llmd` release） | `llm-d-monitoring` | Prometheus + Grafana + operator；抓取 `ServiceMonitor`/`PodMonitor` |
| `HTTPRoute` / `InferencePool` | `llm-d` | 一个 Gateway 上两条路由：chart 默认的 `/` → 池 `llm-d`，以及 header 匹配的 → 池 `llm-d-pd` |

镜像均从各 llm-d 仓库的 **`upstream/main`** 构建（arm64）。三个都会用到：EPP 被两个 router
release 使用，payload processor 用于 3.11，routing sidecar 用于 3.12 的 P/D 池：

```console
gyliu-cary@Mac llm-d % docker images | grep main
ghcr.io/llm-d/llm-d-router-endpoint-picker-dev    main   51b24ccadc27   94.4MB
ghcr.io/llm-d/llm-d-routing-sidecar               main   3d43472e4bb9   58.3MB
ghcr.io/llm-d/llm-d-inference-payload-processor   main   9ba6034f43ec   74.4MB
```

> 最近一次验证：`llm-d@4093435f`、`llm-d-router@a86cc45a`、
> `llm-d-inference-payload-processor@cf5d475`（2026-08-03）。

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
      [llm-d-router/epp] HTTP POST                      # token-producer -> vllm-render
      [llm-d-router/epp] produce_precise_prefix_cache
        [llm-d-router/epp] llm_d.kv_cache.index
      [llm-d-router/epp] run_scheduler_profile
        [llm-d-router/epp] filter_endpoints
        [llm-d-router/epp] pick_endpoints
      [llm-d-router/epp] llm_d.kv_cache.index.add
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
  -t ghcr.io/llm-d/llm-d-router-endpoint-picker-dev:main .        # 必需
gyliu-cary@Mac llm-d % docker build --platform linux/arm64 -f Dockerfile.sidecar \
  -t ghcr.io/llm-d/llm-d-routing-sidecar:main .                   # 可选（P/D 路径）
gyliu-cary@Mac llm-d % cd $IPP_REPO && git fetch upstream && git checkout upstream/main
gyliu-cary@Mac llm-d % docker build --platform linux/arm64 -f Dockerfile \
  -t ghcr.io/llm-d/llm-d-inference-payload-processor:main .       # 可选（IPP 路径）
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
gyliu-cary@Mac llm-d % kubectl apply -k "$ROUTER_REPO/config/crd"
# 若无本地 checkout，可用：
# kubectl apply -k "https://github.com/llm-d/llm-d-router/config/crd?ref=v0.9.0"
```

> `llm-d-router` 仓库没有 git ref `v0` — 请用本地 checkout 或 `ref=v0.9.0`（及更新的 release tag）。

> llm-d 现在也提供了一个把两套 CRD 版本都 pin 住的安装脚本
> （`bash $LLMD_REPO/guides/recipes/gateway/install-gateway-crds.sh`，Gateway API `v1.5.1`
> + GAIE `v1.5.0`）。但它**不会**安装 router `config/crd` 里的 `llm-d.ai` CRD
> （`InferenceObjective`、`InferenceModelRewrite`），所以本 demo 仍建议用上面两条命令。

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

请使用 **`precise-prefix-router.values.yaml`**（不要用 `optimized-baseline.values.yaml`），
让 EPP 运行 `precise-prefix-cache-producer` + `token-producer`，对接 vLLM 在 ZMQ `:5556`
上的 KV-events。chart 会在 EPP Pod 里部署 `vllm-render` sidecar 做分词。

> **顺序很重要：** chart 会在 EPP Pod 里部署 `vllm-render` sidecar，它在启动时**就**需要
> vLLM 镜像**和** `llm-d-hf-token` secret。务必在装 chart **之前**把两者准备好，否则 EPP Pod
> 会卡在 `1/2 CreateContainerConfigError`（`secret "llm-d-hf-token" not found`）。

```console
gyliu-cary@Mac llm-d % # (a) vLLM 镜像 —— kind load 对这个多架构 manifest list 会失败，
gyliu-cary@Mac llm-d %  #     改用 ctr 导入到节点：
gyliu-cary@Mac llm-d % docker pull --platform linux/arm64 docker.io/vllm/vllm-openai-cpu:v0.19.1
gyliu-cary@Mac llm-d % docker save docker.io/vllm/vllm-openai-cpu:v0.19.1 | \
  docker exec -i llm-d-control-plane ctr -n k8s.io images import -
gyliu-cary@Mac llm-d % # (b) HF token secret（先 cp .env.example -> .env 并填好 HF_TOKEN）
gyliu-cary@Mac llm-d % cp $DEMO/.env.example $DEMO/.env   # 编辑 HF_TOKEN
gyliu-cary@Mac llm-d % set -a && source $DEMO/.env && set +a
gyliu-cary@Mac llm-d % kubectl create secret generic llm-d-hf-token -n llm-d \
  --from-literal=HF_TOKEN="$HF_TOKEN" --dry-run=client -o yaml | kubectl apply -f -
gyliu-cary@Mac llm-d % # (c) monitoring CRDs（chart 会创建 ServiceMonitor）
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
镜像和 `llm-d-hf-token` secret 已在 3.7 准备好；这里先预热模型缓存，
再建 ServiceAccount 和 Deployment。

**(a) 预热模型缓存（强烈建议）。** Pod 首次启动要从 HuggingFace 拉 ~1 GB 权重。
`kind/kind-config.yaml` 把宿主机 `/tmp/llm-d-cache` 挂到节点的 `/root/.cache`，
model-server manifest 又把这个节点路径挂成 `HF_HOME`，所以缓存只需灌一次，
之后**所有** pod 重启、甚至重建集群都能复用。在宿主机上灌（能吃满带宽）：

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

**(b) 部署模型服务。**

```console
gyliu-cary@Mac llm-d % # model-server.yaml 引用 serviceAccountName: sa —— 需先创建
gyliu-cary@Mac llm-d %  #     （provider.name=none 时 chart 不会创建）：
gyliu-cary@Mac llm-d % kubectl apply -f $LLMD_REPO/guides/recipes/modelserver/common/sa.yaml -n llm-d
gyliu-cary@Mac llm-d % kubectl apply -f $DEMO/manifests/optional/cpu-vllm/model-server.yaml
gyliu-cary@Mac llm-d % kubectl rollout status deploy/precise-prefix-vllm -n llm-d --timeout=600s
deployment "precise-prefix-vllm" successfully rolled out
gyliu-cary@Mac llm-d % kubectl logs -n llm-d deploy/precise-prefix-vllm | grep -E 'Loading weights|startup complete'
(EngineCore pid=75) INFO 08-03 14:02:52 [default_loader.py:384] Loading weights took 1.51 seconds
(APIServer pid=1) INFO:     Application startup complete.
```

缓存预热后，Pod 启动 ~35 秒即可对外服务，上面的 `--timeout=600s` 完全够用。

> **没做预热、Pod 反复重启？** 这是最需要知道的坑。冷启动在慢网下拉权重要 ~50 分钟，
> 而 HF 下载器在容器每次重启后都会**从 0 重新下载** —— 只要 `startupProbe` 的预算
> 比下载时间短，Pod 就会永远循环、永远收敛不了。所以 manifest 同时设了
> `failureThreshold: 360`（60 分钟）**和**持久化缓存挂载，两者缺一不可。查看进度：
> `kubectl exec -n llm-d deploy/precise-prefix-vllm -c modelserver -- du -sh /root/.cache/huggingface`。

> **Rollout 一直卡在 `0 out of 1 new replicas`？** 看事件：
> `kubectl get events -n llm-d | grep precise-prefix`。若是
> `serviceaccount "sa" not found`，先 apply `sa.yaml`，再执行
> `kubectl rollout restart deploy/precise-prefix-vllm -n llm-d`。

> **为什么用 `strategy: Recreate`？** 单个 Kind 节点放不下第二个 vLLM Pod
> （每个 request 4 CPU / 6 Gi），默认滚动升级会死锁：新 Pod 一直 `Pending`，
> 旧 Pod 一直不退出。

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

> **Prometheus targets 里看不到 `podMonitor/llm-d/decode`？** 如果 `PodMonitor` 正好在
> operator 重新生成 scrape config 的那一刻创建，它可能没被写进生成的配置，而且之后不会有
> 事件再触发同步。改个注解强制重新同步即可：
> `kubectl annotate podmonitor -n llm-d decode resync="$(date +%s)" --overwrite`。
> 验证：
> `curl -s http://localhost:9091/api/v1/status/config | grep -c 'podMonitor/llm-d/decode'`。

### 3.11 把 Inference Payload Processor（IPP）加进 trace

IPP 是第二个 `ext_proc` server。在 Gateway API 模式下要用 `AgentgatewayPolicy` 挂载 ——
它自己的 chart 只有 `provider.name: istio | gke | none` 三种模板，没有 agentgateway 的。

它**天然就会**串进 trace：`pkg/handlers/server.go` 用
`extractTraceContext(ctx, v.RequestHeaders)`（对 `ext_proc` 请求头做 W3C propagator
`Extract`）来起 span，`request.go` 又把 context `Inject` 回它转发的 header。
所以让它跑在 `PreRouting`，**EPP 就会成为 IPP 的子 span**。

```console
gyliu-cary@Mac llm-d % kind load docker-image ghcr.io/llm-d/llm-d-inference-payload-processor:main --name llm-d
gyliu-cary@Mac llm-d % helm install ipp $IPP_REPO/config/charts/payload-processor -n llm-d \
  --set provider.name=none \
  --set payloadProcessor.image.tag=main \
  --set payloadProcessor.image.pullPolicy=IfNotPresent \
  --set payloadProcessor.tracing.enabled=true \
  --set payloadProcessor.tracing.otelExporterEndpoint=http://otel-collector:4317 \
  --set payloadProcessor.tracing.sampling.samplerArg=1.0 \
  --set payloadProcessor.flags.secure-serving=false
```

> **`--secure-serving=false` 是必须的。** IPP 默认 `SecureServing: true`
> （`pkg/server/options.go`），用自签证书跑 gRPC，而 agentgateway 的 `extProc`
> backendRef 走明文 h2。不关掉的话每个请求都 500，gateway 日志报
> `failed to initialize endpoint picker: ... connection reset ... failure_mode=FailClosed`
> —— 注意 `ext_proc` 一坏是**所有**流量都挂，不只是 IPP 这一跳。
> （chart 的 Istio 路径是另一种解法：用 `DestinationRule` 配
> `tls.mode: SIMPLE, insecureSkipVerify: true` 包一层。）

```console
gyliu-cary@Mac llm-d % kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: ipp-extproc
  namespace: llm-d
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: llm-d-inference-gateway
  traffic:
    phase: PreRouting
    extProc:
      backendRef:
        kind: Service
        name: payload-processor
        port: 9004
EOF
gyliu-cary@Mac llm-d % kubectl get agentgatewaypolicy -n llm-d ipp-extproc \
  -o jsonpath='{.status.ancestors[0].conditions[*].reason}{"\n"}'
Valid Attached
```

### 3.12 加上 P/D 分离池

**CPU vLLM 做不了 P/D。** prefill→decode 的 KV 传输需要 connector（NIXL），而
`docker.io/vllm/vllm-openai-cpu:v0.19.1` 里没有 `nixl` 模块
（`python3 -c "import nixl"` → `ModuleNotFoundError`），上游也只为
`gpu` / `xpu` / `tpu` 提供 P/D 模型服务变体。所以 P/D 池跑在
`llm-d-inference-sim` 上，由它 fake 握手 —— **调度和代理组件都是真的**，只有 KV 传输是模拟的。

因为一个 EPP 只能跑一份插件配置，P/D 需要**自己的 router release**，和 precise-prefix
那个并存。chart 会按 release 名给所有资源加前缀（`llm-d-pd-epp`、InferencePool
`llm-d-pd`），互不冲突。

```console
gyliu-cary@Mac llm-d % kind load docker-image ghcr.io/llm-d/llm-d-routing-sidecar:main --name llm-d
gyliu-cary@Mac llm-d % kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.10.2-arm64 --name llm-d
gyliu-cary@Mac llm-d % helm install llm-d-pd oci://ghcr.io/llm-d/charts/llm-d-router-gateway-dev --version v0 \
  -f $LLMD_REPO/guides/recipes/router/base.values.yaml \
  -f $DEMO/manifests/optional/pd/pd-router.values.yaml \
  -f $LLMD_REPO/guides/recipes/router/features/monitoring.values.yaml \
  -f $DEMO/helm-values/tracing.values.yaml \
  -f $DEMO/helm-values/gw-kind-pd.values.yaml \
  --set provider.name=none --set httpRoute.create=false -n llm-d
gyliu-cary@Mac llm-d % kubectl apply -f $DEMO/manifests/optional/pd/model-servers-pd.yaml
gyliu-cary@Mac llm-d % kubectl apply -f $DEMO/manifests/optional/pd/httproute-pd.yaml
gyliu-cary@Mac llm-d % kubectl get inferencepool -n llm-d
NAME       AGE
llm-d      3h15m
llm-d-pd   30s
```

`httproute-pd.yaml` 用 header 匹配，让两个池共用一个 Gateway —— 带 header 匹配的
rule 比 chart 那条光秃秃的 `/` PathPrefix 更具体，所以打了标的请求走 P/D 池，
其余请求照旧进 precise-prefix 池：

```yaml
  rules:
    - matches:
        - path: { type: PathPrefix, value: / }
          headers:
            - { type: Exact, name: x-llm-d-pool, value: pd }
      backendRefs:
        - { group: inference.networking.k8s.io, kind: InferencePool, name: llm-d-pd, weight: 1 }
```

> **routing-sidecar 在 `main` 上改了参数名。** `--connector` 改成了
> **`--kv-connector`**（不改就 unknown flag 崩溃重启），`--vllm-port` 被废弃、
> 改用 **`--model-server-port`**。`main` 还新增了 **`--tracing`** —— 正是它让
> sidecar 的 `prefill` / `decode` 两条腿进入 trace，记得连同常规 `OTEL_*` 环境变量一起设。

### 最终状态

```console
gyliu-cary@Mac llm-d % kubectl get pod -A   # 省略 kube-system
NAMESPACE             NAME                                                     READY   STATUS    RESTARTS   AGE
agentgateway-system   agentgateway-5448f46756-g7zmb                            1/1     Running   0          3h51m
llm-d                 jaeger-587f6c758f-rdvp6                                  1/1     Running   0          3h49m
llm-d                 llm-d-epp-64b9497cd9-5mdzs                               2/2     Running   0          24m
llm-d                 llm-d-inference-gateway-6bbf846c56-qxjhs                 1/1     Running   0          3h49m
llm-d                 llm-d-pd-epp-59d77ccd8-94tbv                             1/1     Running   0          20m
llm-d                 otel-collector-7fd7c98767-ng6nn                          1/1     Running   0          3h49m
llm-d                 payload-processor-576ffd57bf-vp77g                       1/1     Running   0          41m
llm-d                 pd-decode-5bb64c487f-rhh9s                               2/2     Running   0          6m52s
llm-d                 pd-prefill-58c7555d5f-g5q5m                              1/1     Running   0          19m
llm-d                 precise-prefix-vllm-5bdc47b459-8t7jm                     1/1     Running   0          38m
llm-d                 precise-prefix-vllm-5bdc47b459-cjkfm                     1/1     Running   0          38m
llm-d-monitoring      alertmanager-llmd-kube-prometheus-stack-alertmanager-0   2/2     Running   0          3h32m
llm-d-monitoring      llmd-grafana-5c77cd47b4-99hgz                            3/3     Running   0          63m
llm-d-monitoring      llmd-kube-prometheus-stack-operator-f96fc6d6c-6qpkq      1/1     Running   0          3h33m
llm-d-monitoring      llmd-kube-state-metrics-77cb8dbcf9-j7nbg                 1/1     Running   0          3h33m
llm-d-monitoring      llmd-prometheus-node-exporter-xjqbl                      1/1     Running   0          3h33m
llm-d-monitoring      prometheus-llmd-kube-prometheus-stack-prometheus-0       2/2     Running   0          3h32m

gyliu-cary@Mac llm-d % helm list -A
NAME                NAMESPACE             CHART                          APP VERSION   STATUS
agentgateway        agentgateway-system   agentgateway-v1.1.0            v1.1.0        deployed
agentgateway-crds   agentgateway-system   agentgateway-crds-v1.1.0       v1.1.0        deployed
ipp                 llm-d                 payload-processor-0.2.0        v0.2.0        deployed
llm-d               llm-d                 llm-d-router-gateway-dev-v0    v0            deployed
llm-d-pd            llm-d                 llm-d-router-gateway-dev-v0    v0            deployed
llmd                llm-d-monitoring      kube-prometheus-stack-88.1.3   v0.93.0       deployed

gyliu-cary@Mac llm-d % kubectl describe node llm-d-control-plane | grep -A4 'Allocated resources'
Allocated resources:
  Resource           Requests        Limits
  cpu                7500m (53%)     20100m (143%)
  memory             18538Mi (79%)   33414Mi (143%)
```

> 上面这些能塞进**一个 14-CPU / 23Gi 的 Kind 节点**，靠的是砍掉两处 chart 默认值：
> EPP 的 `vllm-render` sidecar（`router.tokenizer.resources`，默认 4 CPU/8Gi —— 见
> `gw-kind.values.yaml`）和模型服务本身（每副本 2 CPU/5Gi）。不砍 tokenizer 那个默认值，
> 第二个 vLLM 副本永远调度不上去（`0/1 nodes are available: 1 Insufficient memory`）。

> precise-prefix 的 EPP Pod 是 `2/2`（`epp` + `vllm-render` sidecar），P/D 的 EPP 是
> `1/1`（它的插件链没有 `token-producer`，所以没 sidecar）；`llm-d-router-gateway-dev`
> 目前只发布浮动的 **`v0`** tag（没有固定 release），chart 内容可能在你不知情时变化。
> 本次拉到的 digest 是
> `sha256:4da0c96b8ecb4881ee72b29284f9da0b14d52494fd584f68c84f7d906f2eaab1`。

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
```

确认 EPP 的 span 不再是孤立 root（它的 parent 是 gateway）：

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
  [inference.llm-d.ai/inference-payload-processor] gateway.request <- llm-d-inference-gateway
  [llm-d-router/epp] gateway.request <- inference.llm-d.ai/inference-payload-processor
  [llm-d-router/epp] gateway.request_orchestration <- llm-d-router/epp
  [llm-d-router/epp] HTTP POST <- llm-d-router/epp
  [llm-d-router/epp] produce_precise_prefix_cache <- llm-d-router/epp
  [llm-d-router/epp] llm_d.kv_cache.index <- llm-d-router/epp
  [llm-d-router/epp] run_scheduler_profile <- llm-d-router/epp
  [llm-d-router/epp] filter_endpoints <- llm-d-router/epp
  [llm-d-router/epp] pick_endpoints <- llm-d-router/epp
  [llm-d-router/epp] llm_d.kv_cache.index.add <- llm-d-router/epp
```

一次 `/v1/chat/completions` 产生跨 **3 个 service 的 11 个 span**：gateway root、
IPP 这一跳、EPP 的 request/orchestration、scheduler 子树（`run_scheduler_profile` →
`filter_endpoints`、`pick_endpoints`）、precise-prefix producer 及其 kv-cache index span，
以及 `token-producer` 调 `vllm-render` sidecar 的那个 `HTTP POST`。

注意父子关系：因为 IPP 跑在 `PreRouting` 并把 trace context 重新注入它转发的 header，
**EPP 的 parent 是 IPP**，不是 gateway。

> `llm-d-kv-cache` 永远不会作为独立的 Jaeger service 出现 —— 它是编译进 EPP 的 Go 库
> （router `go.mod` 里 pin 的 `v0.9.0`），而 OTel 的 service name 是**进程级** resource
> 属性。它的 span 就是上面那些 `llm_d.kv_cache.*`。

### 4.2.1 打出一次 prefix-cache 命中

kv-cache 相关 span 只有在 prompt 至少一个 block（64 token）长、并且被重复发送时才有意义。
把同一条长 prompt 连发 ~6 次，然后看属性：

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
gyliu-cary@Mac llm-d % # 此时 span 属性大致如下：
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

`cache_hit: True` + `max_match_blocks: 1` 就是 KV-cache 感知路由闭环真正跑通了：
vLLM 通过 ZMQ 发出 block，EPP 建好索引，下一个请求命中它。
block 老化后还会出现 `llm_d.kv_cache.index.evict` span。

**有了 2 个副本，路由决策本身才看得见。** 连发同样的长 prompt，`pick_endpoints` 的变化：

```console
gyliu-cary@Mac llm-d % # llm_d.epp.picker.{candidate_endpoints,top_endpoints,top_scores}
cand=1  top=...vllm-5dfb5c8c89-49s6z-rank-0  scores=[4]      # 单副本：无从选择
cand=2  top=...vllm-5bdc47b459-cjkfm-rank-0  scores=[4,4]    # 两副本都冷，打平
cand=2  top=...vllm-5bdc47b459-8t7jm-rank-0  scores=[7,4]    # 前缀落在 8t7jm 上
cand=2  top=...vllm-5bdc47b459-8t7jm-rank-0  scores=[7,4]    # 之后请求全部粘住它
```

7 = 命中时的 `prefix-cache-scorer`（权重 3.0） + `kv-cache-utilization-scorer`（2.0） +
`queue-scorer`（2.0）；没有前缀的那个副本是 4 分。这就是跑 **2 副本**的全部意义 ——
只有一个 endpoint 时 scorer 根本没东西可排序。

gateway、IPP 和 EPP 串进了同一条 trace：

![Jaeger 中 gateway → IPP → EPP 串联的 trace](docs/screenshots/jaeger-stitched-trace.png)

`Services 3 | Depth 6 | Total Spans 11` —— 一条 trace，root 在 gateway。

### 4.2.2 验证 P/D 分离的 trace

给请求打上 `x-llm-d-pool: pd` 走第二条路由：

```console
gyliu-cary@Mac llm-d % kubectl run tpd --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
  curl -sS -o /dev/null -w "pd http=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
  -H 'Content-Type: application/json' -H 'x-llm-d-pool: pd' \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","messages":[{"role":"user","content":"hello pd"}],"max_tokens":16}'
pd http=200
```

这**一个**请求产生跨 **4 个 service 的 21 个 span**：

```console
[llm-d-inference-gateway] POST /*
  [inference.llm-d.ai/inference-payload-processor] gateway.request
    [llm-d-router/epp] gateway.request
      [llm-d-router/epp] gateway.request_orchestration
        [llm-d-router/epp] pick_disagg_profile            # prefill profile
        [llm-d-router/epp] run_scheduler_profile
          [llm-d-router/epp] filter_endpoints
          [llm-d-router/epp] pick_endpoints
        [llm-d-router/epp] pick_disagg_profile            # decode profile
        [llm-d-router/epp] run_scheduler_profile
          [llm-d-router/epp] filter_endpoints
          [llm-d-router/epp] pick_endpoints
        [llm-d-router/epp] pick_disagg_profile
        [llm-d-router/epp] prepare_disaggregation
        [llm-d-router/epp] prepare_disaggregation
    [llm-d-routing-sidecar] llm_d.pd_proxy.POST /v1/chat/completions
      [llm-d-routing-sidecar] forward_request
        [llm-d-routing-sidecar] prefill
          [llm-d-routing-sidecar] HTTP POST               # -> pd-prefill
          [llm-d-routing-sidecar] decode
            [llm-d-routing-sidecar] HTTP POST             # -> pd-decode
```

![Jaeger 中 P/D 分离的 trace](docs/screenshots/jaeger-pd-trace.png)

`Services 4 | Depth 7 | Total Spans 21`。有两点值得从图里读出来：

- EPP 跑的是 **disagg profile handler**：`pick_disagg_profile` 每个 profile 触发一次，
  各自带出一棵 `run_scheduler_profile` → `filter_endpoints` / `pick_endpoints` 子树，
  所以能看到 prefill 和 decode 的 endpoint 是**分别**选出来的，最后由
  `prepare_disaggregation` 把两条腿缝在一起。
- **routing sidecar** 贡献了自己的 service 和真正的两段代理（`prefill` → `decode`），
  这只有在 `main` 新增 `--tracing` 之后才看得到。

> KV 传输本身是模拟的（`llm-d-inference-sim`）；调度、header 处理、代理都是真实组件。
> CPU vLLM 为什么做不了真的，见 3.12。

### 4.3 在 Prometheus 验证 metrics 抓取闭环

```console
gyliu-cary@Mac llm-d % kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9091:9090 &
gyliu-cary@Mac llm-d % # Status → Targets：两个都 UP
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

EPP 的 `ServiceMonitor` 和 vLLM 的 `PodMonitor` 都被抓取（targets `up`）：

![Prometheus targets up](docs/screenshots/prometheus-targets.png)

### 4.4 查看 Grafana 看板

```console
gyliu-cary@Mac llm-d % kubectl port-forward -n llm-d-monitoring svc/llmd-grafana 3000:80 &
gyliu-cary@Mac llm-d % # 打开 http://localhost:3000  (admin / admin)
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

安装脚本现在会加载 **7** 个 llm-d 看板（上游新增了 Inference Gateway 和 SGLang Overview）。

**llm-d Performance Dashboard**（TTFT、inter-token 延迟、KV-cache 命中率、请求吞吐）——
本次跑完 4.2.1 的重复长 prompt 后，KV cache 命中率到了 **68.9 %**：

![Grafana llm-d Performance 看板](docs/screenshots/grafana-performance.png)

**llm-d vLLM Overview**（E2E 延迟、token 吞吐、scheduler 状态、cache 利用率）：

![Grafana llm-d vLLM Overview 看板](docs/screenshots/grafana-vllm-overview.png)

---

## 可观测性验证总结

| 项 | 验证方式 | 结果 |
| --- | --- | --- |
| EPP 指标改名（`llm_d_router_epp` → `llm_d_epp`，#1661） | Prometheus TSDB 里的 `llm_d_epp_request_total` | ✅ 运行时 |
| IPP 标准化 OTel 命名（#164） | Jaeger service `inference.llm-d.ai/inference-payload-processor` | ✅ 运行时（3.11） |
| IPP 接住 trace context | EPP 的 span 是 **IPP 的子 span** | ✅ 运行时 |
| EPP span 命名空间 `llm_d.epp.*`（#1670） | `produce_precise_prefix_cache` + `pick_endpoints` span 属性 | ✅ 运行时 |
| kv-cache index 追踪（#653 / #637） | 真实 vLLM KV-events 下的 `llm_d.kv_cache.index{,.add,.evict}` span | ✅ 运行时 |
| 路由路径上的 kv-cache **命中** | `llm_d.kv_cache.lookup.cache_hit=true`、`max_match_blocks=1` | ✅ 运行时 |
| KV 感知的**路由决策**（2 副本） | `pick_endpoints` `top_scores=[7,4]`，稳定粘住持有前缀的副本 | ✅ 运行时 |
| Scheduler 子树 span | `run_scheduler_profile` → `filter_endpoints` / `pick_endpoints` | ✅ 运行时 |
| P/D 分离调度 | `pick_disagg_profile` ×3 + `prepare_disaggregation` ×2，两个 scheduler profile | ✅ 运行时（sim） |
| routing-sidecar 追踪（`--tracing`，#1667） | `llm_d.pd_proxy.*` → `forward_request` → `prefill` → `decode` | ✅ 运行时（sim） |
| 上游 traceparent adoption（#1514） | gateway → IPP → EPP → sidecar 串起来的 trace | ✅ 运行时 |
| Metrics 抓取闭环 | Prometheus targets UP + TSDB + Grafana 看板 | ✅ 闭环 |

> 步骤 3.7 必须使用 `precise-prefix-router.values.yaml`（不能用 `optimized-baseline`）。
> 否则 vLLM 的 KV-events ZMQ 虽已接通，EPP 仍只跑 baseline 的 prefix-cache-scorer，
> Jaeger 里不会出现 `llm_d.kv_cache.*` 或 `produce_precise_prefix_cache` span。

> standalone（自管 Envoy）chart **无法**把代理这一跳和 EPP 串起来（Envoy 只在 router——
> 即 `ext_proc` 之后——才注入 `traceparent`；它不向 EPP 传任何 trace context，HTTP 头和
> gRPC metadata 里都没有）。这就是本 demo 用 Gateway API 模式的原因，它也是 llm-d 推荐的
> 生产拓扑。

---

## 重跑记录 —— 2026-08-03，对齐 `main`

在全新 Kind 集群上完整重跑了一遍（镜像全部从 `upstream/main` 重新构建），
本文档里的每一步都重新执行过。相比上一次运行的变化：

| 方面 | 变化 |
| --- | --- |
| 上游安装流程 | **没有 breaking change。** 3.1–3.10 里的所有路径、chart、脚本、参数都能原样跑通。 |
| 模型缓存 | 以前 vLLM Pod 每次重建都要把 ~1 GB 权重下到 `emptyDir`。现在改挂 Kind 节点缓存（`hostPath /root/.cache/huggingface`，由 `kind-config.yaml` 里的宿主机 `/tmp/llm-d-cache` 支撑），并在 3.8 里预热 —— 启动从 ~50 分钟降到 ~35 秒。 |
| Startup probe | 提到 `failureThreshold: 360`（60 分钟）。HF 下载器在容器每次重启后都从 0 重来，所以只要探针预算短于下载时间，Pod 就会永远循环、收敛不了。 |
| 部署策略 | 改成 `strategy: Recreate` —— 单 Kind 节点放不下两个 4 CPU / 6 Gi 的 Pod，默认滚动升级会死锁。 |
| Trace 形状 | 一次请求现在是 **10** 个 span（原来 6 个）：新增 `run_scheduler_profile` → `filter_endpoints` / `pick_endpoints`，外加 `token-producer` 的 `HTTP POST` 和 `llm_d.kv_cache.index.evict`。 |
| Jaeger service 列表 | `jaeger` 自己不再上报为一个 service，只剩 `llm-d-inference-gateway` 和 `llm-d-router/epp`。 |
| 监控栈 | `kube-prometheus-stack` 86.1.0 → **88.1.3**（operator v0.93.0）；安装时还会拉起 Alertmanager、kube-state-metrics、node-exporter。7 个 llm-d 看板全部加载。 |
| PodMonitor 竞态 | 如果 `PodMonitor` 正好在 operator 同步的那一刻创建，可能不会进入生成的 scrape config；改注解强制重新同步（见 3.10）。 |
| Gateway CRDs | llm-d 新增了 `guides/recipes/gateway/install-gateway-crds.sh`（Gateway API v1.5.1 + GAIE v1.5.0），可作为 3.3 的替代 —— 但它不含 router 需要的 `llm-d.ai` CRD。 |
| Chart tag | `llm-d-router-gateway-dev` 依然只有浮动的 `v0` tag（没有固定 release）；本次用的 digest 是 `sha256:4da0c96b…`。 |
| 截图 | `docs/screenshots/` 下所有图全部按本次运行重新截取。 |

### 本轮新增的组件

| 新增 | 目的 / 收益 |
| --- | --- |
| **IPP**（3.11） | trace 里多出第三个 service。需要 `--secure-serving=false` 和一条 `AgentgatewayPolicy` 的 `traffic.extProc` —— 它自己的 chart 没有 agentgateway 模板。 |
| **模型服务 2 副本** | 让前缀 scorer 从走过场变成看得见的决策（`top_scores=[7,4]`）。前提是砍掉 `router.tokenizer.resources`（默认 4 CPU/8Gi）和模型服务的 request，否则第二个副本调度不上去。 |
| **P/D 池**（3.12） | 第四个 service，也是整个 demo 里最丰富的一条 trace（21 span）：disagg profile 调度 + sidecar 的 prefill/decode 两条腿。跑在 `llm-d-inference-sim` 上，因为 CPU vLLM 没有 NIXL。 |
| 第二个 router release `llm-d-pd` | 一个 EPP 只能跑一份插件配置，所以 P/D 需要自己的 release；chart 按 release 名加前缀，两个池通过 header 匹配的 `HTTPRoute` 共用一个 Gateway。 |
