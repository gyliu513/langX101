# llm-d on Kind —— 真实 DGX Spark GPU 推理 + 完整可观测性

*[English](README.md)*

本文档记录了一次 **Kind + 真实 GPU** 的 llm-d 部署：本地 Kind 集群(Gateway API /
agentgateway 模式)运行 llm-d 的全部路由与可观测性组件,通过局域网桥接到
**NVIDIA DGX Spark GPU 节点**(`192.168.1.112`)上的**真实 vLLM 推理**。它是
[`../llm-d-full-demo`](../llm-d-full-demo)(因为构建机没有 GPU,使用的是 CPU vLLM /
模拟器)的延伸,增加了:

- 在 precise-prefix(KV-cache 感知路由)路径上的**真实 GPU 推理**。
- 同样闭环的可观测性:跨 gateway → IPP → EPP → model server 的分布式追踪
  (Jaeger)与指标(Prometheus/Grafana)。
- P/D 分离(调度是真实的,KV 传输是模拟的 —— 只有一块物理 GPU)。
- Workload Variant Autoscaler(WVA)基于实时 Prometheus 指标驱动 HPA。

下面所有内容都是 2026-08-24 一次真实运行**实际抓取到的输出**,不是示意性样例。

---

## 1. 为什么用一个 proxy Pod、而不是 Service 把 GPU 节点接进来

Kind 无法把一台远程物理主机当作真正的 Kubernetes 节点加入集群 —— Kind 节点本质上是
*同一台* Docker 主机上的 Docker 容器。所以 GPU 只能作为一个独立进程留在集群外面(跑在
DGX Spark 上),集群内部需要有什么东西来代表它,参与 llm-d 的路由。

llm-d 的 `InferencePool` 是通过 **Pod label** 选择后端的
(`router.modelServers.matchLabels` 会变成 `InferencePool.spec.selector`),EPP
是通过 **Kubernetes Pod API** 来解析这个 selector 的 —— 它直接拨号 Pod IP,从不经过
Service 的 VIP。所以一个指向外部 IP 的 Service,对 InferencePool 的 selector 来说是
不可见的。

解决办法:造一个真实的、就在集群里的 Pod,让它**本身就是** InferencePool 的后端,它的
容器负责把 TCP 流量透明地隧道转发到 DGX Spark:

```text
DGX Spark (192.168.1.112,GPU,普通 docker,不属于 Kind 集群)
  vllm-gpu-0  nvcr.io/nvidia/vllm:26.05-py3
              vllm serve Qwen/Qwen2.5-1.5B-Instruct --port 8000
              --kv-events-config zmq :5556   (真实 GPU 推理 + 真实 KV 事件)

Kind 集群 "llm-d-gpu"(Mac,Docker Desktop)
  namespace agentgateway-system: agentgateway 控制面
  namespace llm-d:
    llm-d-inference-gateway (agentgateway 数据面)          <- trace 根节点
    payload-processor (IPP)                                 ext_proc PreRouting
    llm-d-epp           (precise-prefix EPP,InferencePool "llm-d")
       gpu-vllm-proxy   <-- socat 桥接 Pod,就是 InferencePool "llm-d" 的后端
                            Pod:8000 -> DGX:8000 (HTTP)
                            Pod:5556 -> DGX:5556 (ZMQ KV-cache 事件)
    llm-d-pd-epp         (P/D EPP,InferencePool "llm-d-pd")
       pd-prefill / pd-decode (llm-d-inference-sim + routing-sidecar,KV 传输为模拟)
    llm-d-baseline-epp   (optimized-baseline EPP,InferencePool "llm-d-baseline")
       optimized-baseline-decode (llm-d-inference-sim,HPA + WVA 目标)
    otel-collector + jaeger、kube-prometheus-stack (Prometheus/Grafana)
  wva-system: WVA controller + prometheus-adapter (external.metrics.k8s.io 桥接)

  1 个 Gateway 上的 3 条 HTTPRoute,按 header 区分:
    默认 "/"                -> InferencePool llm-d          (真实 GPU,precise-prefix)
    x-llm-d-pool: pd        -> InferencePool llm-d-pd        (sim,P/D)
    x-llm-d-pool: baseline  -> InferencePool llm-d-baseline  (sim,WVA 扩缩容)
```

`gpu-vllm-proxy` 是一个 2 容器的 Pod,用公开的 `alpine/socat` 镜像(无需自建镜像):
容器 `http-proxy` 跑
`socat TCP-LISTEN:8000,fork,reuseaddr TCP:192.168.1.112:8000`,容器 `kv-proxy`
对 5556 端口做同样的事。HTTP 和 vLLM 的 ZMQ KV 事件 PUB 流(ZMTP 本质上是普通的分帧
TCP)都能透明地按字节隧道转发 —— Prometheus 的 `/metrics` 抓取和 EPP 的
OpenAI/ZMQ 流量,最终都原样到达真实的 DGX 进程。

