# 设计：llm-d 的价值归因（token 经济学演示）

English version: [`design.md`](design.md).

## 1. 目标

在真实的 llm-d 技术栈上，展示 Tokenomics Foundation 的
[Value Attribution Data Architecture](https://www.tokeneconomics.com/projects/value-attribution-data-architecture/)
（v0.1.8，下称"论文"）所提出的完整链路：

```
Cost and Usage  ->  Telemetry  ->  Task  ->  Outcome  ->  Value
(the GPU bill)     (who used it)  (work)    (verified)   (worth)
```

并用它来回答我们在 KubeCon NA 2026 演讲（"Seeing Through the
Stack"）中未能继续深入的问题。那次演讲借助 OpenCost 做到了**每 token 成本**。本
演示再往前推进三层：**每个合格任务的成本（CPQT）**、**每个合格结果的成本
（CPQO）**以及**价值**，所用的仍是同一个 KubeCon 事故（
`prefix-cache-scorer` 的权重从 3 改成了 0）。

非目标：生产级流水线、财务级账单，或新的上游 API。
所有内容都在一台 DGX Spark 上运行，不需要 Kubernetes，且只使用 Python 标准库。

## 2. 需求

| # | 需求 | 演示如何满足 |
|---|---|---|
| R1 | 用共享的键（而非猜测）把 GPU 开销与业务结果关联起来 | 每次模型调用都带有 `focus.workload.id` / `focus.task.id` / `focus.outcome.id`，并按 `trace_id` 进行关联 |
| R2 | 在**零**上游改动的情况下工作（论文中"上游不提供 `focus.*`"的场景） | 血缘键位于客户端的根 span 上；用量由 vLLM 自身的 span 提供；我们在摄取时进行关联 |
| R3 | 统计 100% 的账单（不偏向成功路径） | 保留值 `UNLINKED` 和 `IDLE`；失败的任务作为报废保留 |
| R4 | 真实的质量门，而不是编造的通过率 | 选用结果可自动对照真实答案（ground truth）进行检查的工作负载 |
| R5 | 不局限于 Kubernetes | 运行在 `llm-d-spark-nonk8s-demo` 技术栈上（Docker Compose、基于文件的发现）；成本输入是一张 FOCUS 格式的表，可替换为 OpenCost 的导出数据 |
| R6 | 可复现 | 确定性的任务生成器（带种子）、一个脚本、输出为 CSV + SQLite |

## 3. 架构

```
                         W3C traceparent + baggage(focus.*)
 +----------------+  ------------------------------------>  +--------+  ext_proc  +------------------+
 | agent driver   |                                         | Envoy  | <--------> | EPP (llm-d       |
 | (application)  |  root span "agent.<step>" with          | :8081  |            | router), precise |
 | support_bot    |  focus.workload.id / task.id /          +--------+            | prefix-cache     |
 | triage_bot     |  outcome.id + gen_ai.usage.*                |                 +------------------+
 | playground     |  (playground calls: no keys = UNLINKED)     v                        ^ KV events (ZMQ)
 +----------------+                                      +-------------+ +-------------+ |
        |  OTLP/HTTP JSON                                | vLLM-0 :8000| | vLLM-1 :8001|-+
        |                                                | llm_request | | llm_request |   one GB10 GPU
        v                                                +-------------+ +-------------+
 +----------------+   OTLP gRPC (Envoy, EPP, vLLM)              |               |
 | OTel Collector | <--------------------------------------------+---------------+
 +----------------+
        v
 +----------------+    build.py: per trace, join the root span's focus.* onto the
 |    Jaeger      | -> vLLM leaf span; aggregate per (charge period, workload, task);
 +----------------+    allocate the GPU bill by ActivityWeight
                                   |
 tasks.jsonl (gates, from driver) -+-> SQLite: cost_and_usage, telemetry, task, outcome, value
 demo.toml (prices, rate cards) ---+   + KPI views (kpis.sql) -> report.md / report.html
```

### 3.1 每个归因键的来源（论文 2.2.2 节）

| 论文中的层 | 本演示中的对应组件 | 它添加了什么 |
|---|---|---|
| 1. Agent 框架 / 应用 | `attribution/driver.py` | 在根 span 上和 W3C baggage 中添加 `focus.workload.id`、`focus.task.id`、`focus.outcome.id`（工单 / 告警在运行前就已存在，因此结果 id 在开始时即已知） |
| 2. 网关、路由器、推理引擎 | Envoy、EPP、vLLM | 仅传递 trace 上下文。vLLM 的 `llm_request` span 带有 `gen_ai.usage.prompt_tokens`、`completion_tokens`、`gen_ai.latency.time_in_model_prefill/decode` |
| 3. 遥测采集器 | OTel Collector | 目前不额外添加任何内容（可以添加主机 / GPU 资源属性） |
| 4. 企业级数据补全 | `attribution/build.py` | 按 `trace_id` 把根 span 的键关联到 vLLM 叶子 span 上；从 `configs/demo.toml` 提供计费范围（`ServiceProviderName`、`BillingAccountId`、`ResourceId` ...） |

目前没有任何上游组件输出 `focus.*`，本演示也不需要它们这样做。论文
提醒说，在其作者的测试中 vLLM "没有延续调用方的 trace"。而在这里，vLLM 0.27.1
开启 `--otlp-traces-endpoint` 后**确实**延续了 trace，
正是这一点使得基于 `trace_id` 的关联成为可能。

### 3.2 为什么按 `trace_id` 关联，而不是读取 baggage

`baggage` 会到达每一跳，因为 Envoy 会转发该请求头，但**没有任何组件
把 baggage 条目复制到自己的 span 上**，而且 OTel Collector 看不到
baggage。根 span 是唯一记录这些键的地方。对 EPP 做一个小改动
就能把这些键也放到路由器的 span 上；参见 [README §9](../nonk8s/README-zh.md#9-后续计划)。

## 4. 数据模型映射

全部五张表都沿用论文中的列名（第 3 节）。论文
未定义的列以 `x_` 为前缀，这与 FOCUS 对自定义列的做法一致。

### 4.1 CostAndUsage：自托管 GPU 的账单

自托管 GPU 没有云账单，因此本演示合成 FOCUS 行。每个
计费周期为该 GPU 生成一行，其中
`EffectiveCost = gpu_hourly_usd × period / 3600`（`PricingCategory = Committed`，
`ConsumedUnit = GPU Hours`）。

* **消费范围** = 提供商 + 计费账户 + `ResourceId = spark-3bee/gpu0`。
  两个 vLLM 副本共享这一块 GPU，因此属于同一个范围。副本信息
  作为 `x_ServingReplica` 保留在 Telemetry 中。
* **计费周期**：60 s（可配置）。FOCUS 按小时或按天计费。本演示
  压缩了时间，使每个阶段跨越多个周期。
* **Kubernetes**：用 OpenCost 的 FOCUS 导出数据替换这张表，以
  节点 / GPU 为键。**不使用 Kubernetes 时**：按每 GPU 小时分摊的硬件 + 电力 + 运维成本，
  这正是 `demo.toml` 所编码的内容。

### 4.2 Telemetry：叶子 span 与 ActivityWeight

* **GPU 范围的叶子 span** = vLLM 的 `llm_request`。它是消耗了被计费资源的
  最深层 span（论文 2.3.1 节）。Envoy 和 EPP 的 span
  不计入 GPU 成本。
* **行粒度** = (计费周期, WorkloadId, TaskId, OutcomeId, 副本)。
  关联完成后丢弃 `trace_id` / `span_id`。
* **`CacheReadTokenCount`** 来自客户端：vLLM 返回
  `usage.prompt_tokens_details.cached_tokens`（需开启
  `--enable-prompt-tokens-details`），driver 将其作为
  `gen_ai.usage.cache_read.input_tokens` 写到自己的根 span 上。vLLM 的 span 没有缓存属性。
* **`ActivityWeight`**：论文建议按 token 价格加权（输出为输入的 3-5×，
  缓存读取为 0.1×），这适用于按 token 计费的 API。对于自托管
  引擎，成本驱动因素是 GPU 时间，因此默认值为
  `method = "gpu_time"`：即 vLLM 测得的 `time_in_model_prefill + time_in_model_decode`。
  也可使用 `method = "tokens"` 进行对比。
  **注意：**在连续批处理（continuous batching）下，多个请求共享前向计算，因此
  各请求模型时间之和会超过实际的 GPU 挂钟时间。作为同一周期内的*相对*权重，
  它仍然是一种公平的分摊方式，但不应被解读为
  绝对的 GPU 秒数。
* **`IDLE`**：没有任何活动的计费周期会变成一行 `IDLE`，保留
  其成本，而不是消失（这是论文 2.3.2 节中的开放问题）。
  在有活动的周期内，空闲容量按论文所述
  分摊给各使用方。

### 4.3 任务与结果：两道门

| 工作负载 | 任务：第一道门（任务门），执行过程中 | 结果：第二道门（结果门），交付之后 |
|---|---|---|
| `support_bot`：账单争议 agent。每个工单带有一段较长（约 3.9k token）且唯一的发票历史；第 1 步*调查*，第 2 步在同一对话中进行*工具调用*，最多重试 2 次 | 退款计算器调用格式正确，**并且**其 `amount_usd` 与该套餐下一张确实存在的发票相符（工具会对照记录进行校验） | 退款金额精确到分，即 agent 使用了**最近一张**发票。否则客户会在结算窗口内重新打开工单 |
| `triage_bot`：告警分诊。约 250 token 的提示词，单次调用 | 输出使用允许标签的 JSON | 严重级别**和**组件都与真实答案一致；否则该告警会被重新升级 |
| playground | 无：没有键，因此为 `UNLINKED` | 无 |

单位和人力成本遵循论文 2.4.3 节：

* 任务数量以**分钟**为单位：`Baseline` = 由人完成该工作所需的时间，
  `Observed` = AI 交付的分钟数，`Friction` = 即使通过也需要的人工审核（摩擦），
  `Rework` = 失败时的人工善后（返工）。
* `support_bot` 的结果是离散单位（`deflected_tickets`），因此不能
  从中减去分钟数。摩擦与返工被货币化为
  一条在同一 CFO 视角下的**单独的负向价值主张**（`Friction and Rework`）。
* `triage_bot` 的结果以分钟为单位，因此摩擦与返工从
  任务中汇总上来，召回成本则直接扣减。

结算：结果在其任务结束后的 `window_seconds` 内处于 `Pending` 状态，
之后变为 `Settled`（冻结）。结算窗口内的召回会更新 Pending 条目；本
演示从不需要修正条目。

### 4.4 价值

| 工作负载 | 利益相关方 | 类别 | 乘数 | 状态 |
|---|---|---|---|---|
| support_bot | CFO | Cost Reduction（成本降低） | 每个被分流的工单 $8.50 | Reported |
| support_bot | CFO | Friction and Rework（摩擦与返工） | 每人工分钟 −$1.50 | Reported |
| triage_bot | CTO | Engineering Capacity（工程产能） | 每净分钟 $1.50 | Reported |

所有价值主张都是 `Reported`，从不是 `Booked`：演示中没有独立的
证明方。`RealizedValue` 仅为 Settled 的结果设置。`PlannedValue` 编码的是
业务预期（90% 合格）。

### 4.5 KPI（`attribution/kpis.sql`）

`kpi_infra`（论文 4.1 节）、`kpi_workload`（4.2-4.4 节）、`kpi_phase`
（组合视图，报废率中 `UNLINKED` 单独成行，`IDLE` 分开保留）。有两处
有意的偏离：

* **每个合格结果的 GPU 秒数（GPU-s per qualified outcome）**与 CPQO 并列。在固定价格的 GPU 上，
  浪费 GPU 时间的事故不会改变同一周期的账单；它消耗的是
  容量。GPU-s/QO 以物理单位展示这种浪费，与
  账单如何分摊无关。
* **每 $1 价值的开销（Spend per $1 of value）**取代了 ROI %。在一块 GPU 上运行 1.5B 模型时，计算
  成本相对于人力成本微不足道，因此 ROI 百分比会变成毫无意义的巨大
  数字。

## 5. 实验设计

| 阶段 | EPP 配置 | 预期 |
|---|---|---|
| `baseline` | `prefix-cache-scorer` 权重 3（上游默认值） | 第 2 步 / 重试会落到持有该工单前缀的副本上：KV 命中率高，prefill 短 |
| `incident` | 权重 0（KubeCon 上的错误配置） | 后续步骤分散到各副本：命中率降低，每个合格结果耗费更多 prefill GPU 时间。两道门不受影响，因此*质量*类 KPI 应保持不变 |

两个阶段使用相同的种子、并发度和时长。`scripts/run-demo.sh` 运行
两个阶段，恢复权重 3，等待结算窗口结束，然后构建
数据集和报告。

## 6. 已知局限

* 数字很小：一块 GB10 运行 1.5B 模型，每个阶段只花几美分，因此成本
  以 4-5 位小数显示。它们随 `gpu_hourly_usd` 线性缩放。
* 在批处理下，按请求累加的模型时间会重复计算（4.2 节）。
* `UNLINKED` 调用没有根 span，因此其缓存 token 数未知
  （报告为 0）。
* EPP 的 span 是客户端根 span 之下 Envoy span 的兄弟节点，而不是子节点
  （`llm-d-spark-nonk8s-demo` §10.2）。这不影响关联，因为两者
  都挂在 driver 的根 span 之下。
* 没有 P/D 分离，也没有分层 KV 卸载，因此只有一个 GPU 范围和
  一个缓存层级。
