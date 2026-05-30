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

### 各组件职责说明

**`llm-d-epp` Pod — 路由核心（同一 Pod 内的 2 个容器）**

| 容器 | 职责 |
|---|---|
| **Envoy Proxy**（`:8081`） | 七层 HTTP 网关。接收所有入站请求，在转发之前通过 gRPC `ext_proc` 协议（`:9002`）调用 EPP 询问"该把这个请求发给哪个 Pod？"。收到 EPP 返回的目标 Pod IP 后，Envoy 直接将请求代理到该 Pod 并将响应流回客户端。 |
| **EPP — Endpoint Picker**（`:9002`） | 调度大脑。对每个请求运行 4 插件评分流水线来选出最优的 decode Pod。同时维护**前缀缓存索引**（详见下方 KV Cache 章节）。在 `:9090` 暴露 Prometheus 指标，并将 OTLP trace 发送到 OTel Collector。 |

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

第 2 步  Envoy → EPP ext_proc 调用（gRPC :9002）
         Envoy 在转发之前调用 EPP 的 gRPC 外部处理接口，
         传入请求头和请求体。EPP 运行 4 插件评分流水线：

         a. queue-scorer           读取各 Pod 实时队列深度
         b. kv-cache-scorer        读取各 Pod KV Cache 占用率
         c. prefix-cache-scorer    对提示词前缀做哈希 → 查询前缀缓存索引
                                   → 找到已有 KV Cache 的 Pod
         d. no-hit-lru-scorer      无前缀命中时的 LRU 兜底

         EPP 将获胜 Pod 的 IP 返回给 Envoy，并将本次请求
         记入前缀缓存索引（或更新已有条目）。

第 3 步  Envoy → decode Pod（:8000）
         Envoy 直接将请求转发到目标 Pod（绕过 kube-proxy 负载均衡），
         并将响应流回客户端。

第 4 步  decode Pod → OTel Collector（OTLP gRPC :4317）
         模型服务器 Pod 发送涵盖推理执行过程的 OTLP span。

第 5 步  EPP → OTel Collector（OTLP gRPC :4317）
         EPP 每个请求发送 2 个 span：
         - gateway.request               完整请求生命周期
         - gateway.request_orchestration  调度决策详情

第 6 步  OTel Collector 处理并转发
         过滤器丢弃 /metrics HTTP 轮询 span（降噪）。
         批处理器将剩余 span 打包 → 通过 OTLP 转发给 Jaeger。

第 7 步  Jaeger 存储并展示
         span 进入 Jaeger 的内存存储。
         通过 :16686 的 UI，可将 EPP 调度耗时与模型服务器执行耗时关联分析。
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
| `PodMonitor/decode` | `llm-d` | CR | Prometheus 抓取模型服务器指标（:8000）——来自 `guides/recipes/modelserver/components/monitoring/` |
| Prometheus（HTTPS/TLS） | `llm-d-monitoring` | StatefulSet | 指标存储 |
| Grafana | `llm-d-monitoring` | Deployment | 5 个预装 llm-d 仪表盘 |

### 可观测性覆盖范围

| 信号类型 | 工具 | 来源 | 数量 |
|---|---|---|---|
| **指标（Metrics）** | Prometheus + Grafana | EPP（ServiceMonitor）+ 模型服务器（PodMonitor） | 35+ EPP + 41 vLLM |
| **追踪（Traces）** | Jaeger + OTel Collector | EPP（`llm-d-router/epp`）+ 模型服务器 | 每请求 2 个 span |

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

模型服务器 manifest 中的五个 `OTEL_*` 环境变量将 inference-sim Pod 接入分布式追踪管道。每个变量对应 OpenTelemetry SDK 的一个标准配置项。

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

EPP 是 trace 的发起者。当 EPP 将请求路由到模型服务器 Pod 时，它会在 HTTP 请求中注入一个 W3C `traceparent` 头，携带根 trace ID 和"已采样"标志。模型服务器的 OTel SDK 读取该头部：

```
EPP（根 span 创建者）
  │  创建：gateway.request  [traceID=abc, spanID=001, sampled=true]
  │  注入：traceparent: 00-abc-001-01  到发往模型服务器的 HTTP 请求中
  │
  ▼
decode-0（子 span 创建者）
  OTel SDK 读取 traceparent 头
  parentbased 采样器：父 span 已采样 → 采样本 span
  创建：inference.request  [traceID=abc, spanID=002, parentSpanID=001]
  导出到 OTel Collector → Jaeger
```

最终效果：EPP 追踪的每个请求都会产生一个**具有相同 trace ID** 的模型服务器 span，Jaeger 因此能将它们拼合成一条完整的端到端 trace。如果 EPP 决定不采样某个请求（例如在 10% 采样率下），模型服务器也会丢弃其 span——不会出现孤立的 span 堆积。

**`OTEL_TRACES_SAMPLER_ARG=1.0`**

内层 `traceidratio` 采样器的比率参数，仅在无父 span 时生效（即模型服务器直接收到无 `traceparent` 头的请求）。`1.0` 表示 100%——所有根级 span 均被采样。在本 Demo 中，模型服务器 Pod 通常始终从 EPP 获得 traceparent，因此这条路径几乎不会触发。设为 `1.0` 是为了捕获绕过 EPP 直达模型服务器的请求（如健康检查或不带 trace 头的手动 curl 测试）。

**端到端 trace 拓扑：**

```
Jaeger 中的请求生命周期：

  traceID: abc123...
  │
  ├── [span 1]  gateway.request            service=llm-d-router/epp
  │     duration: ~0.2ms（EPP 调度耗时）
  │     attributes: pod.selected=decode-0, plugin.scores=...
  │     │
  │     └── [span 2]  inference.request    service=llm-d-model-server
  │           duration: ~50ms（模型推理耗时）
  │           attributes: pod=decode-0, model=Qwen2.5-0.5B-Instruct
```

两个服务，两个 span，同一个 trace ID——通过 `traceparent` 头自动关联。

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
  "https://github.com/llm-d/llm-d-router/config/crd"
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