| 组件 | 命名空间 | 作用 |
| --- | --- | --- |
| `agentgateway`(控制面) | `agentgateway-system` | Gateway API + Inference Extension 控制器 |
| `llm-d-inference-gateway`(数据面) | `llm-d` | 代理本身;trace 根 span `POST /*` |
| `payload-processor`(IPP) | `llm-d` | 在 `PreRouting` 阶段的 `ext_proc`;把请求体字段改写进路由 header |
| `llm-d-epp` | `llm-d` | precise-prefix(KV-cache 感知)EPP,服务**真实 GPU**池 |
| `gpu-vllm-proxy` | `llm-d` | socat 桥接 Pod —— InferencePool `llm-d` 的后端,隧道到 DGX Spark |
| `llm-d-pd-epp` / `pd-prefill` / `pd-decode` | `llm-d` | P/D 分离池(sim,KV 传输为模拟) |
| `llm-d-baseline-epp` / `optimized-baseline-decode` | `llm-d` | WVA/HPA 扩缩容池(sim) |
| `otel-collector` + `jaeger` | `llm-d` | 追踪链路 |
| `kube-prometheus-stack`(`llmd` release) | `llm-d-monitoring` | Prometheus + Grafana |
| `wva-controller-manager` + `prometheus-adapter` | `wva-system` | 自动扩缩容控制回路 |

本次运行用到的镜像都是直接从已发布的镜像仓库拉取的 —— **没有做任何本地构建**
(router/EPP/IPP/sim 镜像现在都是 multi-arch 且可公开拉取;唯一一个之前需要自建的
`llm-d-router-disagg-sidecar` 也找到了已发布的 tag)。相比 CPU demo 需要从
`upstream/main` 构建 EPP/sidecar/IPP(因为那时这些镜像还没发布 multi-arch 版本),
这是一个简化。

> 最后验证时间 2026-08-24,对应 `llm-d-router-gateway:v0` chart(digest
> `sha256:7cf1ad13…`)、EPP 镜像
> `ghcr.io/llm-d/llm-d-router-endpoint-picker:main`、IPP `v0.1.0`、routing-sidecar
> `ghcr.io/llm-d/llm-d-router-disagg-sidecar:v0.10.0`、inference-sim `:latest`、
> WVA controller `v0.9.0`、vLLM `nvcr.io/nvidia/vllm:26.05-py3`(为 GB10/Blackwell
> 构建的 vLLM 0.20.1 dev 版本)。

---

## 2. DGX Spark GPU 节点

硬件:NVIDIA **GB10**(Grace-Blackwell,即 "DGX Spark"),arm64 Grace CPU + Blackwell
GPU 共享一块 **130.667 GB 统一内存池**,CUDA 13.0,驱动 580.126.09,Docker 28.5.1 +
nvidia-container-toolkit 1.18.2(在这台机器上 `--gpus all` 直接可用,不需要显式指定
`--runtime=nvidia`)。

**目前还没有官方 `vllm/vllm-openai` 镜像支持这种 arm64+Blackwell 组合。** 经现场测试
确认可用的镜像,是 NVIDIA 自己的 DGX Spark playbook 镜像:
**`nvcr.io/nvidia/vllm:26.05-py3`**(公开可拉取,无需 NGC 登录),内置了针对 GB10 的
vLLM `0.20.1+7124b12a.dev` 版本。

### GPU 显存的真实情况检查 —— 这是整个 demo 中分量最重的一条发现

这台机器是**共享**的:用户的 ComfyUI 会话被特意保留在运行状态(见"已知限制"一节)。
`nvidia-smi` 的聚合显存查询在 GB10 上返回 `Not Supported`(没有固定的显存总量可报告
—— 这是统一内存),而真正起作用的数字 —— `torch.cuda.mem_get_info()` 返回的空闲字
节数 —— **在这一次会话中剧烈波动**,完全跟随 ComfyUI 自身的活动强度(它的进程占用在
相隔几分钟的两次观测中分别是约 14 GiB 和约 28 GiB),事先根本无法预测:

