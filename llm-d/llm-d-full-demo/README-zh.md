# llm-d 完整栈可观测性演示（无 GPU 环境）

本指南在本地 Kind 集群上部署**完整的 llm-d 生产架构**，通过 **Prometheus**（指标）、**Grafana**（仪表盘）、**Jaeger**（分布式追踪）实现三位一体的端到端全链路可观测性，无需 GPU。

> **English version:** [README.md](./README.md)

---

## 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Kind 集群（单节点，14 CPU / 23 GB）                                          │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  llm-d 命名空间                                                      │   │
│  │                                                                      │   │
│  │   客户端                                                              │   │
│  │     │ HTTP :80                                                       │   │
│  │     ▼                                                                │   │
│  │  ┌─────────────────────────────────────────────┐                    │   │
│  │  │  llm-d-epp Pod（2 个容器）                    │                    │   │
│  │  │                                             │                    │   │
│  │  │  ┌─────────────┐   gRPC    ┌─────────────┐ │                    │   │
│  │  │  │   Envoy     │◄─────────►│    EPP      │ │                    │   │
│  │  │  │   代理       │  :9002    │  （端点选择器）│ │                    │   │
│  │  │  │   :8081     │           │             │ │                    │   │
│  │  │  └──────┬──────┘           └──────┬──────┘ │                    │   │
│  │  └─────────┼───────────────────────── ┼────────┘                    │   │
│  │            │ 路由到选中的 Pod           │ OTLP traces                 │   │
│  │            │                          ▼                             │   │
│  │            │              ┌────────────────────┐                   │   │
│  │            │              │   OTel Collector   │                   │   │
│  │            │              │      :4317         │                   │   │
│  │            │              └─────────┬──────────┘                   │   │
│  │            │                        │ OTLP 转发                    │   │
│  │            │                        ▼                             │   │
│  │            │              ┌────────────────────┐                   │   │
│  │            │              │      Jaeger        │                   │   │
│  │            │              │    UI :16686       │                   │   │
│  │            │              └────────────────────┘                   │   │
│  │            │                                                       │   │
│  │            ▼  InferencePool "llm-d"                                │   │
│  │     ┌──────────┐    ┌──────────┐                                   │   │
│  │     │ decode-0 │    │ decode-1 │  （inference-sim，port 8000）     │   │
│  │     └──────────┘    └──────────┘                                   │   │
│  │          │ OTLP traces                                              │   │
│  │          └──────────────► OTel Collector ──► Jaeger               │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  llm-d-monitoring 命名空间                                            │   │
│  │  Prometheus（HTTPS/TLS）◄── ServiceMonitor（EPP :9090）              │   │
│  │                         ◄── PodMonitor（model servers :8000）       │   │
│  │  Grafana ◄── 5 个 llm-d 仪表盘                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 数据流图

```
                     ┌──────────────────────────────────────────────────────┐
                     │                可观测性数据流向                        │
                     └──────────────────────────────────────────────────────┘

 ┌────────┐  HTTP   ┌────────┐ ext_proc ┌────────┐  HTTP   ┌──────────┐
 │ 客户端  │────────►│ Envoy  │──────────►│  EPP   │────────►│ decode-N │
 │        │◄────────│ :8081  │◄──────────│ :9002  │◄────────│  :8000   │
 └────────┘  响应   └────────┘  路由决策  └────────┘  响应   └──────────┘
                                              │                   │
                                              │                   │
             ────────────────── METRICS ──────┼───────────────────┼────────
                                              │                   │
                                         ┌────▼────┐         ┌────▼────┐
                                         │Service  │         │  Pod    │
                                         │Monitor  │         │Monitor  │
                                         │（EPP）   │         │（模型    │
                                         └────┬────┘         │服务器）  │
                                              │              └────┬────┘
                                              ▼                   ▼
                                         ┌──────────────────────────────┐
                                         │  Prometheus（HTTPS :9090）    │
                                         │  llm-d-monitoring 命名空间    │
                                         └──────────────┬───────────────┘
                                                        │
                                                        ▼
                                         ┌──────────────────────────────┐
                                         │     Grafana（:3000）          │
                                         │   5 个 llm-d 仪表盘           │
                                         └──────────────────────────────┘

             ────────────────── TRACES ──────┼───────────────────┼────────
                                             │                   │
                                        OTLP gRPC           OTLP gRPC
                                       （EPP spans）         （sim spans）
                                             │                   │
                                             ▼                   ▼
                                         ┌──────────────────────────────┐
                                         │   OTel Collector（:4317）     │
                                         │   - 过滤 /metrics 轮询 span   │
                                         │   - 批量聚合后转发             │
                                         └──────────────┬───────────────┘
                                                        │ OTLP
                                                        ▼
                                         ┌──────────────────────────────┐
                                         │     Jaeger（:16686）          │
                                         │   - gateway.request           │
                                         │   - gateway.request_          │
                                         │     orchestration             │
                                         └──────────────────────────────┘
```

