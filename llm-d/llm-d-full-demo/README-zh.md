# llm-d 完整栈可观测性演示（无 GPU 环境）

本指南在本地 Kind 集群上部署**完整的 llm-d 生产架构**，覆盖 llm-d 的全部关键组件：**Envoy** 数据面代理、**EPP / llm-d Router**（端点选择器）、**Inference Payload Processor（IPP，推理负载处理器）**、**InferencePool / InferenceObjective**、**inference-sim** 模型服务器、内嵌的 **KV-cache 索引器**、**Workload Variant Autoscaler（WVA，工作负载变体自动扩缩器）**，以及可选的 **P/D 分离** 路径。通过 **Prometheus**（指标）、**Grafana**（仪表盘）、**Jaeger**（分布式追踪）实现端到端全链路可观测性，无需 GPU。

每个请求在 Jaeger 中可通过**三个 trace 来源**观测——**Envoy** 代理、**IPP**、**EPP**——从而看到并测量网关的每一跳。Envoy 自身的 trace 包含 `ingress` span 以及**两次 `ext_proc` 调用**（对 IPP 和对 EPP）作为子 span，这正是证明请求确实按 `Envoy → IPP → EPP → 模型服务器` 流动的依据。

> [!IMPORTANT]
> 这是**三条独立的 trace**，并非一条拼接的 trace。EPP 与 IPP 各自开启自己的 trace（llm-d EPP 从 ext_proc 的 gRPC 流上下文开始 `gateway.request`，并把 `traceparent` 向**下游**注入到模型服务器，按设计不采纳 Envoy 的 ext_proc trace 上下文）。因此三者靠时间和 Envoy trace 中的 ext_proc span 关联，而非共享 trace ID。EPP→模型服务器这一跳**会**与一个能导出 trace 的模型服务器（真实 vLLM 配 `--otlp-traces-endpoint`）共享 trace ID；无 GPU 的 `inference-sim` 不导出 trace。该行为已在真实 Kind 集群上验证——见[实测追踪行为](#实测追踪行为)。

> Envoy 一直是本栈的一部分；它作为 sidecar 运行在 `llm-d-epp` Pod 内（standalone router chart 的 `proxy`）。本次更新将其显式化，把 IPP 作为 EPP 之前的第二个 `ext_proc` 过滤器加入，并启用 Envoy 自身的 OpenTelemetry tracing，使代理这一跳（及两次 ext_proc 调用）变得可观测。

> **English version:** [README.md](./README.md)

---

## 架构图

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Kind 集群（单节点，14 CPU / 23 GB）                                            │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  llm-d 命名空间                                                          │ │
│  │   客户端 │ HTTP :80                                                      │ │
│  │     ▼                                                                    │ │
│  │  ┌─────────────────────────────────────────────┐    ┌─────────────────┐ │ │
│  │  │  llm-d-epp Pod（2 个容器）                    │    │ payload-        │ │ │
│  │  │  ┌─────────────┐   gRPC    ┌─────────────┐ │ ext │ processor (IPP)  │ │ │
│  │  │  │   Envoy     │◄─────────►│    EPP      │ │proc │   :9004 (h2)     │ │ │
│  │  │  │   代理       │  :9002    │ （端点选择器）│ │◄───►│  body→header     │ │ │
│  │  │  │   :8081     │           │             │ │     │  X-Gateway-      │ │ │
│  │  │  └──┬───────┬──┘           └──────┬──────┘ │     │  Model-Name      │ │ │
│  │  └─────┼───────┼─────────────────────┼────────┘     └────────┬────────┘ │ │
│  │        │       │ 根 span + traceparent                       │ OTLP     │ │
│  │        │ 路由到 Pod                    │ OTLP traces           │          │ │
│  │        │              ┌────────────────▼───┐ ◄───────────────┘          │ │
│  │        │              │   OTel Collector   │──── OTLP ──► ┌───────────┐  │ │
│  │        │              │      :4317         │             │  Jaeger   │  │ │
│  │        ▼              └────────────────────┘             │  :16686   │  │ │
│  │   InferencePool "llm-d"          ▲ OTLP traces           └───────────┘  │ │
│  │   ┌──────────┐  ┌──────────┐     │                                      │ │
│  │   │ decode-0 │  │ decode-1 │─────┘  （inference-sim，port 8000）         │ │
│  │   └──────────┘  └──────────┘                                            │ │
│  │   WVA 控制器 ── 读取 vLLM/队列/KV 指标 ──► VariantAutoscaling             │ │
│  │             ── 输出 wva_desired_replicas ──► HPA ──► 扩缩 decode          │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  llm-d-monitoring 命名空间                                              │ │
│  │  Prometheus（HTTPS/TLS）◄── ServiceMonitor（EPP :9090）                  │ │
│  │                         ◄── PodMonitor（model servers :8000）           │ │
│  │  Grafana ◄── 5 个 llm-d 仪表盘                                          │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────┘
```

请求路径为：**客户端 → Envoy `:8081` → IPP `ext_proc` `:9004` → EPP `ext_proc` `:9002` → 选中的 decode Pod `:8000`。** Envoy 先调用 IPP（对请求做增强，例如把请求体的 `model` 字段写入 `X-Gateway-Model-Name`），再调用 EPP（选出目标 Pod），最后把请求转发给该 Pod。

## llm-d 组件覆盖

llm-d 的每个关键组件均有体现。“基线”组件已接入常驻演示；“可选”需要额外的文档步骤；“进阶”以带注意事项的 overlay 形式提供，位于 [`manifests/optional/`](./manifests/optional/)。

| 组件 | 仓库 / 来源 | 在本演示中 | 无 GPU 可用？ |
|---|---|---|---|
| **Inference Gateway（Envoy）** | 自管 sidecar（router chart `proxy`） | 基线——同时是 trace 根 | 是 |
| **EPP / llm-d Router** | `llm-d-router` | 基线 | 是 |
| **InferencePool / InferenceObjective** | GAIE + `llm-d.ai` CRDs | 基线 | 是 |
| **Inference Payload Processor（IPP）** | `llm-d-inference-payload-processor` | 基线（第 2 个 `ext_proc`） | 是 |
| **模型服务器（vLLM）** | `llm-d-inference-sim` | 基线 | 是（模拟） |
| **KV-cache 索引器** | `llm-d-kv-cache`（EPP 内库） | 基线为前缀缓存索引；精确 KV-events 路由为**进阶** | 前缀索引可；KV-events 需真实 vLLM |
| **Workload Variant Autoscaler（WVA）** | `llm-d-workload-variant-autoscaler` | 可选（第 9 步） | 是（饱和度扩缩） |
| **路由 sidecar / P/D 分离** | `llm-d-routing-sidecar` | 进阶 overlay | 仅拓扑（需 vLLM + NIXL） |
| **Prometheus / Grafana** | kube-prometheus-stack | 基线 | 是 |
| **Jaeger / OTel Collector** | 上游 | 基线 | 是 |

### 各组件职责说明

**`llm-d-epp` Pod — 路由核心（同一 Pod 内的 2 个容器）**

| 容器 | 职责 |
|---|---|
| **Envoy Proxy**（`:8081`） | 七层 HTTP 网关。接收所有入站请求，并按顺序调用两个 `ext_proc` 服务——先是 **IPP**（`:9004`）对请求增强，再是 **EPP**（`:9002`）询问"该把请求发给哪个 Pod？"。收到 EPP 返回的目标 Pod IP 后，直接代理到该 Pod 并将响应流回客户端。同时启用了 **OpenTelemetry tracing**：每个请求发出一个 `ingress` span，外加每次处理器调用一个 `ext_proc ... Process` 子 span，因此从代理侧可见并可测量 IPP 与 EPP 两跳。（Envoy 的 span 自成一条 trace；EPP/IPP 不采纳此上下文——见[实测追踪行为](#实测追踪行为)。） |
| **EPP — Endpoint Picker**（`:9002`） | 调度大脑。对每个请求运行 4 插件评分流水线来选出最优的 decode Pod。同时维护**前缀缓存索引**（详见下方 KV Cache 章节）。在 `:9090` 暴露 Prometheus 指标，并将 OTLP trace 发送到 OTel Collector。 |

**`payload-processor` Pod — Inference Payload Processor（IPP，`:9004`）**

一个独立的 Deployment，运行 Envoy `ext_proc` gRPC 服务（TLS/h2）。它位于 EPP **之前**，检查并改写请求负载。默认插件把请求体的 `model` 字段写入 `X-Gateway-Model-Name` 头（`body-field-to-header`）并解析基础模型（`base-model-to-header`），从而让网关在不解析请求体的情况下获得按模型路由的输入。它导出 OTLP trace，因此在每条请求 trace 中以 `llm-d-inference-payload-processor` span 出现。Envoy 以 `failure_mode_allow: true` 连接它，故 IPP 故障只会降级（无增强、无 IPP span）而不会中断请求。

**EPP 4 插件评分流水线（每个请求按顺序执行）：**

1. `queue-scorer` — 读取各 Pod 当前队列深度；优先选择有余量的 Pod。
2. `kv-cache-utilization-scorer` — 读取各 Pod 的 KV Cache 占用率；避免内存压力过大的 Pod。
3. `prefix-cache-scorer` — 对入站请求的提示词前缀做哈希，查询内存中的前缀缓存索引；优先选择已缓存该前缀的 Pod（更低的首 token 时延）。
4. `no-hit-lru-scorer` — 没有前缀命中时的兜底策略；在剩余候选 Pod 中按最近最少使用原则路由。

**`optimized-baseline-decode` Deployment（2 副本 = `decode-0`、`decode-1`）**

每个 Pod 运行 `inference-sim`，它是一个轻量级模拟器，在无需 GPU 的情况下模拟 vLLM 的 HTTP API 和指标接口。它：
- 在 `8000` 端口提供 `/v1/chat/completions` 接口。
- 在 `8000` 端口暴露与 vLLM 兼容的 Prometheus 指标（`vllm:generation_tokens_total`、`vllm:gpu_cache_usage_perc` 等）。
- 在内存中维护本地 **KV Cache**，并通过指标向 EPP 上报使用情况。
- 向 OTel Collector 发送 OTLP trace。

**`InferencePool / llm-d`** — Kubernetes 自定义资源，定义模型服务器后端池（通过标签 `llm-d.ai/guide=optimized-baseline` 选取 Pod）。EPP 监听此 CR 以维护各 Pod 的实时状态视图。

**`InferenceObjective / llm-d-standard`** — 定义流量的 QoS 优先级（本 Demo 为 `Priority=0`），用于 EPP 调度器的流控决策。

**`otel-collector`** — 集中式遥测汇聚点。在 `:4317` 接收来自 EPP 和 decode Pod 的 OTLP gRPC 数据，通过过滤处理器丢弃嘈杂的 `/metrics` HTTP 轮询 span，批量聚合后转发给 Jaeger。

**`jaeger`** — 一体化分布式追踪后端（内存存储，开发模式），在 `:16686` 提供查询 UI。

**`ServiceMonitor / llm-d-epp-monitor`** — Prometheus Operator 自定义资源，指示 Prometheus 每 30 秒抓取 EPP 的 `/metrics`（`:9090`）。

**`PodMonitor / llm-d-model-servers`** — Prometheus Operator 自定义资源，通过标签选择器指示 Prometheus 抓取每个 decode Pod 的 `/metrics`（`:8000`）。

**Prometheus**（HTTPS/TLS，位于 `llm-d-monitoring` 命名空间）— 抓取两个 Monitor 的数据，存储时序数据，提供 PromQL API。

**Grafana**（位于 `llm-d-monitoring` 命名空间）— 通过 5 个预置 llm-d 仪表盘可视化 Prometheus 数据。

---

## KV Cache 在架构中的位置

KV Cache 在本栈中存在于**两个不同层次**，且均可被观测：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  第一层 — Pod 本地 KV Cache（位于每个 decode Pod 内部）                         │
│                                                                             │
│   decode-0                              decode-1                            │
│  ┌──────────────────────┐            ┌──────────────────────┐               │
│  │  inference-sim / vLLM│            │  inference-sim / vLLM│               │
│  │                      │            │                      │               │
│  │  ┌────────────────┐  │            │  ┌────────────────┐  │               │
│  │  │  KV Cache      │  │            │  │  KV Cache      │  │               │
│  │  │（分页注意力机制） │  │            │  │（分页注意力机制） │  │               │
│  │  │  blocks: N     │  │            │  │  blocks: N     │  │               │
│  │  └───────┬────────┘  │            │  └───────┬────────┘  │               │
│  │          │ 指标上报   │            │          │ 指标上报   │               │
│  │  vllm:gpu_cache_      │            │  vllm:gpu_cache_      │               │
│  │  usage_perc           │            │  usage_perc           │               │
│  └──────────┼────────────┘            └──────────┼────────────┘               │
│             │                                    │                          │
│             └──────────────┬───────────────────┘                           │
│                            │ PodMonitor 抓取 → Prometheus → Grafana         │
└────────────────────────────┼────────────────────────────────────────────────┘
                             │
                             │ EPP 读取 KV Cache 使用率
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  第二层 — 跨 Pod 前缀缓存索引（位于 EPP 内部）                                  │
│                                                                             │
│   EPP 内存状态：                                                              │
│                                                                             │
│   前缀缓存索引（哈希映射）                                                     │
│   ┌────────────────────────────────────────────┐                            │
│   │  hash("What is llm-d?")   → decode-0       │                            │
│   │  hash("Explain KV cache") → decode-1       │                            │
│   │  hash("How does Envoy…")  → decode-0       │                            │
│   │  ...                                       │                            │
│   └────────────────────────────────────────────┘                            │
│   索引大小通过以下指标追踪：inference_extension_prefix_indexer_size             │
│                                                                             │
│   每个请求的评分流程：                                                         │
│                                                                             │
│   新请求到达                                                                  │
│        │                                                                    │
│        ▼                                                                    │
│   hash(提示词前缀)                                                            │
│        │                                                                    │
│        ├── 索引命中 ──► 路由到已有 KV Cache 的 Pod                            │
│        │               （缓存复用 → 更低首 token 时延 TTFT）                   │
│        │                                                                    │
│        └── 索引未命中 ──► kv-cache-utilization-scorer 选负载最低的 Pod         │
│                          → LRU 兜底路由 → EPP 将新前缀记入索引                 │
│                            供后续同前缀请求命中                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

**KV Cache 状态如何流入指标和路由决策：**

```
decode Pod KV Cache 占用率
        │
        │ /metrics（端口 8000）
        ▼
PodMonitor → Prometheus
        │
        │ EPP 通过 informer/metrics watch 读取 PromQL 数据
        ▼
EPP kv-cache-utilization-scorer
        │
        ├─ 规避过载 Pod（占用率高 → 降低优先级）
        └─ 与 prefix-cache-scorer 联合，优先选择
           「有余量且已缓存对应前缀」的 Pod
```

**在本 Demo 中观测 KV Cache 的位置：**

| 信号 | 查看位置 | 含义 |
|---|---|---|
| `vllm:gpu_cache_usage_perc{pod="decode-0"}` | Prometheus / Grafana "KV Cache" 仪表盘 | 各 Pod 当前 KV Cache 占用率 |
| `inference_extension_prefix_indexer_size` | Prometheus TC-5 查询 | EPP 已索引的唯一前缀数量——随流量多样性增长 |
| `inference_extension_plugin_duration_seconds{plugin_type="prefix-cache-scorer"}` | Prometheus TC-2 查询 | EPP 每请求在前缀缓存查找上花费的时间 |
| Jaeger `gateway.request_orchestration` span | Jaeger UI | 完整的调度决策详情，包括选择了哪个 Pod 及其原因 |

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

### 逐步解析：请求路径（控制面 + 数据面）

```
第 1 步  客户端 → Envoy（:80）
         HTTP POST /v1/chat/completions 请求到达 Envoy 的 80 端口。
         Envoy 开启一个 `ingress` span（属于它自己的 trace）。

第 2 步  Envoy → IPP ext_proc 调用（gRPC :9004，TLS/h2）
         Envoy 先调用 Inference Payload Processor，传入请求头和请求体。
         IPP 运行其请求插件：
         - body-field-to-header：把请求体 `model` 字段复制到
                                 X-Gateway-Model-Name 头
         - base-model-to-header：解析基础模型名
         IPP 把（可能改写后的）请求头返回给 Envoy。Envoy 把这次调用记为一个
         `ext_proc ... Process egress` 子 span。IPP 还会在一条**独立的 trace**
         中发出自己的 span（服务 llm-d-inference-payload-processor）。
         failure_mode_allow=true：IPP 不可用时，Envoy 跳过它继续处理。

第 3 步  Envoy → EPP ext_proc 调用（gRPC :9002）
         Envoy 接着调用 EPP（又一个 `ext_proc ... Process egress` 子 span），
         运行 4 插件评分流水线：

         a. queue-scorer           读取各 Pod 实时队列深度
         b. kv-cache-scorer        读取各 Pod KV Cache 占用率
         c. prefix-cache-scorer    对提示词前缀做哈希 → 查询前缀缓存索引
                                   → 找到已有 KV Cache 的 Pod
         d. no-hit-lru-scorer      无前缀命中时的 LRU 兜底

         EPP 将获胜 Pod 的 IP 返回给 Envoy 并记入前缀缓存索引。EPP 在它**自己的**
         trace 中发出 gateway.request + gateway.request_orchestration，并向
         **下游**注入一个全新的 traceparent 指向选中的 Pod。

第 4 步  Envoy → decode Pod（:8000）
         Envoy 直接将请求转发到目标 Pod（绕过 kube-proxy 负载均衡），
         并将响应流回客户端。

第 5 步  各组件 → OTel Collector（OTLP gRPC :4317）
         Envoy（ingress + 2 个 ext_proc span）、IPP（gateway.request）、
         EPP（gateway.request + gateway.request_orchestration）各自导出 span。
         它们是**三条独立的 trace**（不同 trace ID）。decode Pod（inference-sim）
         **不导出** trace。

第 6 步  OTel Collector 处理并转发
         过滤器丢弃 /metrics HTTP 轮询 span（降噪）。
         批处理器将剩余 span 打包 → 通过 OTLP 转发给 Jaeger。

第 7 步  Jaeger 存储并展示
         :16686 的 UI 显示三个 llm-d 服务（llm-d-envoy-proxy、
         llm-d-inference-payload-processor、llm-d-router/epp）。Envoy 的 trace
         是唯一能在一个视图里看到两次 ext_proc 跳的。详见"实测追踪行为"。
```

### 逐步解析：指标路径

```
每 30 秒：

  Prometheus → ServiceMonitor → 抓取 EPP :9090/metrics
                                  35+ inference_extension_* 计数器/直方图
                                  （调度器延迟、插件耗时、
                                    前缀索引大小、运行中请求数…）

  Prometheus → PodMonitor    → 抓取 decode-0 :8000/metrics
                             → 抓取 decode-1 :8000/metrics
                                  41 个 vllm:* 指标
                                  （gpu_cache_usage_perc、generation_tokens_total、
                                    e2e_request_latency_seconds、queue_size…）

  Grafana 轮询 Prometheus（PromQL）→ 实时渲染 5 个仪表盘
```

---

## 实测追踪行为

本节记录追踪流水线**实际**的行为，已在真实 Kind 集群上端到端验证（而非理想化版本）。

**你得到的：** Jaeger 中有三个 llm-d 服务，每个请求各自发出一条 trace：

| 服务 | 每请求 span | 说明 |
|---|---|---|
| `llm-d-envoy-proxy` | `ingress` + 2× `async ...ExternalProcessor.Process egress` | 两个 ext_proc span 即对 IPP 和对 EPP 的调用。这是唯一能同时看到两跳的 trace。 |
| `llm-d-inference-payload-processor` | `gateway.request` | IPP 的请求体/请求头处理。 |
| `llm-d-router/epp` | `gateway.request` + `gateway.request_orchestration` | EPP 路由 + 调度决策。 |
| `llm-d-model-server` | （无） | `inference-sim:v0.8.0` 不导出 trace。 |

**为什么不是一条拼接的 trace：**

- llm-d EPP 从 ext_proc 的 **gRPC 流上下文**开始 `gateway.request`（`llm-d-router` 的 `pkg/epp/handlers/server.go`），故自成一条 trace，从不采纳传入的 `traceparent`；它把全新的 `traceparent` 向**下游**注入到模型服务器。已验证：客户端发送 `traceparent` 也不会把 EPP（或 IPP）拉入该 trace。
- IPP 同样自成一条 trace。
- Envoy 的 OTLP tracing 为代理这一跳产生独立 trace。Envoy 仅在向**上游**转发时（即 ext_proc 过滤器之后）才写入 `traceparent`，所以 ext_proc 服务收不到 Envoy 的上下文。

**要做到单条拼接的 trace 需要什么**（超出本演示范围——需上游改动）：EPP 与 IPP 这两个 ext_proc 服务需从 ext_proc 请求头中提取传入的 `traceparent`，并将各自的 span 挂到其下。按设计**确实**生效的一处拼接是 **EPP → 模型服务器**（EPP 向下游注入），因此把 sim 换成能导出 trace 的 vLLM（`--otlp-traces-endpoint`）可得到 EPP+模型服务器的 2 服务 trace。

**实用建议：** 要跟踪单个请求，打开它的 **Envoy** trace——其中包含代理这一跳以及 IPP、EPP 两次 ext_proc 调用及耗时——再跳转到 IPP 和 EPP 服务查看各自内部细节。

---

## 组件说明

| 组件 | 命名空间 | 类型 | 描述 |
|---|---|---|---|
| `llm-d-epp` | `llm-d` | Pod（2 容器） | **Envoy 代理**（port 80→8081，trace 根，2× ext_proc）+ **EPP**（gRPC :9002） |
| `payload-processor` | `llm-d` | Deployment | **IPP**——Envoy ext_proc（:9004，TLS/h2）；请求体→请求头增强 |
| `InferencePool/llm-d` | `llm-d` | CR | 监听带 `llm-d.ai/guide=optimized-baseline` 标签的 Pod |
| `InferenceObjective/llm-d-standard` | `llm-d` | CR | Priority=0 流控目标 |
| `optimized-baseline-decode` | `llm-d` | Deployment（2 副本） | inference-sim 模拟 vLLM 模型服务器 |
| `otel-collector` | `llm-d` | Deployment | 接收 OTLP traces，过滤噪声，转发给 Jaeger |
| `jaeger` | `llm-d` | Deployment | Trace 存储 + UI（port 16686） |
| `ServiceMonitor/llm-d-epp-monitor` | `llm-d` | CR | Prometheus 抓取 EPP 指标（:9090） |
| `PodMonitor/decode` | `llm-d` | CR | Prometheus 抓取模型服务器指标（:8000）——来自 `guides/recipes/modelserver/components/monitoring/` |
| `VariantAutoscaling/optimized-baseline-decode` | `llm-d` | CR（可选） | **WVA** 目标；输出 `wva_desired_replicas` → HPA |
| Prometheus（HTTPS/TLS） | `llm-d-monitoring` | StatefulSet | 指标存储 |
| Grafana | `llm-d-monitoring` | Deployment | 5 个预装 llm-d 仪表盘 |

### 可观测性覆盖范围

| 信号类型 | 工具 | 来源 | 数量 |
|---|---|---|---|
| **指标（Metrics）** | Prometheus + Grafana | EPP（ServiceMonitor）+ 模型服务器（PodMonitor） | 35+ EPP + 41 vLLM |
| **追踪（Traces）** | Jaeger + OTel Collector | Envoy（`llm-d-envoy-proxy`）+ IPP（`llm-d-inference-payload-processor`）+ EPP（`llm-d-router/epp`）；模型服务器不导出（sim） | 每请求 3 个服务 / 3 条独立 trace |

---

## 组件内部机制解析

### 流量生成器（`03-traffic-generator.yaml`）

流量生成器是一个运行 Shell 脚本的 `curlimages/curl` 容器，脚本以 ConfigMap 方式挂载，完全自包含，不依赖任何额外工具。

**整体结构：**

```
ConfigMap: llm-d-traffic-gen-script
  └── generate.sh  （Shell 脚本，chmod 0755）
        │
        └── 挂载到 Deployment llm-d-traffic-gen 的 /scripts/generate.sh
              └── 以 /bin/sh /scripts/generate.sh 方式执行
```

**脚本逻辑（`generate.sh`）：**

```sh
# 1. 目标：EPP Service 地址 http://llm-d-epp:80（Envoy 代理，外部端口 80）
ROUTER_URL="http://llm-d-epp:80"
MODEL="Qwen/Qwen2.5-0.5B-Instruct"
INTERVAL=3   # 请求间隔（秒）

# 2. 固定提示词池 —— 8 条提示词，按轮询顺序循环发送
PROMPTS="What is Kubernetes?|Explain distributed inference.|
         How does KV cache work?|What is prefix caching?|..."

# 3. 主循环
while true; do
  req++
  prompt = PROMPTS[ (req-1) % 8 ]

  # 正常请求 —— POST 到 /v1/chat/completions
  curl -X POST $ROUTER_URL/v1/chat/completions \
    -d '{"model":"Qwen/...","messages":[...],"max_tokens":64}'

  # 每 8 个请求注入一次错误（使用不存在的模型名）
  # → 在 Jaeger 中生成失败 trace，并触发错误率指标
  if req % 8 == 0:
    curl -X POST $ROUTER_URL/v1/chat/completions \
      -d '{"model":"nonexistent-model",...}'

  sleep 3
done
```

**关键设计说明：**

| 设计选择 | 原因 |
|---|---|
| 轮询 8 条固定提示词 | 产生重复前缀模式，使 `prefix-cache-scorer` 能累积真实的缓存命中 |
| 每 8 个请求注入一次错误 | 填充错误率仪表盘和 Jaeger 错误 trace，但不会造成刷屏 |
| `max_tokens: 64` | 足够短以快速完成，足够长以产生有意义的 token 吞吐量指标 |
| 发送到 `:80`（而非 `:8081`） | `:80` 是 EPP Service 的外部端口，映射到 Pod 内 Envoy 的 `:8081` |
| 3 秒间隔 | 产生约 20 req/min，在 Kind 集群内提供稳定信号，不造成过载 |

---

### PodMonitor——内部工作原理

本 Demo 复用了已有的 recipe component：`guides/recipes/modelserver/components/monitoring/`，通过以下命令应用：

```bash
kubectl apply -k guides/recipes/modelserver/components/monitoring/ -n llm-d
```

**它创建的 CR：**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: decode
  namespace: llm-d
spec:
  selector:
    matchLabels:
      llm-d.ai/role: decode      # ← 所有 decode Pod 都带有此标签
  podMetricsEndpoints:
  - port: modelserver            # ← Pod 上的命名端口（containerPort 8000）
    path: /metrics
    interval: 30s
```

本 Demo 的 decode Pod 同时携带 `llm-d.ai/role: decode` 和 `llm-d.ai/guide: optimized-baseline` 两个标签，因此 recipe 中基于 role 的 selector 无需任何修改即可生效。

**Controller 是谁？**

`PodMonitor` 是 **Prometheus Operator** 拥有的 CRD（随 `kube-prometheus-stack` Helm chart 一起安装）。Prometheus Operator 是一个控制器，它监听 PodMonitor 和 ServiceMonitor CR，并动态重写 Prometheus 的抓取配置——你无需手动编辑 `prometheus.yml`。

```
┌──────────────────────────────────────────────────────────────────────────┐
│  llm-d-monitoring 命名空间                                                │
│                                                                          │
│  Prometheus Operator（控制器）                                            │
│       │                                                                  │
│       │  list/watch 监听                                                  │
│       ▼                                                                  │
│  PodMonitor/llm-d-model-servers  ──────────────────────────────────────► │
│       │                          转译为 scrape_config                    │
│       ▼                                                                  │
│  Prometheus StatefulSet                                                  │
│       │  （配置热重载：scrape_configs 中新增 decode pod 抓取目标）            │
│       │                                                                  │
│       │  HTTP GET /metrics，每 15 秒一次                                  │
│       ▼                                                                  │
│  decode-0 :8000/metrics                                                  │
│  decode-1 :8000/metrics                                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

**Prometheus 如何找到正确的 Pod：**

1. PodMonitor 指定 `selector.matchLabels: llm-d.ai/guide: optimized-baseline`。
2. Prometheus Operator 列出集群中所有匹配该标签的 Pod。
3. 对每个匹配的 Pod，解析命名端口 `modelserver` → `containerPort: 8000`。
4. Prometheus 直接抓取 `http://<pod-ip>:8000/metrics`（绕过 Service/kube-proxy）。

**为什么用命名端口而不是端口号？**

使用 `port: modelserver`（名称，而非 `8000`）将 Monitor 与实际端口号解耦。若端口号将来发生变化，只需更新容器定义，PodMonitor 无需改动。

**跨命名空间抓取：**

PodMonitor 位于 `llm-d` 命名空间，而 Prometheus 位于 `llm-d-monitoring`。kube-prometheus-stack Helm chart 将 Prometheus 配置为 `podMonitorNamespaceSelector: {}`（匹配所有命名空间），因此可以跨命名空间发现 PodMonitor。

---

### InferenceObjective（`02-inferenceobjective.yaml`）——作用与控制者

**CR 内容：**

```yaml
apiVersion: inference.networking.x-k8s.io/v1alpha2
kind: InferenceObjective
metadata:
  name: llm-d-standard
  namespace: llm-d
spec:
  poolRef:
    name: llm-d        # ← 引用 Helm chart 创建的 InferencePool
  priority: 0          # ← 调度优先级（0 = 标准流量；数值越高越优先）
```

**它的作用：**

`InferenceObjective` 是 [Gateway API Inference Extension（GAIE）](https://gateway-api-inference-extension.sigs.k8s.io/) 项目中的流控策略对象。它为给定 InferencePool 的流量附加一个**优先级**，EPP 在负载下处理排队请求时会读取该优先级：

- **`priority: 0`** — 标准流量；当池处于压力下时视为尽力而为（best-effort）。
- 更高的值（如 `priority: 10`）— 优先级更高的流量，在 `queue-scorer` 决策中获得倾斜。

本 Demo 中只有一个优先级为 0 的 Objective，所有流量一视同仁。但该对象仍是必须的，因为 EPP 的调度 API 要求每个 InferencePool 至少绑定一个 InferenceObjective。

**Controller 是谁？**

> **简短回答：EPP 本身就是控制器。**

这是本 Demo 与独立 GAIE 部署的关键架构差异：

```
标准 GAIE 部署：
  GAIE controller（独立进程）──reconcile──► InferencePool、InferenceObjective
  EPP（独立进程）             ──读取────────► InferencePool status

llm-d Router 部署（本 Demo）：
  EPP Pod ──────────────────────────────────► 直接 watch InferencePool，
                                               读取 InferenceObjective，
                                               无需独立 GAIE 控制器
```

llm-d EPP 将 InferencePool/InferenceObjective 的控制器逻辑直接内嵌其中。EPP 启动后会：
1. List/Watch 本命名空间的 `InferencePool` 对象。
2. List/Watch 引用这些 Pool 的 `InferenceObjective` 对象。
3. List/Watch 各 Pool 选择器匹配的 Pod。
4. 构建内部状态表（Pod 健康状况、队列深度、KV Cache 状态）。
5. 在 `queue-scorer` 插件的权重逻辑中使用 InferenceObjective 的 `priority` 字段。

---

### 模型服务器 OpenTelemetry 配置（`01-model-servers.yaml`）

> [!NOTE]
> 已在真实集群验证：`llm-d-inference-sim:v0.8.0` **不会**响应这些 `OTEL_*` 变量——Jaeger 中从未出现 `llm-d-model-server` 服务。保留这些变量是因为它们本身正确且具前瞻性：一个遵循这些变量的真实 vLLM（或未来的 sim 版本）会导出一个推理 span，并接入 EPP 向下游传播的 trace。下文描述的是这一**预期**行为。

模型服务器 manifest 中的五个 `OTEL_*` 环境变量旨在将模型服务器 Pod 接入分布式追踪管道。每个变量对应 OpenTelemetry SDK 的一个标准配置项。

```yaml
# OpenTelemetry 分布式追踪
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

**逐变量说明：**

**`OTEL_SERVICE_NAME=llm-d-model-server`**

该服务在追踪后端中的逻辑名称。Jaeger 将其用作每个 span 上 `service.name` 资源属性的值。在 Jaeger UI 中，这正是你在 **Service** 下拉框中选择的名称，用来过滤 trace。`decode-0` 和 `decode-1` 两个 Pod 共享同一个服务名；Jaeger 通过 OTel SDK 自动注入的 `k8s.pod.name` 属性来区分各个 Pod。

**`OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`**

导出 span 的目标地址。`otel-collector` 通过 Kubernetes 集群内 DNS 解析为同命名空间的 OTel Collector Service。端口 `4317` 是标准的 gRPC OTLP 接收端口。OTel SDK 会与此端点建立持久 gRPC 连接并以流式方式传输 span 数据，避免每次请求的 TCP 握手开销。

> 此处使用 `http://`（而非 `https://`）是为本地 Kind 集群特意设计的。生产环境应使用双向 TLS。

**`OTEL_TRACES_EXPORTER=otlp`**

从 SDK 的导出器注册表中选择 OTLP 导出器（其他选项包括 `zipkin`、`jaeger`、`console`）。`otlp` 使用 OpenTelemetry Protocol——OTel Collector 原生支持的厂商中立的线上格式。通过先导出到 Collector 再转发给 Jaeger，在不修改任何应用代码的情况下获得处理层（过滤、批量、尾部采样）的能力。

**`OTEL_TRACES_SAMPLER=parentbased_traceidratio`**

这是一个**复合采样器**，也是五个变量中最重要的一个。它将两种采样策略组合在一起：

```
parentbased_traceidratio
│
├── 外层：parentbased（基于父 span）
│     检查入站请求中是否携带 W3C traceparent 头。
│     ├── 有头部，父 span 已采样    → 采样本 span（继承）
│     ├── 有头部，父 span 未采样    → 丢弃本 span（继承）
│     └── 无头部（根 span）        → 交由内层采样器决定 ▼
│
└── 内层：traceidratio（基于 Trace ID 比率）
      根据 trace ID 哈希值确定性地按比率采样。
      比率由 OTEL_TRACES_SAMPLER_ARG 设置（1.0 = 根 span 始终采样）。
```

**在 llm-d 流程中的重要性：**

**EPP 是路由路径的 trace 发起者**（这是 `llm-d-router` 的设计）。每个请求它从 ext_proc 的 gRPC 流开始 `gateway.request`——**不**读取传入的 `traceparent`——随后把一个全新的 `traceparent` 向**下游**注入到选中的模型服务器。因此 EPP 的 trace 旨在延伸到模型服务器，而非回连到 Envoy：

```
EPP（路由 trace 的根 span 创建者）
  │  创建：gateway.request  [traceID=abc, spanID=001]
  │  注入：traceparent: 00-abc-001-01  到转发给模型服务器的请求中
  │
  ▼
decode-0（本应成为子 span 的一跳）
  若模型服务器导出 trace（真实 vLLM 配 --otlp-traces-endpoint），
  其 OTel SDK 读取 traceparent → 在 traceID=abc 下生成推理 span。
  无 GPU 的 inference-sim 不导出 trace，因此该子 span 从不出现。
```

这就是为什么 EPP 与一个能导出 trace 的模型服务器共享 trace ID，而 **Envoy 与 IPP 各自产生独立的 trace**——Envoy 在自己的 trace 上开启 `ingress` 与两个 `ext_proc` 客户端 span，IPP 在自己的 trace 上开启 `gateway.request`。这三者互不采纳彼此的上下文。下方的 `OTEL_TRACES_SAMPLER_ARG=1.0` 作用于各自 trace 的根。

**`OTEL_TRACES_SAMPLER_ARG=1.0`**

内层 `traceidratio` 采样器的比率参数，仅在无父 span 时生效（即模型服务器直接收到无 `traceparent` 头的请求）。`1.0` 表示 100%——所有根级 span 均被采样。在本 Demo 中，模型服务器 Pod 通常始终从 EPP 获得 traceparent，因此这条路径几乎不会触发。设为 `1.0` 是为了捕获绕过 EPP 直达模型服务器的请求（如健康检查或不带 trace 头的手动 curl 测试）。

**端到端 trace 拓扑：**

```
Jaeger 中每个请求是三条独立 trace（已在真实集群验证）：

  Trace A  service=llm-d-envoy-proxy
    └── ingress                                   （代理这一跳）
        ├── async ...ExternalProcessor.Process egress   （对 IPP 的 ext_proc 调用）
        └── async ...ExternalProcessor.Process egress   （对 EPP 的 ext_proc 调用）

  Trace B  service=llm-d-inference-payload-processor
    └── gateway.request                           （IPP 请求体/请求头处理）

  Trace C  service=llm-d-router/epp
    ├── gateway.request                           （完整请求生命周期）
    └── gateway.request_orchestration             （EPP 调度详情）
    （若模型服务器导出 trace 则会延伸过去；sim 不导出）
```

三个服务，三个 trace ID。Trace A（Envoy）是唯一能同时看到两次 ext_proc 跳的视图，也是实践中查看并测量单个请求 IPP → EPP 顺序的方式。

---

### GAIE CRDs——谁来 reconcile？

**第 3 步安装的 CRDs：**

```bash
kubectl apply -k "https://github.com/llm-d/llm-d-router/config/crd"
```

该 kustomization 拉取两个来源，一次性注册所有必要的 CRD：

| CRD | API Group | 用途 |
|---|---|---|
| `InferencePool` | `inference.networking.k8s.io` | 定义模型服务器 Pod 池（标签选择器 + 失败模式） |
| `InferenceObjective` | `llm-d.ai` | 为 Pool 附加优先级/流控策略 |
| `InferenceModelRewrite` | `llm-d.ai` | （本 Demo 未使用）模型名称重写规则 |

> **为什么是 `llm-d.ai` 而不是 `inference.networking.x-k8s.io`？** 2026 年 5 月，llm-d 将
> `InferenceObjective` 和 `InferenceModelRewrite` 迁移到了自己的 `llm-d.ai` API group
>（PR [#1169](https://github.com/llm-d/llm-d-router/pull/1169)）。
> 旧的 `inference.networking.x-k8s.io` CRD 不再由统一的 `llm-d-router/config/crd` kustomization 安装。
> EPP 仍接受旧 group 下的对象，但会打 deprecation 日志。

**为什么安装 CRDs 却不安装 GAIE 控制器？**

CRD 只是**Schema 注册**——它告诉 Kubernetes API Server "这种类型的对象是合法的"。安装 CRD 本身不会启动任何控制器。只有先注册了 `InferenceObjective` CRD，`kubectl apply -f 02-inferenceobjective.yaml` 才不会返回 `no matches for kind "InferenceObjective"` 错误。

在标准 GAIE 部署中，你还需要部署 `inference-extension-controller` Pod 来 reconcile InferencePool 的 status。本 Demo **不安装**这个控制器，因为 llm-d EPP 已经承担了它的所有职责：

```
┌──────────────────────────────────────────────────────────────────────────┐
│  GAIE 控制器通常做的事              本 Demo 由谁来做                        │
├──────────────────────────────────────────────────────────────────────────┤
│  Watch InferencePool，发现成员 Pod  EPP（内置）                            │
│  Watch Pod Ready/NotReady 事件      EPP（内置）                            │
│  更新 InferencePool .status         EPP（内置）                            │
│  读取 InferenceObjective 优先级     EPP queue-scorer 插件                  │
│  负载下执行流控                      EPP 调度流水线                         │
└──────────────────────────────────────────────────────────────────────────┘
```

之所以从上游 GAIE 仓库单独安装 CRDs（而不是打包进 Helm chart），是因为 CRDs 是集群级别的资源——管理单一命名空间的 Helm chart 不应拥有或升级它们，否则会产生所有权冲突。单独安装确保了：安装顺序正确（CRDs 先于 Chart 对象），以及多个 Helm release 共用同一套 CRDs 时不产生冲突。

---

## 前提条件

- **Kind** v0.29+、**Docker Desktop**（已分配 14+ CPU、20+ GB RAM）
- **kubectl**、**Helm** v3.10+
- **jq**、**python3**
- 已克隆 llm-d 仓库：`git clone https://github.com/llm-d/llm-d.git && cd llm-d`

---

## 安装步骤

先设置版本变量——后续多个步骤都会用到：

```bash
export GAIE_VERSION=v1.5.0
export ROUTER_CHART_VERSION=v0
```

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

# 3b. llm-d router CRDs——一次性安装 GAIE CRDs（InferencePool）
#     和 llm-d.ai CRDs（InferenceObjective、InferenceModelRewrite）
kubectl apply -k \
  "https://github.com/llm-d/llm-d-router/config/crd?ref=${ROUTER_CHART_VERSION}"
```

> **为什么用 `llm-d-router/config/crd` 而不是上游 GAIE 仓库？**
> 2026 年 5 月，llm-d 将 `InferenceObjective` 迁移到了自己的 `llm-d.ai/v1alpha2` API group。
> `llm-d-router/config/crd` 的 kustomization 一次性安装所有必要的 CRD：
> 上游 GAIE CRD（`inference.networking.k8s.io` InferencePool）**以及**
> llm-d 自有 CRD（`llm-d.ai` InferenceObjective、InferenceModelRewrite）。

验证：
```bash
kubectl get crd | grep -E "inferencep|monitoring.coreos|llm-d.ai"
# 预期输出（3 个 inference CRD）：
# inferencemodelrewrites.llm-d.ai              ...
# inferenceobjectives.llm-d.ai                 ...
# inferencepools.inference.networking.k8s.io   ...
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
  -f docs/monitoring/llm-d-full-demo/helm-values/proxy-tracing-ipp.values.yaml \
  -n llm-d \
  --version ${ROUTER_CHART_VERSION}
```

- `tracing.values.yaml` 配置 **EPP** 将 trace 发送到 `http://otel-collector:4317`。
- `proxy-tracing-ipp.values.yaml` 覆盖 chart 的 **Envoy** 配置：(a) 把 **IPP** 作为 EPP 之前的第二个 `ext_proc` 过滤器加入；(b) 让 Envoy 成为 **OpenTelemetry trace 根**；(c) 新增 `ipp_ext_proc` 与 `otel_collector` 两个 cluster。该文件是 chart Envoy 预设的逐字拷贝加上述改动；升级 `ROUTER_CHART_VERSION` 时需重新同步。

> Envoy 会在 IPP（第 6b 步）存在之前就引用 `payload-processor` Service。由于 IPP 过滤器配置了 `failure_mode_allow: true`，期间请求仍能成功——只是在 IPP 运行前不产生 IPP span。

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

### 第 6b 步：部署 Inference Payload Processor（IPP）

IPP 是 Envoy 链路中的第二个 `ext_proc` 服务（已在第 5 步接好）。现在部署该工作负载，使 Envoy 的 `ipp_ext_proc` cluster 变为健康并开始产生 IPP span。

从 [`llm-d-inference-payload-processor`](https://github.com/llm-d/llm-d-inference-payload-processor) 仓库的 chart 安装：

```bash
git clone https://github.com/llm-d/llm-d-inference-payload-processor.git /tmp/ipp

helm install payload-processor /tmp/ipp/config/charts/payload-processor \
  -f docs/monitoring/llm-d-full-demo/helm-values/ipp.values.yaml \
  -n llm-d
```

> 若你的环境能访问已发布的 OCI chart，也可改用
> `helm install payload-processor oci://ghcr.io/llm-d/charts/payload-processor --version v0 -f ... -n llm-d`。

`ipp.values.yaml` 设置 `provider.name=none`（chart 只部署 IPP 工作负载——Deployment、Service、ConfigMap、RBAC；Envoy 接线在 router 侧完成），并启用到 `http://otel-collector:4317` 的 OTLP tracing。

> [!NOTE]
> 镜像 `ghcr.io/llm-d/llm-d-inference-payload-processor:main` 目前**无法匿名拉取**（403）。若 Pod 出现 `ImagePullBackOff`，请从克隆的仓库本地构建并加载进 Kind。Apple Silicon 上按 arm64 构建：
> ```bash
> docker run --rm -v /tmp/ipp:/src -w /src/cmd -e CGO_ENABLED=0 -e GOOS=linux -e GOARCH=arm64 \
>   golang:1.25 go build -o /src/payload-processor-bin .
> printf 'FROM gcr.io/distroless/static:nonroot\nCOPY payload-processor-bin /payload-processor\nENTRYPOINT ["/payload-processor"]\n' > /tmp/ipp/Dockerfile.local
> docker build --platform linux/arm64 -f /tmp/ipp/Dockerfile.local -t ghcr.io/llm-d/llm-d-inference-payload-processor:main /tmp/ipp
> kind load docker-image ghcr.io/llm-d/llm-d-inference-payload-processor:main --name llm-d
> kubectl delete pod -n llm-d -l app=payload-processor   # 让其在已加载镜像上重启
> ```
> （x86_64 去掉 `--platform`/`GOARCH=arm64`。）

验证：
```bash
kubectl get deploy,svc -n llm-d | grep payload-processor
# deployment.apps/payload-processor   1/1   1   1
# service/payload-processor   ClusterIP   ...   9004/TCP
```

---

### 第 7 步：部署模型服务器

```bash
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/01-model-servers.yaml
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/02-inferenceobjective.yaml

# PodMonitor —— 复用已有的 recipe component（通过 llm-d.ai/role=decode 标签选取 Pod）
kubectl apply -k guides/recipes/modelserver/components/monitoring/ -n llm-d
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
kubectl wait --for=condition=Ready pods --all -n llm-d --timeout=120s
kubectl get pods -n llm-d
```

预期输出：
```
NAME                                        READY   STATUS
jaeger-xxx                                  1/1     Running
llm-d-epp-xxx                               2/2     Running
optimized-baseline-decode-xxx (×2)          1/1     Running
otel-collector-xxx                          1/1     Running
```

---

### 第 8 步：部署流量生成器

```bash
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/03-traffic-generator.yaml
```

```bash
kubectl logs -n llm-d deploy/llm-d-traffic-gen -f
# req=5 [200] Describe transformer architecture.
# req=6 [200] How does load balancing work?
```

---

### 第 9 步：Workload Variant Autoscaler（WVA）——可选

WVA 是面向推理模型服务器的全局自动扩缩器。它监听 decode Deployment，从 Prometheus 读取 vLLM/队列/KV-cache 指标，计算期望副本数，并以 Prometheus 指标 `wva_desired_replicas` 输出。标准 HPA 消费该指标驱动 scale 子资源。在无 GPU 的 Kind 上以**饱和度扩缩**模式（KV-cache + 队列深度）运行；GPU 成本优化仅作演示。

WVA 的组成比演示其余部分更复杂，请从 [`llm-d-workload-variant-autoscaler`](https://github.com/llm-d/llm-d-workload-variant-autoscaler) 仓库安装其控制器、CRD 和 service-class/accelerator ConfigMap（`kind-emulator` 配置专为此场景设计），然后应用本演示的衔接清单：

```bash
# 9a. 控制器 + CRD + 配置（来自 WVA 仓库；kind-emulator 配置）
ENVIRONMENT=kind-emulator ./deploy/install.sh        # 或：kubectl apply -k config/overlays/cluster-scoped/kubernetes

# 9b. 让 WVA 控制器指向本演示的 Prometheus
#     （其 manager ConfigMap 的 PROMETHEUS_BASE_URL → llm-d-monitoring 的 Prometheus svc）

# 9c. 把 wva_desired_replicas 作为外部指标暴露给 HPA
#     安装 prometheus-adapter（或 KEDA）并映射该序列——参见 WVA 仓库

# 9d. 为 decode 池应用 VariantAutoscaling + HPA
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/05-variantautoscaling.yaml
kubectl apply -f docs/monitoring/llm-d-full-demo/manifests/06-hpa.yaml
```

验证：
```bash
kubectl get variantautoscaling,hpa -n llm-d
# variantautoscaling.llmd.ai/optimized-baseline-decode   optimized-baseline-decode   1   4
# horizontalpodautoscaler.autoscaling/optimized-baseline-decode-hpa  Deployment/optimized-baseline-decode
```

提高流量（降低生成器的 `INTERVAL`，或循环 `curl`），观察 `wva_desired_replicas` 上升时 decode 副本数随之变化。

---

## 进阶层（可选）

其余组件——**P/D 分离**（配合 `llm-d-routing-sidecar`）与**精确前缀缓存 / KV-cache 感知路由**（由 ZMQ KV-events 喂养的 EPP 内嵌 KV-cache 索引器）——以带注意事项的 overlay 形式提供，位于 [`manifests/optional/`](./manifests/optional/)。它们在模拟器上部署拓扑与控制/可观测性平面，但数据面 KV 机制（真实 NIXL 传输、真实 KV-events、分词）需要 CPU/GPU 版 vLLM。详见 [`manifests/optional/README.md`](./manifests/optional/README.md)：包含具体步骤、对应的 llm-d 官方 guide 引用，以及无 GPU 注意事项。

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

Jaeger UI 的 **Service** 下拉框列出三个 llm-d 服务：
`llm-d-envoy-proxy`（Envoy）、`llm-d-inference-payload-processor`（IPP）、
`llm-d-router/epp`（EPP）。每个请求**每个服务各产生一条 trace**（它们不会拼接在一起——见[实测追踪行为](#实测追踪行为)）。

1. **Service** → 选 `llm-d-envoy-proxy`，**Find Traces**，打开一条。它包含：
   - `ingress`——代理这一跳
   - 两个 `async ...ExternalProcessor.Process egress` span——对 IPP 和对 EPP 的调用。
     这是唯一能在一个视图里看到单个请求两次 ext_proc 跳的地方。
2. **Service** → `llm-d-inference-payload-processor` → IPP 的 `gateway.request` span。
3. **Service** → `llm-d-router/epp` → `gateway.request` + `gateway.request_orchestration`（调度决策）。
4. `llm-d-model-server` 不存在——无 GPU 的 `inference-sim` 不导出 trace。

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

#### TC-11：三个 trace 来源 + Envoy 含两次 ext_proc 跳

验证三个 llm-d 服务都出现，且 Envoy 的 trace 含两次 `ext_proc` 调用（IPP 与 EPP）。

```bash
# 三个服务都应列出
curl -s "http://localhost:16686/api/services" | python3 -c "import sys,json; print(sorted(json.load(sys.stdin)['data']))"
# 预期包含：llm-d-envoy-proxy、llm-d-inference-payload-processor、llm-d-router/epp

# Envoy 的 trace = ingress + 两个 ext_proc 'Process egress' span
curl -s "http://localhost:16686/api/traces?service=llm-d-envoy-proxy&limit=3&lookback=1h" | \
  python3 -c "
import sys, json
for t in (json.load(sys.stdin).get('data') or []):
    ops = [s['operationName'] for s in t.get('spans', [])]
    n_extproc = sum('ExternalProcessor.Process' in o for o in ops)
    print(f'traceID={t[\"traceID\"][:16]}  spans={len(ops)}  ext_proc_calls={n_extproc}')
"
```

**预期：** 每条 Envoy trace 有 3 个 span 且 `ext_proc_calls=2`（IPP 与 EPP 调用）。它们与 IPP、EPP 各自的 trace 是**独立**的——不会产生单条 4 服务 trace（见[实测追踪行为](#实测追踪行为)）。若缺少 IPP 服务，确认第 6b 步已部署且 `ipp_ext_proc` cluster 健康（端口转发 Envoy admin 后 `curl -s localhost:19000/clusters | grep ipp_ext_proc`）。

#### TC-12：IPP 请求头增强

确认 IPP 处理了每个请求体（把 `model` 提取到 `X-Gateway-Model-Name`）：

```bash
kubectl logs -n llm-d deploy/payload-processor | grep -iE "parsed field from body|base model header" | tail
```

**预期**（已在真实集群验证）——每个请求一对：
```
... "msg":"parsed field from body","field":"model","value":"Qwen/Qwen2.5-0.5B-Instruct"
... "msg":"updated base model header based on the request target model","targetModel":"Qwen/Qwen2.5-0.5B-Instruct"
```

#### TC-13：WVA 期望副本数（可选）

若已安装 WVA（第 9 步），确认它输出扩缩信号：

```promql
wva_desired_replicas{variant_name="optimized-baseline-decode", exported_namespace="llm-d"}
```
**预期：** 值 ≥ 1 且随负载上升；HPA 跟踪该值。

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

docs/monitoring/llm-d-full-demo/helm-values/proxy-tracing-ipp.values.yaml
  └── 完整 Envoy 配置覆盖：IPP ext_proc 过滤器（在 EPP 之前）、
      OpenTelemetry trace 根、ipp_ext_proc + otel_collector 两个 cluster

docs/monitoring/llm-d-full-demo/helm-values/ipp.values.yaml   （payload-processor chart）
  └── 仅部署 IPP 工作负载（provider.name=none）+ OTLP tracing
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
| `OTEL_SERVICE_NAME` | `llm-d-model-server` | Jaeger UI Service 下拉框中显示的服务名 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | gRPC OTLP 目标地址（集群内 DNS，端口 4317） |
| `OTEL_TRACES_EXPORTER` | `otlp` | 线上格式：OpenTelemetry Protocol（厂商中立） |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | 复合采样器：继承父 span 决策；根 span 回退到比率采样 |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | 根 span 比率（100%）；实际上模型服务器 Pod 始终拥有 EPP 父 span |

详细说明及 trace 传播流程，见[模型服务器 OpenTelemetry 配置](#模型服务器-opentelemetry-配置01-model-serversyaml)章节。

### OTel Collector 处理管道

```yaml
receivers:  otlp（gRPC :4317，HTTP :4318）
processors:
  - filter/drop-metrics-scraping   # 丢弃 /metrics HTTP 轮询产生的 span（Prometheus 噪声）
  - batch（1024 spans，1s 超时）   # 批量缓冲后转发，降低 Jaeger 写入压力
exporters:  otlp/jaeger → jaeger-collector:4317
```

filter 处理器至关重要：Prometheus 每 15–30 秒抓取一次 `/metrics`，若不在此丢弃，这些 HTTP 请求每分钟会在 Jaeger 中产生数百个低价值 span。

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
# 卸载 helm release（router + IPP）
helm uninstall llm-d -n llm-d
helm uninstall payload-processor -n llm-d

# 若安装了 WVA（第 9 步）——在 WVA 仓库检出目录中：
#   ENVIRONMENT=kind-emulator ./deploy/install.sh --uninstall
#   （或：kubectl delete -k config/overlays/cluster-scoped/kubernetes）

# 删除其余所有工作负载（OTel + Jaeger + 模型服务器 + VA/HPA）
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