| 时刻 | 空闲显存(`mem_get_info`) | 发生了什么 |
| --- | --- | --- |
| 会话开始 | 约 5.3 GB | 第 1 个 replica(`--gpu-memory-utilization 0.04` ≈5.2GB)顺利启动,权重 2.89 GiB + KV cache 0.56 GiB |
| 紧接着 | 约 1.1 GB | 那一刻没有空间再起第 2 个 replica |
| 会话中段重试 | 约 14.1 GB | **第 2 个真实 replica 确实成功启动了**(`REPLICA_1=true`)—— `vllm-gpu-0` 和 `vllm-gpu-1` 都报告了 `Application startup complete` |
| 约 2 分钟后 | (ComfyUI 又涨回去了) | `vllm-gpu-0` **崩溃**:`RuntimeError: Engine core initialization failed` / `ValueError: No available memory for the cache blocks` |
| 之后重试,只跑 1 个 replica | 约 6.6 GB | 就连**单个** replica、同样 0.04 的预算,也**以同样方式失败了** |
| 最终重试 | —— | 把 `--gpu-memory-utilization` 调低到 0.03(约 3.9GB)后再次成功 |

由此得出两条对如何运行这个 demo 都很关键的结论:(1)**2 个真实 replica 是可以做到
的** —— 只要共享机器恰好有余量,CPU demo 里"2 个 replica 让 KV 路由决策变得可见"
这个场景在原理上并没有被彻底堵死,只是在这台共享机器上**无法按需可靠复现**;
(2)**一次成功的部署不是永久状态** —— 显存随时可能被同一台机器上的其他负载抢走,
结果是一次真实的崩溃(而不是优雅降级)。`gpu-node/deploy-vllm.sh` 的默认
`GPU_MEM_UTIL` 因此从 0.04 调低到了 0.03,`REPLICA_1=true` 仍然作为一个应急开关保
留着 —— 把这两者都当作"有概率成功",而不是"保证成功",并且始终以
`bash gpu-node/healthcheck.sh` 的结果为准,而不是想当然地认为"之前成功过,现在应
该还在"。完整事故记录见 `docs/TEST_PLAN.md` 的 TC-GPU-05。

部署脚本:`gpu-node/deploy-vllm.sh`(通过 SSH 执行幂等的 `docker run`)。
现场验证:

```console
$ bash gpu-node/deploy-vllm.sh
...
(EngineCore pid=258) INFO gpu_model_runner.py:4879 Model loading took 2.89 GiB memory and 60.297843 seconds
(EngineCore pid=258) INFO gpu_worker.py:440 Available KV cache memory: 0.56 GiB
(EngineCore pid=258) INFO kv_cache_utils.py:1708 GPU KV cache size: 20,992 tokens
(EngineCore pid=258) INFO kv_events.py:329 Starting ZMQ publisher thread
INFO:     Application startup complete.
==> Smoke test
{"object": "list", "data": [{"id": "Qwen/Qwen2.5-1.5B-Instruct", ...}]}
```

来自 DGX Spark 本机的一次真实对话补全:

```console
$ curl -sS -X POST http://localhost:8000/v1/chat/completions -d '{"model":"Qwen/Qwen2.5-1.5B-Instruct","messages":[{"role":"user","content":"Say hello in 5 words"}],"max_tokens":20}'
{"choices":[{"message":{"content":"Hello! How can I assist you today?"}}], "usage":{"prompt_tokens":35,"completion_tokens":10}}
```

`nvidia-smi` 确认了一个真实的 `VLLM::EngineCore` GPU 进程(4809 MiB),和 ComfyUI 的
两个进程并存。从 Mac 上(因此也包括 Kind pod 内部,因为 Docker Desktop 会把出站流量
路由到局域网)的可达性,用 `gpu-node/healthcheck.sh` 确认过。

---

## 3. 安装步骤

共用变量:

```console
export LLMD_REPO=$HOME/go/src/github.com/llm-d/llm-d
export ROUTER_REPO=$HOME/go/src/github.com/llm-d/llm-d-router
export IPP_REPO=$HOME/go/src/github.com/llm-d/llm-d-inference-payload-processor
export DEMO=$HOME/go/src/github.com/gyliu513/langX101/llm-d/llm-d-gpu-demo
```

### 3.1 在 DGX Spark 上部署 vLLM

```console
cp $DEMO/.env.example $DEMO/.env   # DGX_HOST=192.168.1.112, DGX_USER=lgy, DGX_MODEL=Qwen/Qwen2.5-1.5B-Instruct
bash $DEMO/gpu-node/deploy-vllm.sh
bash $DEMO/gpu-node/healthcheck.sh
```

### 3.2 创建 Kind 集群

```console
kind create cluster --config $DEMO/kind/kind-config.yaml
kubectl apply -f $DEMO/manifests/00-namespace.yaml
```

这里不需要像 CPU demo 那样挂载 HF 缓存的 hostPath —— 真实的模型权重放在 DGX Spark
上,而不在 Kind 集群里。

### 3.3 Gateway API + GAIE + llm-d.ai CRD

```console
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.5.0/v1-manifests.yaml
kubectl apply -k $ROUTER_REPO/config/crd
```