---

## 组件说明

| 组件 | 命名空间 | 类型 | 描述 |
|---|---|---|---|
| `llm-d-epp` | `llm-d` | Pod（2 容器） | **Envoy 代理**（port 80→8081）+ **EPP**（gRPC :9002） |
| `InferencePool/llm-d` | `llm-d` | CR | 监听带 `llm-d.ai/guide=optimized-baseline` 标签的 Pod |
| `InferenceObjective/llm-d-standard` | `llm-d` | CR | Priority=0 流控目标 |
| `optimized-baseline-decode` | `llm-d` | Deployment（2 副本） | inference-sim 模拟 vLLM 模型服务器 |
| `otel-collector` | `llm-d` | Deployment | 接收 OTLP traces，过滤噪声，转发给 Jaeger |
| `jaeger` | `llm-d` | Deployment | Trace 存储 + UI（port 16686） |
| `ServiceMonitor/llm-d-epp-monitor` | `llm-d` | CR | Prometheus 抓取 EPP 指标（:9090） |
| `PodMonitor/llm-d-model-servers` | `llm-d` | CR | Prometheus 抓取模型服务器指标（:8000） |
| Prometheus（HTTPS/TLS） | `llm-d-monitoring` | StatefulSet | 指标存储 |
| Grafana | `llm-d-monitoring` | Deployment | 5 个预装 llm-d 仪表盘 |

### 可观测性覆盖范围

| 信号类型 | 工具 | 来源 | 数量 |
|---|---|---|---|
| **指标（Metrics）** | Prometheus + Grafana | EPP（ServiceMonitor）+ 模型服务器（PodMonitor） | 35+ EPP + 41 vLLM |
| **追踪（Traces）** | Jaeger + OTel Collector | EPP（`llm-d-router/epp`）+ 模型服务器 | 每请求 2 个 span |

---

## 前提条件

- **Kind** v0.29+、**Docker Desktop**（已分配 14+ CPU、20+ GB RAM）
- **kubectl**、**Helm** v3.10+
- **jq**、**python3**
- 已克隆 llm-d 仓库：`git clone https://github.com/llm-d/llm-d.git && cd llm-d`

---

## 安装步骤

### 第 1 步：创建 Kind 集群

```bash
mkdir -p /tmp/llm-d-cache

kind create cluster \
  --config docs/monitoring/llm-d-full-demo/kind/kind-config.yaml
```

验证：
```bash
kubectl get nodes
# NAME                  STATUS   ROLES
# llm-d-control-plane   Ready    control-plane
```

---

### 第 2 步：拉取并加载 inference-sim 镜像

**Apple Silicon（arm64）**：
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

**x86_64**：
```bash
docker pull ghcr.io/llm-d/llm-d-inference-sim:v0.8.0
kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.8.0 --name llm-d
# 同时修改 manifests/01-model-servers.yaml 中的镜像 tag 为 v0.8.0
```

---

### 第 3 步：安装 CRDs

> **重要：** Monitoring CRDs 必须在 llm-d router Helm chart 之前安装，否则 ServiceMonitor 创建会失败。

```bash
# 3a. Monitoring CRDs（ServiceMonitor、PodMonitor）——必须最先安装
bash docs/monitoring/scripts/install-prometheus-grafana.sh --crds-only

# 3b. GAIE CRDs（InferencePool、InferenceObjective）
kubectl apply -k \
  "https://github.com/kubernetes-sigs/gateway-api-inference-extension/config/crd?ref=v1.5.0"
```

验证：
```bash
kubectl get crd | grep -E "inferencep|monitoring.coreos"
```

---

### 第 4 步：安装 Prometheus + Grafana

```bash
bash docs/monitoring/scripts/install-prometheus-grafana.sh --enable-tls
```

---

### 第 5 步：安装 llm-d Router（含 Tracing）

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

`tracing.values.yaml` 配置 EPP 将 trace 发送到 `http://otel-collector:4317`。

---

### 第 6 步：部署 OTel Collector + Jaeger

OTel Collector 和 Jaeger 必须与 llm-d 组件**在同一命名空间**，才能通过 `http://otel-collector:4317` 接收 traces。

```bash
bash docs/monitoring/scripts/install-otel-collector-jaeger.sh -n llm-d
```

部署内容：
- **OTel Collector** — 接收 OTLP gRPC（:4317），过滤 `/metrics` 轮询 span，批量转发给 Jaeger
- **Jaeger**（all-in-one，内存存储）— Trace 存储 + UI（:16686）

---

### 第 7 步：部署模型服务器

```bash
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/01-model-servers.yaml
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/02-inferencemodel.yaml
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/03-podmonitor.yaml
```