### 3.4 agentgateway 控制面 + Gateway

```console
helm upgrade --install agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds \
  --namespace agentgateway-system --create-namespace --version v1.1.0
helm upgrade --install agentgateway oci://cr.agentgateway.dev/charts/agentgateway \
  --namespace agentgateway-system --create-namespace --version v1.1.0 \
  --set inferenceExtension.enabled=true
kubectl apply -k "https://github.com/llm-d/llm-d/guides/recipes/gateway/agentgateway?ref=main" -n llm-d
```

### 3.5 OTel Collector + Jaeger

```console
bash $LLMD_REPO/guides/recipes/observability/install-otel-collector-jaeger.sh -n llm-d
```

### 3.6 GPU 桥接 Pod(要在 EPP release 之前部署 —— 它需要有一个后端可选)

```console
bash $LLMD_REPO/guides/recipes/observability/install-prometheus-grafana.sh --crds-only
kubectl apply -f $DEMO/manifests/optional/gpu-proxy/gpu-vllm-proxy.yaml
```

现场验证 —— Kind 内部的一个 Pod 通过隧道打到了真实 GPU 推理:

```console
$ kubectl run trig2 --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
  curl -sS -X POST http://10.244.0.9:8000/v1/chat/completions -d '{"model":"Qwen/Qwen2.5-1.5B-Instruct",...}'
{"id":"chatcmpl-96cf154a307c70a5", "choices":[{"message":{"content":"Hello! How can I assist you today?"}}]}
```

### 3.7 Precise-prefix router release(真实 GPU)

```console
kubectl create secret generic llm-d-hf-token -n llm-d --from-literal=HF_TOKEN="" --dry-run=client -o yaml | kubectl apply -f -
helm install llm-d oci://ghcr.io/llm-d/charts/llm-d-router-gateway --version v0 \
  -f $DEMO/manifests/optional/precise-prefix/precise-prefix-router.values.yaml \
  -f $DEMO/helm-values/tracing.values.yaml \
  -f $DEMO/helm-values/gw-kind.values.yaml \
  --set provider.name=none --set httpRoute.create=true \
  --set httpRoute.inferenceGatewayName=llm-d-inference-gateway \
  -n llm-d
```

> Chart/镜像名字在 CPU demo 构建之后三周内发生了变化:OCI chart 去掉了 `-dev` 后缀
> (`llm-d-router-gateway-dev` → `llm-d-router-gateway`),EPP 镜像仓库同样
> (`llm-d-router-endpoint-picker-dev` → `llm-d-router-endpoint-picker`)。完整列表
> 见下方"本次运行中发现的上游变化"一节。

现场验证 —— EPP `2/2 Running`,ZMQ subscriber 通过 proxy Pod 连上了:

```console
$ kubectl logs -n llm-d deploy/llm-d-epp -c epp | grep zmq
{"logger":"zmq-subscriber","msg":"Connected subscriber socket","endpoint":"tcp://10.244.0.9:5556"}
```

### 3.8 IPP

```console
helm install ipp $IPP_REPO/config/charts/payload-processor -n llm-d \
  -f $DEMO/helm-values/ipp.values.yaml --set provider.name=none
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata: {name: ipp-extproc, namespace: llm-d}
spec:
  targetRefs: [{group: gateway.networking.k8s.io, kind: Gateway, name: llm-d-inference-gateway}]
  traffic: {phase: PreRouting, extProc: {backendRef: {kind: Service, name: payload-processor, port: 9004}}}
EOF
```

### 3.9 Gateway 追踪导出

```console
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata: {name: gateway-tracing, namespace: llm-d}
spec:
  targetRefs: [{group: gateway.networking.k8s.io, kind: Gateway, name: llm-d-inference-gateway}]
  frontend: {tracing: {backendRef: {kind: Service, name: otel-collector, port: 4317}, protocol: GRPC, randomSampling: "true"}}
EOF
```

### 3.10 P/D 分离池

```console
helm install llm-d-pd oci://ghcr.io/llm-d/charts/llm-d-router-gateway --version v0 \
  -f $DEMO/manifests/optional/pd/pd-router.values.yaml \
  -f $DEMO/helm-values/tracing.values.yaml \
  -f $DEMO/helm-values/gw-kind-pd.values.yaml \
  --set provider.name=none --set httpRoute.create=true \
  --set httpRoute.inferenceGatewayName=llm-d-inference-gateway \
  --set httpRoute.headerMatches.x-llm-d-pool=pd \
  -n llm-d
kubectl apply -f $DEMO/manifests/optional/pd/model-servers-pd.yaml
```

> chart 的 `httpRoute.headerMatches` map(CPU demo 之后新增的能力)可以直接创建按
> header 匹配的路由 —— 不再需要手写 `HTTPRoute` YAML 了。