模型服务器清单中已内置 OTEL 环境变量，让 inference-sim 导出 traces：
```yaml
env:
- name: OTEL_SERVICE_NAME
  value: "llm-d-model-server"
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: "http://otel-collector:4317"
- name: OTEL_TRACES_SAMPLER_ARG
  value: "1.0"   # 100% 采样率（开发环境；生产环境建议 0.1）
```

等待就绪：
```bash
kubectl wait --for=condition=Ready pods --all -n llm-d --timeout=90s
kubectl get pods -n llm-d
```

预期输出：
```
NAME                                        READY   STATUS
jaeger-xxx                                  1/1     Running
llm-d-epp-xxx                               2/2     Running
llm-d-traffic-gen-xxx                       1/1     Running
optimized-baseline-decode-xxx (×2)          1/1     Running
otel-collector-xxx                          1/1     Running
```

---

### 第 8 步：部署流量生成器

```bash
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/04-traffic-generator.yaml
```

```bash
kubectl logs -n llm-d deploy/llm-d-traffic-gen -f
# req=5 [200] Describe transformer architecture.
# req=6 [200] How does load balancing work?
```

---

## 访问可观测性工具

### Prometheus（指标）

```bash
kubectl port-forward -n llm-d-monitoring \
  svc/llmd-kube-prometheus-stack-prometheus 9090:9090
```