### 3.11 Baseline 池 + HPA(WVA 目标)

```console
kubectl apply -f $DEMO/manifests/optional/baseline/model-servers-baseline.yaml
helm install llm-d-baseline oci://ghcr.io/llm-d/charts/llm-d-router-gateway --version v0 \
  -f $DEMO/helm-values/tracing.values.yaml \
  -f $DEMO/helm-values/gw-kind-baseline.values.yaml \
  --set provider.name=none --set httpRoute.create=true \
  --set httpRoute.inferenceGatewayName=llm-d-inference-gateway \
  --set httpRoute.headerMatches.x-llm-d-pool=baseline \
  -n llm-d
kubectl apply -f $DEMO/manifests/06-hpa.yaml
kubectl apply -f $DEMO/manifests/optional/baseline/podmonitor-baseline.yaml
```

> 如果没有最后这个 PodMonitor,Prometheus(进而 WVA)就完全看不到
> `optimized-baseline-decode` 自己的指标 —— 这是在 TC-WVA-06 中现场发现的,当时 WVA
> 一直记录 `"No saturation metrics available for model"`,加上这个 PodMonitor 之后
> 才解决。如果它在 ~30 秒内没有出现在 Prometheus targets 里,强制触发一次 resync
> (和 CPU demo 里 `podMonitor/llm-d/decode` 遇到的是同一个竞态问题):
> `kubectl annotate podmonitor -n llm-d optimized-baseline-decode resync="$(date +%s)" --overwrite`。

### 3.12 Prometheus + Grafana

```console
bash $LLMD_REPO/guides/recipes/observability/install-prometheus-grafana.sh
```

### 3.13 Workload Variant Autoscaler

WVA 控制器的安装流程相比 CPU demo **发生了明显变化**(见下面"上游变化"一节)——
`deploy/install.sh` 的新默认值 `SCALER_BACKEND=keda`,以及它内置的 Gateway API CRD
重装动作(`v1.2.0`),和已有的 v1.5.1 版本冲突,所以这次改用了 **Kustomize 直接安装
controller** 的方式:

```console
# 在 upstream/main 上开一个临时 worktree,不动用户自己分支的工作区
git -C $HOME/go/src/github.com/llm-d/llm-d-workload-variant-autoscaler fetch upstream
git -C $HOME/go/src/github.com/llm-d/llm-d-workload-variant-autoscaler worktree add --detach /tmp/wva-main upstream/main
kubectl apply -k /tmp/wva-main/config/overlays/cluster-scoped/kubernetes   # 镜像在 kustomization.yaml 里已固定为 v0.9.0

# 让 controller 指向我们这套明文 HTTP 的 kube-prometheus-stack(patch ConfigMap):
#   PROMETHEUS_BASE_URL: "http://llmd-kube-prometheus-stack-prometheus.llm-d-monitoring.svc.cluster.local:9090"
#   PROMETHEUS_ALLOW_HTTP: "true"
#   (去掉 PROMETHEUS_TLS_INSECURE_SKIP_VERIFY —— 和 ALLOW_HTTP 同时设置会被拒绝)
kubectl set env deploy/wva-controller-manager -n wva-system PROMETHEUS_TOKEN_PATH-   # 明文 HTTP 下去掉 bearer token 认证

# 让 HPA 能读到 wva_desired_replicas 的 external.metrics.k8s.io 桥接层:
helm upgrade --install prometheus-adapter prometheus-community/prometheus-adapter -n wva-system \
  -f <(git -C $LLMD_REPO show upstream/main:guides/workload-autoscaling/components/prometheus-adapter/wva-adapter-values.yaml) \
  --set prometheus.url=http://llmd-kube-prometheus-stack-prometheus.llm-d-monitoring.svc.cluster.local \
  --set prometheus.port=9090
```

端到端现场验证(WVA 产出指标,prometheus-adapter 对外提供,HPA 消费):

```console
$ kubectl logs -n wva-system deploy/wva-controller-manager | tail -3
"msg":"Optimization completed successfully","mode":"saturation","modelsProcessed":1,"decisionsApplied":0
"msg":"EmitReplicaMetrics completed","variantName":"optimized-baseline-decode-hpa","currentReplicas":1,"desiredReplicas":1

$ curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=wva_desired_replicas'
{"metric":{"variant_name":"optimized-baseline-decode-hpa","exported_namespace":"llm-d"}, "value":[..., "1"]}

$ kubectl get --raw /apis/external.metrics.k8s.io/v1beta1/namespaces/llm-d/wva_desired_replicas
{"items":[{"metricName":"wva_desired_replicas", ..., "value":"1"}]}

$ kubectl get hpa -n llm-d optimized-baseline-decode-hpa
NAME                             REFERENCE                              TARGETS     MINPODS  MAXPODS  REPLICAS
optimized-baseline-decode-hpa   Deployment/optimized-baseline-decode   1/1 (avg)   1        4        1
```

`AcceleratorNotResolved` 告警是预期内的、不影响功能的 —— baseline 池跑的是
`llm-d-inference-sim`(没有 GPU nodeSelector),和 CPU demo 一样。

---

## 4. 最终状态(本次运行)

```console
$ kubectl get pods -A   # 省略 kube-system、local-path-storage
NAMESPACE             NAME                                      READY   STATUS
agentgateway-system   agentgateway-...                          1/1     Running
llm-d                 gpu-vllm-proxy-...                        2/2     Running
llm-d                 jaeger-...                                1/1     Running
llm-d                 llm-d-baseline-epp-...                    1/1     Running
llm-d                 llm-d-epp-...                              2/2     Running
llm-d                 llm-d-inference-gateway-...                1/1     Running
llm-d                 llm-d-pd-epp-...                          1/1     Running
llm-d                 optimized-baseline-decode-...              1/1     Running
llm-d                 otel-collector-...                        1/1     Running
llm-d                 payload-processor-...                     1/1     Running
llm-d                 pd-decode-...                              2/2     Running
llm-d                 pd-prefill-...                             1/1     Running
llm-d-monitoring      alertmanager-... / grafana / operator / kube-state-metrics / node-exporter / prometheus   全部 Running
wva-system            prometheus-adapter-...                    1/1     Running
wva-system            wva-controller-manager-...                1/1     Running

$ kubectl get inferencepool,httproute -n llm-d
inferencepool.../llm-d          inferencepool.../llm-d-baseline   inferencepool.../llm-d-pd
httproute.../llm-d              httproute.../llm-d-baseline       httproute.../llm-d-pd

$ kubectl describe node llm-d-gpu-control-plane | grep -A4 Allocated
Allocated resources:
  cpu     4035m (28%)   14950m (106%)
  memory  9178Mi (39%)  19782Mi (85%)
```

之所以所有东西都能塞进一个 Kind 节点(Docker Desktop 14 CPU / 约 23 Gi 的预算),
*是因为*真正的推理计算发生在集群之外的 DGX Spark 上 —— 集群内的占用只是路由/可观测
性组件,再加两个很小的 `inference-sim` 池。

---

## 5. 测试步骤

完整、详细的测试用例集见 **[`docs/TEST_PLAN.md`](docs/TEST_PLAN.md)**
(TC-GPU-\*、TC-BRIDGE-\*、TC-ROUTE-\*、TC-TRACE-\*、TC-KV-\*、TC-PD-\*、
TC-WVA-\*、TC-METRICS-\*、TC-NEG-\*)。以下是本次运行中现场验证结果的汇总:

| 项目 | 证据 | 结果 |
| --- | --- | --- |
| 真实 GPU 推理 | `nvidia-smi` 显示 `VLLM::EngineCore` 进程;真实的对话补全 | ✅ |
| Proxy-Pod 桥接(HTTP) | 集群内 curl 经 Pod IP 打到 DGX,响应结构一致 | ✅ |
| Proxy-Pod 桥接(ZMQ) | EPP 日志 `Connected subscriber socket endpoint=tcp://<proxy-pod-ip>:5556` | ✅ |
| 三向 HTTPRoute 优先级 | 默认路径 / `x-llm-d-pool: pd` / `x-llm-d-pool: baseline` 都各自返回 200 | ✅ |
| Gateway → EPP 追踪拼接 | `gateway.request` span 的 parent 是 `llm-d-inference-gateway`(不是孤立根节点) | ✅ |
| IPP → EPP 追踪拼接 | 本次运行**未复现** —— IPP 功能正常(日志确认了 header 注入),但自己产生了一条断开的根 trace。见"上游变化" | ⚠️ 相比 CPU demo 的回归 |
| Precise-prefix 调度器 span | `produce_precise_prefix_cache`、`run_scheduler_profile`、`llm_d.epp.scorer.*`(×3)、`pick_endpoints`、`index_lookup`/`index_add` —— 一次真实 GPU 请求上 14 个 span、2 个服务 | ✅ |
| 真实 KV-cache **命中** | **未复现** —— vLLM 0.20.1 的 KV 事件 payload 里 `cache_kind` 字段不被这个 router 版本识别;事件传输是正常的(`messages_received_total=1`),但被跳过了(`stores_skipped_total{reason=unsupported_cache_kind}=1`)。见"上游变化" | ⚠️ 版本不匹配发现 |
| P/D 分离 trace | 27 个 span / 3 个服务:`pick_disagg_profile` ×3、`prepare_disaggregation` ×2、sidecar 的 `prefill`/`decode`/`forward_request` | ✅ |
| 指标闭环 | 3 个 EPP ServiceMonitor + GPU-proxy PodMonitor 在 Prometheus 里都是 UP;`vllm:time_to_first_token_seconds_count` = 6(真实 GPU 直方图) | ✅ |
| Grafana 仪表盘 | 7 个 llm-d 仪表盘全部加载;vLLM Overview 面板上能看到实时数据点 | ✅ |
| WVA 自动扩缩容回路(指标 → external API → HPA 目标) | `wva_desired_replicas` → external metrics API → HPA `1/1 (avg)` | ✅ |
| WVA 在合成负载下的真实扩容 | 顺带发现并修复了 baseline 池缺失 PodMonitor 的问题;修复后,`llm-d-inference-sim` 在这次施加的负载下仍未表现出可观测的排队深度(TC-WVA-06) | ⚠️ 未复现 |
| 第 2 个真实 GPU replica | 在共享机器恰好有余量时成功启动过一次(`REPLICA_1=true`),几分钟后其中一个在显存重新被抢占时崩溃 —— 见 §2 | ⚠️ 可行,但不稳定 |