打开：[https://localhost:9090](https://localhost:9090)（接受自签名证书）

---

### Grafana（仪表盘）

```bash
kubectl port-forward -n llm-d-monitoring svc/llmd-grafana 3000:80
```

打开：[http://localhost:3000](http://localhost:3000) — 用户名/密码：`admin` / `admin`

| 仪表盘 | 内容 |
|---|---|
| **llm-d vLLM Overview** | Token 吞吐量、请求速率、TTFT |
| **llm-d Failure & Saturation** | 错误率、队列深度、抢占事件 |
| **llm-d Diagnostic Drill-Down** | 按 Pod 详细指标 |
| **llm-d Performance (KV Cache)** | KV 缓存使用率时间序列 |
| **P/D Coordinator Metrics** | Prefill/Decode 分离指标 |

---

### Jaeger（分布式追踪）

```bash
kubectl port-forward -n llm-d svc/jaeger-collector 16686:16686
```

打开：[http://localhost:16686](http://localhost:16686)

在 Jaeger UI 中：
1. **Service** → 选择 `llm-d-router/epp`
2. **Find Traces** → 查看真实的 EPP 路由 span
3. 点击任意 trace 查看详情：
   - `gateway.request` — 完整请求生命周期
   - `gateway.request_orchestration` — EPP 调度决策（选 Pod）

---

### 发送测试请求

```bash
kubectl port-forward -n llm-d svc/llm-d-epp 8081:80 &
curl -s -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct",
       "messages":[{"role":"user","content":"What is llm-d?"}],
       "max_tokens":50}' | jq
```

发送后去 Jaeger 查找对应的 trace。

---

## 测试用例

### 指标测试（Prometheus / Grafana）

#### TC-1：EPP 调度延迟 P99

```promql
histogram_quantile(0.99, sum by(le) (
  rate(inference_extension_scheduler_e2e_duration_seconds_bucket[5m])
))
```
**预期：** P99 < 1ms

#### TC-2：插件处理延迟分解

```promql
histogram_quantile(0.99, sum by(le, plugin_type) (
  rate(inference_extension_plugin_duration_seconds_bucket[5m])
))
```
**预期：** 各插件（queue-scorer、kv-cache-utilization-scorer、prefix-cache-scorer、no-hit-lru-scorer）P99 < 0.5ms

#### TC-3：EPP 请求吞吐量

```promql
sum(rate(inference_objective_request_total[5m]))
```

#### TC-4：各 Pod Token 生成速率

```promql
sum by(pod) (rate(vllm:generation_tokens_total[5m]))
```
**预期：** 两个 decode Pod 速率大致相等。

#### TC-5：EPP 前缀缓存索引大小

```promql
inference_extension_prefix_indexer_size
```
**预期：** 随时间单调递增。

#### TC-6：vLLM E2E 请求延迟 P90

```promql
histogram_quantile(0.90, sum by(le, pod) (
  rate(vllm:e2e_request_latency_seconds_bucket[5m])
))
```

#### TC-7：运行中请求数

```promql
inference_objective_running_requests
```

---

### 追踪测试（Jaeger）

#### TC-8：EPP Trace 验证

验证每个通过 EPP 的请求产生含 2 个 span 的 trace：

```bash
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

**预期输出：**
```
traceID=222f257fb8243b01  spans=2  duration=0.1ms
  - gateway.request
  - gateway.request_orchestration
```

#### TC-9：Trace 延迟与指标一致性验证

从两个来源对比 EPP 调度延迟，结果应一致：

**Prometheus：**
```promql
histogram_quantile(0.99, sum by(le) (
  rate(inference_extension_scheduler_e2e_duration_seconds_bucket[5m])
))
```

**Jaeger：** 选取一个 trace → 查看 `gateway.request_orchestration` span 的 Duration 字段。

#### TC-10：错误请求 Trace 验证

验证错误请求也会产生 trace：

```bash
kubectl port-forward -n llm-d svc/llm-d-epp 8081:80 &
curl -s -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"nonexistent","messages":[{"role":"user","content":"test"}],"max_tokens":5}'
# 然后在 Jaeger 中查找该失败请求的 trace
```

---

## Helm Values 叠加顺序

```
guides/recipes/router/base.values.yaml
  └── EPP 镜像、Envoy 代理默认配置

guides/optimized-baseline/router/optimized-baseline.values.yaml
  └── 4 插件评分：queue + kv-cache + prefix-cache + no-hit-lru

guides/recipes/router/features/monitoring.values.yaml
  └── EPP ServiceMonitor（Prometheus 抓取）

docs/monitoring/llm-d-full-demo/helm-values/tracing.values.yaml
  └── EPP OTLP tracing → http://otel-collector:4317（100% 采样）

docs/monitoring/llm-d-full-demo/helm-values/kind-overrides.values.yaml
  └── Kind 环境资源缩减（EPP/Envoy）
```

---

## 配置参考

### tracing.values.yaml

| 参数 | 值 | 说明 |
|---|---|---|
| `router.tracing.enabled` | `true` | 开启 EPP OTLP tracing |
| `router.tracing.otelExporterEndpoint` | `http://otel-collector:4317` | OTel Collector 地址 |
| `router.tracing.sampling.sampler` | `parentbased_traceidratio` | 采样器类型 |
| `router.tracing.sampling.samplerArg` | `1.0` | 100% 采样（开发环境；生产建议 `0.1`） |

### 模型服务器 OTEL 环境变量

| 变量 | 值 | 说明 |
|---|---|---|
| `OTEL_SERVICE_NAME` | `llm-d-model-server` | Jaeger 中显示的服务名 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | OTel Collector 地址 |
| `OTEL_TRACES_EXPORTER` | `otlp` | 导出协议 |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | 继承父 trace 的采样决定 |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | 100% 采样率 |

### OTel Collector 处理管道

```yaml
receivers:  otlp（gRPC :4317，HTTP :4318）
processors:
  - filter/drop-metrics-scraping   # 丢弃 /metrics 轮询产生的 span
  - batch（1024 spans，1s 超时）
exporters:  otlp/jaeger → jaeger-collector:4317
```

---

## GAIE v1.5.0 API 说明

GAIE v1.5.0 不再包含 `InferenceModel` CRD，已改为：

| CRD | 用途 |
|---|---|
| `InferencePool` | 定义 model server 后端池（通过标签选 Pod） |
| `InferenceObjective` | 定义请求优先级（用于流控） |
| `InferenceModelRewrite` | 定义模型名称重写规则 |
| `InferencePoolImport` | 跨命名空间池导入 |

---

## 清理

```bash
# 删除所有工作负载（OTel + Jaeger + 模型服务器 + EPP）
kubectl delete namespace llm-d

# 卸载监控栈
bash docs/monitoring/scripts/install-prometheus-grafana.sh --uninstall

# 删除 Kind 集群
kind delete cluster --name llm-d

# 停止所有端口转发
pkill -f "kubectl port-forward" 2>/dev/null || true
```

---

## 故障排查

### Jaeger 中没有 trace

1. 检查 OTel Collector 是否运行：`kubectl get pods -n llm-d -l app=otel-collector`
2. 检查 EPP tracing 是否启用：`kubectl get deploy llm-d-epp -n llm-d -o yaml | grep -A5 tracing`
3. 查看 OTel Collector 日志：`kubectl logs -n llm-d deploy/otel-collector`
4. 发送手动请求后等待 ~5 秒再查 Jaeger

### EPP Pod 启动即崩溃

在 Helm chart 安装之前，先执行 `--crds-only` 安装 Monitoring CRDs（第 3 步）。

### 模型服务器 Pod 卡在 `ImagePullBackOff`

```bash
kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.8.0-arm64 --name llm-d
```

### 流量生成器返回 404

EPP Service 的 HTTP 端口是 **80**（不是 8081）：
```bash
ROUTER_URL=http://llm-d-epp:80
```

### Prometheus 不抓取 EPP

```bash
kubectl get servicemonitor -n llm-d
kubectl port-forward -n llm-d svc/llm-d-epp 9090:9090
curl http://localhost:9090/metrics | grep inference_extension | head -5
```