---

## 6. 可观测性截图

以下所有截图都来自这次真实运行(`docs/screenshots/`),不是效果图。

**默认路径 —— 真实 GPU 的 precise-prefix trace**(14 个 span / 2 个服务):完整的调
度器子树 —— `tokenize_render`、`produce_precise_prefix_cache`、
`run_scheduler_profile` 展开为 3 个 `llm_d.epp.scorer.*` 子节点,然后是
`pick_endpoints` —— 对应一个实际由 DGX Spark GPU 处理的请求。

![Jaeger —— 真实 GPU 默认路径 trace](docs/screenshots/jaeger-traces.png)

**P/D 分离路径 trace**(27 个 span / 3 个服务):`pick_disagg_profile` ×3
(prefill profile、decode profile,以及合并的一趟)、两棵完整的
`run_scheduler_profile` 子树、`prepare_disaggregation` ×2,以及
`llm-d-routing-sidecar` 服务真实的两段代理(`forward_request` →
`prefill` → `decode` → `HTTP POST` ×2)。

![Jaeger —— P/D 分离 trace](docs/screenshots/jaeger-pd-trace.png)

**Prometheus targets** —— 3 个 EPP `ServiceMonitor` 和 `gpu-vllm-proxy` 的
`PodMonitor` 全部 UP;唯一 DOWN 的是这个 Kind 集群本来就不存在的控制面组件
(etcd/kube-proxy/scheduler/controller-manager),这是预期内的。

![Prometheus targets 页面](docs/screenshots/prometheus-targets.png)

**Prometheus 查询 —— 真实 GPU 的 TTFT 直方图**,经由 `gpu-vllm-proxy` 隧道抓取
(`vllm:time_to_first_token_seconds_count`):

![Prometheus 查询结果 —— vLLM TTFT 计数](docs/screenshots/prometheus-query-ttft.png)

**Grafana —— 安装器加载的 7 个 llm-d 仪表盘**:

![Grafana 仪表盘列表](docs/screenshots/grafana-dashboards-list.png)

**Grafana —— llm-d vLLM Overview**,Token Throughput、TTFT、Queue Time、
Prefill/Decode Time、Max Generation Token 等面板上都能看到实时数据点:

![Grafana llm-d vLLM Overview 仪表盘](docs/screenshots/grafana-vllm-overview.png)

**Grafana —— llm-d Performance Dashboard**(端到端延迟、KV-cache 命中率、
请求吞吐量):

![Grafana llm-d Performance 仪表盘](docs/screenshots/grafana-performance.png)

---

## 7. 本次运行中发现的上游变化(2026-08-24,相对 CPU demo 2026-08-03 基线)

llm-d 这个项目迭代很快;短短三周就产生了真正的破坏性变化:

1. **Chart/镜像改名。** `llm-d-router-gateway-dev` → **`llm-d-router-gateway`**
   (去掉 `-dev`);`llm-d-router-endpoint-picker-dev` →
   **`llm-d-router-endpoint-picker`**。
2. **`llm-d` 仓库里的 `guides/recipes/router/` 被删除了。** 原来
   `base.values.yaml` / `features/monitoring.values.yaml` 那种分层叠加的用法没
   有了;监控现在是一个普通的 values 开关
   (`router.monitoring.prometheus.enabled: true`,
   `.auth.enabled: false` 表示允许无认证抓取)。
3. **`httpRoute.headerMatches`** 现在是 chart 里的一等公民 values —— 按 header
   路由的池子不再需要手写 `HTTPRoute` YAML。
4. **`llm-d-routing-sidecar` 改名为 `llm-d-router-disagg-sidecar`**,有了真正
   打好 tag 的发布版本(`v0.10.0`),取代了原来要从源码构建浮动 `:main` 的做法。
   命令行 flag 没变(`--kv-connector`、`--model-server-port`、
   `--secure-proxy=false`、`--tracing`)。
5. **WVA 又"反复横跳"回了支持 CRD 的形态,而且默认改成了 KEDA。** 之前 CPU demo
   得出的结论("`VariantAutoscaling` CRD 已废弃,改用 HPA 注解")本身也被部分推翻
   了:`VariantAutoscaling` 现在又重新被记录为多 variant 场景下的用法,同时本
   demo 用的简单 HPA 注解路径依然照常工作。`deploy/install.sh` 新的默认值
   `SCALER_BACKEND=keda`,加上它内置的 Gateway API CRD 降级安装动作,和我们已有
   的 v1.5.1 CRD 冲突了 —— 改用 Kustomize 直接安装 controller 的方式绕过(见
   §3.13)。
6. **在这个 agentgateway 版本上,IPP 没有拼进 gateway→EPP 的 trace 里**,尽管它
   功能上是正常的(通过 IPP pod 日志确认:请求/响应体处理、
   `X-Gateway-Model-Name` header 注入都发生了)。它在 Jaeger 里表现为自己独立、
   断开的 service/trace,而不是 CPU demo 在 2026-08-03 展示的那个中间节点。没有
   进一步定位根因(目前最有可能的假设是 agentgateway 的 ext_proc 阶段顺序,和
   `InferencePool` 原生 ext_proc 接线方式之间的冲突)—— 在这里如实标注,而不是
   反复调整参数直到"看起来又恢复了原来的形状"就当作修好了。
7. **KV-cache 事件的 schema 版本不匹配。** `nvcr.io/nvidia/vllm:26.05-py3` 里的
   vLLM(`0.20.1+7124b12a.dev`)发布的 KV-cache 事件消息里,`cache_kind` 字段不
   被这个 router 版本的解码器识别
   (`llm_d_epp_kv_cache_events_stores_skipped_total{reason="unsupported_cache_kind"}`)。
   传输链路(经 proxy Pod 的 ZMQ 隧道)已证实是正常工作的 —— 收到了一条消息,
   日志/指标里都留下了痕迹 —— 只是这个 block 从未被真正录入 prefix index,所以
   `produce_precise_prefix_cache` 一直报告 `max_match_blocks=0`。这看起来是一次
   非常新的 vLLM nightly 版本和 router 事件解析器之间真实的版本不匹配,值得向上
   游报告,而不是这个 demo 设计上的缺陷。

---

## 已知限制(这些是设计使然,不是 bug)

- **稳定运行时是 1 个真实 GPU replica;第 2 个是可能的,但不可靠。**
  见 §2 —— DGX Spark 的统一内存和用户的 ComfyUI 会话共享,后者的占用会独立波动。
  第 2 个 replica(`REPLICA_1=true`)确实成功启动过一次,几分钟后其中一个在显存
  重新吃紧时崩溃了。本 demo 以 1 个 replica 作为稳妥的默认配置;CPU demo 里"2 个
  replica 让 KV 路由决策变得可见"这个场景在这台硬件上是有机会碰到的,但不能保证。
- **一次成功的 vLLM 部署,后续可能被同一台机器上不相关的 GPU 负载挤掉。** 不只
  是启动阶段的风险 —— 一个正在运行的 replica 曾在会话中途、另一个进程的显存占用
  上涨后崩溃(`Engine core initialization failed`)。始终用
  `healthcheck.sh` 重新确认,而不要信任"之前成功过"。
- **P/D 的 KV 传输仍然是模拟的。** 真正的 NIXL prefill/decode 分离需要 ≥2 块物
  理 GPU;这台 DGX Spark 只有 1 块。调度、header 处理,以及 routing-sidecar 的
  两段代理,都是真实的。
- **WVA/baseline 池跑在 `llm-d-inference-sim` 上,不是真实 GPU。** WVA 是作为
  一个控制回路机制(Prometheus → external-metrics API → HPA)被验证的,和具体由
  哪个后端服务流量无关 —— 这和 CPU demo 的验证范围是一致的。
- **本次运行没有现场演示出真实的 KV-cache 命中路由** —— 见"上游变化"第 7 条。
  围绕它的调度器/评分器机制(§6,`llm_d.epp.scorer.*` span、`pick_endpoints`)
  是被完整、正确执行过的;只是命中/未命中这个具体结果,和 CPU demo 的结果不同。
