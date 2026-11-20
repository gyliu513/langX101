# Findings / 发现汇总 (English · 中文对照)

Source run: `llm-d/tokeneconomics`, DGX Spark (GB10), 2026-11-19, vLLM 0.27.1, EPP `main`
(2026-11-16), Qwen2.5-1.5B-Instruct × 2, baseline (`prefix-cache-scorer` weight 3) vs
incident (weight 0), 310 s each, 12 concurrent agents. Full evidence:
[`../nonk8s/README.md`](../nonk8s/README.md) / [`../nonk8s/README-zh.md`](../nonk8s/README-zh.md); Kubernetes findings K1-K6:
[`../k8s/README.md`](../k8s/README.md) / [`../k8s/README-zh.md`](../k8s/README-zh.md).

数据来源：`llm-d/tokeneconomics`，DGX Spark（GB10），2026-11-19，vLLM 0.27.1，EPP `main`
（2026-11-16），Qwen2.5-1.5B-Instruct × 2，基线（`prefix-cache-scorer` 权重 3）对比
故障（权重 0），每个阶段 310 秒，12 个并发 agent。完整证据见
[`../nonk8s/README.md`](../nonk8s/README.md) / [`../nonk8s/README-zh.md`](../nonk8s/README-zh.md)；Kubernetes 相关发现 K1-K6 见
[`../k8s/README.md`](../k8s/README.md) / [`../k8s/README-zh.md`](../k8s/README-zh.md)。

---

## Summary / 总览

| # | Finding (EN) | 发现（中文） | Owner / 归属 | Type / 类型 |
|---|---|---|---|---|
| E1 | The KubeCon bug has a price: +22% cost per qualified outcome, −15% capacity | KubeCon 那个 bug 可以算出价格：每个合格结果成本 +22%，容量 −15% | demo result / 演示结论 | economics / 经济性 |
| E2 | A shared fixed-price GPU couples workloads: +43% unit cost for an unaffected neighbour | 共享的固定价格 GPU 会让工作负载互相牵连：未受影响的邻居单位成本 +43% | demo result / 演示结论 | economics / 经济性 |
| E3 | Quality, not compute, dominates small-model economics: Task gate 100%, Outcome gate 36%, negative value | 小模型的经济性由质量而不是算力决定：任务门 100%，结果门 36%，价值为负 | demo result / 演示结论 | economics / 经济性 |
| F1 | vLLM does continue the caller's trace (the paper says it does not) | vLLM 确实会延续调用方的 trace（论文说不会） | Tokenomics paper / FOCUS SemConv WG | correction / 勘误 |
| F2 | No component records `focus.*` baggage on its spans | 没有任何组件把 `focus.*` baggage 记录到 span 上 | llm-d-router (+ vLLM, P/D sidecar) | gap / 缺口 |
| F3 | vLLM's span lacks cached tokens and the response model | vLLM 的 span 缺少缓存 token 数和响应模型 | vLLM | gap / 缺口 |
| F4 | Summed per-request GPU time over-counts ~11× under continuous batching | 连续批处理下逐请求累加的 GPU 时间约重复计数 11 倍 | vLLM + Tokenomics paper | gap / 缺口 |
| F5 | Allocated cost alone blames the wrong workload; a usage-basis KPI is needed | 只看分摊成本会怪错工作负载，需要用量口径的 KPI | Tokenomics paper / playbook | recommendation / 建议 |
| F6 | The Task gate cannot catch a stale-but-valid tool argument | 任务门发现不了“合法但过期”的工具参数 | agent design / agent 设计 | insight / 洞察 |
| F7 | EPP span is a sibling of Envoy's span when the client sends `traceparent` | 客户端带 `traceparent` 时，EPP 的 span 与 Envoy 的 span 成为兄弟节点 | llm-d-router (known) | known issue / 已知问题 |
| F8 | Changing a scorer weight requires an EPP restart | 修改 scorer 权重需要重启 EPP | llm-d-router | limitation / 限制 |
| F9 | Jaeger / Grafana UIs load very slowly over a remote link | 通过远程链路访问时 Jaeger / Grafana 界面加载很慢 | tooling / 工具 | ops note / 运维提示 |
| K1 | On Kubernetes, OpenCost shows idle GPU is ~half the bill | Kubernetes 上 OpenCost 显示空闲 GPU 约占账单一半 | FinOps / paper | economics / 经济性 |
| K2 | EPP KV-event tracing floods Jaeger (~87k traces/min) and evicts request traces | EPP 的 KV 事件追踪淹没 Jaeger（约 8.7 万条/分钟），挤掉请求 trace | llm-d-router | gap / 缺口 |
| K3 | Time-sliced GPUs need a per-slice OpenCost price | 时间分片 GPU 需要按分片设置 OpenCost 价格 | operators / 运维 | ops note / 运维提示 |
| K4 | vLLM replicas share one OTel service name; pod name must be added | vLLM 副本共用一个 OTel 服务名，需要补 pod 名 | llm-d guides / charts | gap / 缺口 |
| K5 | Trace topology differs between Kubernetes and no-Kubernetes | Kubernetes 与非 Kubernetes 的 trace 结构不同 | consumers / 使用方 | insight / 洞察 |
| K6 | Task IDs must be globally unique (PID 1 in containers) | 任务 ID 必须全局唯一（容器里 PID 恒为 1） | agent design / agent 设计 | lesson / 教训 |

---

## E1. The KubeCon bug has a price / KubeCon 那个 bug 可以算出价格

**EN.** Setting `prefix-cache-scorer` to weight 0 makes the follow-up step of a
support_bot task land on a different replica 50.8% of the time (baseline 0.0%). The
`compute` step's KV-cache hit falls from 97.7% to 48.9%. In one sampled trace, prefill for
the same ~3.9k-token prompt rises from 105 ms to 549 ms (5.2×). Over the phase,
support_bot's GPU-seconds per qualified outcome rise from 12.72 to 15.49 (+22%), its cost
per qualified outcome (CPQO) from $0.00145 to $0.00177 (+22%), and the whole GPU completes
15% fewer tasks (1,040 → 880) in the same 310 s. Outcome quality does not change
(36.4% → 35.6%). The bug wastes capacity; it does not make answers worse.

**中文。** 把 `prefix-cache-scorer` 权重改成 0 之后，support_bot 任务的后续步骤有 50.8%
落到了另一个副本上（基线为 0.0%）。`compute` 步骤的 KV cache 命中率从 97.7% 降到 48.9%。
在一条抽样 trace 中，同样约 3.9k token 的 prompt，prefill 从 105 ms 涨到 549 ms（5.2 倍）。
整个阶段内，support_bot 每个合格结果消耗的 GPU 秒从 12.72 涨到 15.49（+22%），每个合格结果的
成本（CPQO）从 $0.00145 涨到 $0.00177（+22%）。在同样的 310 秒内，整张 GPU 完成的任务数少了 15%
（1,040 → 880）。结果质量没有变化（36.4% → 35.6%）。这个 bug 浪费的是容量，并不会让回答变差。

---

## E2. A shared GPU couples workloads / 共享 GPU 让工作负载互相牵连

**EN.** triage_bot is not affected by the bug: its prompts are short and its cache hit
is unchanged (26.7% → 26.8%). Yet its cost per 1M tokens rises 43% ($0.373 → $0.534) and
its CPQO 31%. On a fixed-price GPU the per-period bill is constant and is spread by
activity share, so when support_bot gets less efficient, everyone's allocated unit cost
goes up. A FinOps team reading only allocated cost would blame the wrong workload. The
usage-basis view (triage_bot GPU-s per qualified outcome +8%, from general contention)
shows where the waste is. See also F5.

**中文。** triage_bot 并没有受这个 bug 影响：它的 prompt 很短，缓存命中率也没变
（26.7% → 26.8%）。但它每百万 token 的成本上涨了 43%（$0.373 → $0.534），CPQO 上涨了 31%。
在固定价格的 GPU 上，每个计费周期的账单是固定的，并按活动占比分摊。所以 support_bot
效率一下降，所有人分摊到的单位成本都会上升。只看分摊成本的 FinOps 团队会怪错工作负载。
用量口径（triage_bot 每个合格结果的 GPU 秒只上升 8%，来自整体资源争用）才能看出浪费
真正在哪里。另见 F5。

---

## E3. Quality dominates small-model economics / 小模型的经济性由质量决定

**EN.** support_bot passes its in-flight technical gate (Task) 100% of the time, but only
36.4% of refunds survive the post-delivery check (Outcome). 357 tickets are reopened.
Priced with human review (2 min) and rework (12 min per reopened ticket) at $1.50/min,
its baseline value is **−$6,375** (+$1,734 deflection, −$8,109 friction and rework),
while its whole GPU bill for the phase is about $0.30. The lever is model or agent
quality (a larger model, or a tool that knows which invoice is current), not the GPU
price. Without the Outcome dataset, this agent would have been reported as "100%
successful". This is the strongest argument for the paper's two-gate design.

**中文。** support_bot 的执行中技术检查（任务门）100% 通过，但只有 36.4% 的退款经受住了
交付后的检查（结果门），有 357 张工单被重新打开。按 $1.50/分钟计算人工审核（2 分钟）和
返工（每张重开工单 12 分钟）后，它在基线阶段的价值是 **−$6,375**（工单分流 +$1,734，
摩擦与返工 −$8,109），而它在该阶段的 GPU 账单总共只有约 $0.30。真正的杠杆是模型或 agent
的质量（换更大的模型，或者让工具知道哪张发票是最新的），而不是 GPU 价格。如果没有结果
数据集，这个 agent 会被报告为“100% 成功”。这是支持论文两道门设计最有力的证据。

---

## F1. vLLM does continue the caller's trace / vLLM 确实会延续调用方的 trace

**EN.**
- **What:** the paper (section 2.2.2) says vLLM "did not" continue the caller's trace in
  its authors' testing.
- **Evidence:** with `--otlp-traces-endpoint` on vLLM 0.27.1, `llm_request` is a child of
  Envoy's router span in the caller's trace. All 3,200 vLLM spans in the run joined their
  trace.
- **Action:** send the evidence to the paper's authors (FOCUS SemConv WG). The likely
  difference is the tracing flag, or a gateway that drops `traceparent`.

**中文。**
- **现象：** 论文（第 2.2.2 节）称，在作者的测试中 vLLM “没有”延续调用方的 trace。
- **证据：** vLLM 0.27.1 开启 `--otlp-traces-endpoint` 后，`llm_request` 是调用方 trace 中
  Envoy router span 的子 span。本次运行的 3,200 个 vLLM span 全部接入了各自的 trace。
- **行动：** 把证据发给论文作者（FOCUS SemConv WG）。差异的原因很可能是 tracing 开关，
  或者某个网关丢弃了 `traceparent`。

---

## F2. No component records the baggage / 没有任何组件记录 baggage

**EN.**
- **What:** the EPP registers both the TraceContext and the Baggage propagators
  (`llm-d-router/pkg/common/observability/tracing/telemetry.go:55`), and Envoy forwards
  the `baggage` header. But no span in Envoy, the EPP or vLLM carries `focus.*`: a probe
  request with baggage produced 17 spans and 0 such attributes.
- **Impact:** the lineage keys exist only on the client's root span. Attribution needs a
  trace-wide join at ingest, so full traces must be kept, and any client that does not
  export its own span is UNLINKED.
- **Proposal (llm-d-router):** an opt-in allowlist, for example
  `--trace-baggage-attributes=focus.workload.id,focus.task.id,focus.outcome.id`, that
  copies the listed baggage entries onto the EPP's `request` span. llm-d would then be
  the first inference stack that emits `focus.*` natively. vLLM and the P/D sidecar need
  the same option.

**中文。**
- **现象：** EPP 同时注册了 TraceContext 和 Baggage 两种 propagator
  （`llm-d-router/pkg/common/observability/tracing/telemetry.go:55`），Envoy 也会转发
  `baggage` 头。但 Envoy、EPP、vLLM 的 span 上都没有 `focus.*`：一次带 baggage 的探测请求
  产生了 17 个 span，这类属性一个也没有。
- **影响：** 标识只存在于客户端的根 span 上。归因必须在摄取时做整条 trace 范围的关联，
  因此必须保留完整 trace；任何不导出自己 span 的客户端都会变成 UNLINKED。
- **提议（llm-d-router）：** 增加一个可选启用的白名单，例如
  `--trace-baggage-attributes=focus.workload.id,focus.task.id,focus.outcome.id`，
  把名单中的 baggage 条目复制到 EPP 的 `request` span 上。这样 llm-d 就会成为第一个
  原生输出 `focus.*` 的推理栈。vLLM 和 P/D sidecar 也需要类似的选项。

---

## F3. vLLM's span lacks cached tokens and the response model / vLLM 的 span 缺少缓存 token 数和响应模型

**EN.**
- **What:** `llm_request` carries `gen_ai.usage.prompt_tokens` / `completion_tokens` and
  prefill / decode times, but not `gen_ai.usage.cache_read.input_tokens` and not
  `gen_ai.response.model`. The paper maps both directly from OTel (`CacheReadTokenCount`,
  `ModelId`).
- **Impact:** the cached count is only in the HTTP response, and only with
  `--enable-prompt-tokens-details`. The demo has to take it from the client, so the cache
  reads of UNLINKED calls are unknown.
- **Proposal (vLLM):** add the cached-token count (and `created_cache_tokens` as
  `cache_write`) and the response model to the request span.

**中文。**
- **现象：** `llm_request` 上有 `gen_ai.usage.prompt_tokens` / `completion_tokens` 和
  prefill / decode 时间，但没有 `gen_ai.usage.cache_read.input_tokens`，也没有
  `gen_ai.response.model`。论文要从 OTel 直接映射这两项（`CacheReadTokenCount`、`ModelId`）。
- **影响：** 缓存 token 数只出现在 HTTP 响应里，而且要开启 `--enable-prompt-tokens-details`
  才有。演示只能从客户端获取，所以 UNLINKED 调用的缓存读取量是未知的。
- **提议（vLLM）：** 在请求 span 上加上缓存 token 数（以及作为 `cache_write` 的
  `created_cache_tokens`）和响应模型名。

---

## F4. Per-request GPU time over-counts under batching / 批处理下逐请求 GPU 时间重复计数

**EN.**
- **What:** in the baseline, the sum of prefill + decode time over all calls is
  3,461 GPU-s in a 310 s phase: about 11× wall-clock at 12-way concurrency, because
  batched requests share forward passes. The paper's `TotalDurationMs` has the same
  problem.
- **Impact:** as a *relative* ActivityWeight within one charge period it is still a fair
  split, but it cannot be read as GPU-seconds or used to estimate utilization or idle
  capacity.
- **Proposal (vLLM + paper WG):** an engine-level "attributed GPU time" per request:
  each forward pass's time divided over its batch members, weighted by tokens, exported
  on the span. This is concrete input for the paper's open "weighting formulas" question
  (section 2.3.2) for self-hosted engines.

**中文。**
- **现象：** 基线阶段所有调用的 prefill + decode 时间加起来是 3,461 GPU 秒，而阶段只有
  310 秒：在 12 路并发下约为墙钟时间的 11 倍，因为批处理中的请求共享前向计算。论文中的
  `TotalDurationMs` 有同样的问题。
- **影响：** 在同一个计费周期内作为*相对*的 ActivityWeight，它仍然是公平的分摊依据；
  但不能当作 GPU 秒来读，也不能用来估算利用率或空闲容量。
- **提议（vLLM + 论文工作组）：** 由引擎为每个请求输出“归因 GPU 时间”：把每次前向计算的
  时间按 token 加权分给同批的各个请求，并写到 span 上。这可以作为论文中自建推理“权重
  公式”这一开放问题（第 2.3.2 节）的具体输入。

---

## F5. Publish a usage-basis KPI next to allocated cost / 在分摊成本旁边给出用量口径 KPI

**EN.**
- **What:** the paper allocates each period's bill by activity share. On self-hosted,
  fixed-price capacity this couples workloads (E2).
- **Recommendation (paper / playbook):** for self-hosted capacity, report a usage-basis
  KPI, resource time per qualified outcome, next to the allocated-cost KPIs (CPQT, CPQO).
  This is the same split as our KubeCon deck's "allocation cost vs usage cost". The demo
  implements it as `gpu_s_per_qo`.

**中文。**
- **现象：** 论文按活动占比分摊每个周期的账单。在自建、固定价格的容量上，这会让工作
  负载互相牵连（E2）。
- **建议（论文 / Playbook）：** 对自建容量，在分摊成本类 KPI（CPQT、CPQO）旁边同时给出
  用量口径的 KPI：每个合格结果消耗的资源时间。这与我们 KubeCon 演讲中“分摊成本 vs 用量
  成本”的区分一致。演示中实现为 `gpu_s_per_qo`。

---

## F6. The Task gate misses stale-but-valid arguments / 任务门发现不了“合法但过期”的参数

**EN.**
- **What:** support_bot's tool validates that `amount_usd` is a real invoice amount for
  the customer's plan. That passes 100%, but the agent often picks an *older* invoice,
  which only the customer's reopened ticket (the system of record) reveals.
- **Insight:** in-flight checks verify *form and existence*. Only post-delivery outcomes
  verify *correctness in context*. Any value report built only on Task data will
  overstate value.

**中文。**
- **现象：** support_bot 的工具会校验 `amount_usd` 是否是该套餐真实存在的发票金额。这一
  检查 100% 通过，但 agent 经常选到*较早*的发票，只有客户重新打开工单（即记录系统）才能
  暴露出来。
- **洞察：** 执行中的检查只能验证*格式和存在性*，只有交付后的结果才能验证*在具体上下文中
  是否正确*。只基于任务数据的价值报告会高估价值。

---

## F7. EPP span is a sibling of Envoy's span (known) / EPP span 与 Envoy span 成为兄弟节点（已知问题）

**EN.** When the client sends `traceparent`, `[llm-d-epp] request` hangs under the client
root instead of under Envoy's ext_proc span (`llm-d-spark-nonk8s-demo` §10.2;
`extractTraceContext` in `pkg/epp/handlers/server.go` lets the header override the gRPC
metadata). Attribution is not affected, because the driver exports its root span, but the
waterfall is harder to read. Proposed fix (unchanged): when both contexts have the same
trace id, prefer the gRPC-metadata span.

**中文。** 客户端带 `traceparent` 时，`[llm-d-epp] request` 会挂在客户端根 span 下面，
而不是 Envoy 的 ext_proc span 下面（见 `llm-d-spark-nonk8s-demo` §10.2；
`pkg/epp/handlers/server.go` 中的 `extractTraceContext` 让请求头覆盖了 gRPC metadata）。
归因不受影响，因为 driver 导出了自己的根 span；但调用瀑布图更难读。建议的修复方式不变：
两个上下文的 trace id 相同时，优先使用 gRPC metadata 里的 span。

---

## F8. Scorer weight changes need an EPP restart / 修改 scorer 权重需要重启 EPP

**EN.** The EPP configuration is not hot-reloaded, so each phase switch recreates the EPP
container (about 6 s). The few calls in flight show up as a `between-phases` UNLINKED line
($0.0164). This is harmless for the demo, and the real KubeCon incident (a Helm upgrade)
restarts the EPP as well. A config hot-reload, or a per-request override for experiments,
would make A/B cost experiments cleaner.

**中文。** EPP 配置不支持热加载，所以每次切换阶段都要重建 EPP 容器（约 6 秒）。期间少量
在途请求会显示为一行 `between-phases` UNLINKED（$0.0164）。这对演示无害，KubeCon 的真实
故障（一次 Helm 升级）同样会重启 EPP。如果 EPP 支持配置热加载，或者支持按请求覆盖配置
做实验，A/B 成本实验会更干净。

---

## F9. Remote UI access / 远程访问界面

**EN.** Over the Tailscale link used for the run, Jaeger's 4.3 MB UI bundle took about
36 s to load and Grafana's plugins several minutes, so both looked blank at first.
Workaround: an SSH tunnel to `localhost`, then wait. Grafana's "KV Cache Usage %" panel
shows the *last* value, which is 0 once the run is over. This is not a bug.

**中文。** 本次运行使用的 Tailscale 链路上，Jaeger 4.3 MB 的前端包加载约 36 秒，Grafana
插件加载要几分钟，所以两个页面一开始看起来都是空白。解决办法：用 SSH 隧道转发到
`localhost`，然后耐心等待。Grafana 的 “KV Cache Usage %” 面板显示的是*最新值*，运行结束后
为 0。这不是 bug。

---

## K1. Idle GPU is about half the bill on Kubernetes / Kubernetes 上空闲 GPU 约占账单一半

**EN.** With OpenCost as the Cost and Usage source (per pod, per minute), 52% of each phase's bill
(56% over the run) is `__idle__`: the node has 4 time-sliced GPU units and the two vLLM pods
request 2. The idle line ($0.23 per 5-minute phase) is larger than support_bot's whole bill
($0.16). The paper (2.3.2) leaves open whether to spread unused capacity or hold it
separately. **Recommendation:** hold it separately, as OpenCost does, and report it next to CPQO.
Spreading it would double every CPQO and hide the routing incident in the noise.

**中文。** 以 OpenCost 作为成本与用量来源（按 pod、按分钟）时，每个阶段账单的 52%（整个运行为 56%）是
`__idle__`：节点有 4 个时间分片 GPU 单元，两个 vLLM pod 只申请了 2 个。空闲这一行（每个 5 分钟
阶段 $0.23）比 support_bot 的全部账单（$0.16）还大。论文（2.3.2）没有规定未用容量应该分摊还是单列。
**建议：** 像 OpenCost 一样单列，并在 CPQO 旁边报告。如果分摊，所有 CPQO 都会翻倍，路由故障也会被
淹没在噪声里。

---

## K2. The EPP's KV-event tracing floods Jaeger / EPP 的 KV 事件追踪淹没 Jaeger

**EN.**
- **What:** with `kvEventsConfig.tracing: true`, the EPP starts a new root trace for every KV-cache
  index event: about 87,000 single-span traces per minute on two small replicas (93% `index_evict`),
  about 60× the request traces.
- **Impact:** Jaeger's in-memory store evicted request traces within a minute or two. An end-of-run
  query lost 76% of the baseline traces, and a 60 s harvester still missed half the incident traces.
- **Workaround used:** drop `index_evict` and `index_add` spans in the OTel Collector's filter
  processor (98% of spans filtered). `IsRootSpan()` did not match the standalone `index_add`
  traces.
- **Proposal (llm-d-router):** sample KV-event tracing separately from request tracing, or record
  index events as span events, and keep it off in default profiles.

**中文。**
- **现象：** 开启 `kvEventsConfig.tracing: true` 后，EPP 会为每个 KV cache 索引事件新开一条根 trace：两个
  小副本上每分钟约 8.7 万条单 span trace（93% 是 `index_evict`），约为请求 trace 的 60 倍。
- **影响：** Jaeger 的内存存储在一两分钟内就把请求 trace 挤掉了。运行结束后查询，基线阶段 76% 的 trace
  已丢失；即使每 60 秒采集一次，故障阶段也漏掉了一半。
- **本次的处理：** 在 OTel Collector 的 filter processor 中丢弃 `index_evict` 和 `index_add` span（98% 的 span
  被过滤）。`IsRootSpan()` 匹配不到独立的 `index_add` trace。
- **提议（llm-d-router）：** 让 KV 事件追踪与请求追踪分开采样，或改为 span event，并在默认配置中关闭。

---

## K3. Time-sliced GPUs need a per-slice price / 时间分片 GPU 需要按分片定价

**EN.** OpenCost prices each `nvidia.com/gpu` unit at the configured GPU rate. With time-slicing ×4,
the default rate would bill one GB10 as four GPUs. Set the price to the physical GPU's rate
divided by the slice count ($1.00 = $4.00 / 4 here). A slice's cost says nothing about how much of
the GPU it actually used; that is what the usage-basis KPI is for.

**中文。** OpenCost 按配置的 GPU 单价为每个 `nvidia.com/gpu` 单元计价。时间分片 ×4 时，默认单价会把
一块 GB10 当成四块 GPU 计费。应把单价设为物理 GPU 单价除以分片数（本例 $1.00 = $4.00 / 4）。
一个分片的成本并不反映它实际用了多少 GPU，这正是用量口径 KPI 要补的部分。

---

## K4. Replicas share one OTel service name / 副本共用一个 OTel 服务名

**EN.** Both vLLM pods export as `vllm-precise-prefix`, so a span alone cannot be matched to its
OpenCost row. The demo adds `k8s.pod.name` through the downward API. **Proposal (llm-d guides /
charts):** set `OTEL_RESOURCE_ATTRIBUTES=k8s.pod.name=$(POD_NAME),…` on model servers by default, as
the EPP chart already does for itself.

**中文。** 两个 vLLM pod 都以 `vllm-precise-prefix` 导出，仅凭 span 无法对应到 OpenCost 的某一行。本演示
通过 downward API 加上了 `k8s.pod.name`。**提议（llm-d 指南 / chart）：** 默认给模型服务器设置
`OTEL_RESOURCE_ATTRIBUTES=k8s.pod.name=$(POD_NAME),…`，EPP 的 chart 已经这样为自己设置了。

---

## K5. Trace topology differs / trace 结构不同

**EN.** On Kubernetes, vLLM's `llm_request` is a child of the EPP's `request` span; without
Kubernetes it hangs under Envoy's router span. Joining on `trace_id` works for both. Tooling
that assumes a fixed parent breaks across deployments.

**中文。** 在 Kubernetes 上，vLLM 的 `llm_request` 是 EPP `request` span 的子 span；非 Kubernetes 部署中
它挂在 Envoy 的 router span 下。按 `trace_id` 关联对两者都适用；假设固定父 span 的工具会在两种部署间失效。

---

## K6. Task IDs must be globally unique / 任务 ID 必须全局唯一

**EN.** The first Kubernetes run derived task IDs from the process ID, which is always 1 in a
container. A leftover Job then produced colliding IDs, and its traffic was attributed to the new
run's tasks. The driver now adds a random run ID, and build keeps only spans inside the phase
windows. The paper's "opaque internal keys" also have to be globally unique.

**中文。** 第一次 Kubernetes 运行用进程 ID 生成任务 ID，而容器里 PID 恒为 1。一个残留的 Job 因此产生了
重复 ID，它的流量被算到了新一轮运行的任务上。现在 driver 会加一个随机运行 ID，build 也只保留阶段时间窗
内的 span。论文要求的“不透明内部键”同样必须全局唯一。

---

## Upstream actions / 上游行动项

| # | Action (EN) | 行动（中文） | Target / 目标 |
|---|---|---|---|
| 1 | Opt-in baggage → span attributes allowlist in the EPP (F2) | EPP 增加可选的 baggage → span 属性白名单（F2） | llm-d-router |
| 2 | Cached / created-cache tokens + response model on the request span (F3) | 在请求 span 上补充缓存读写 token 数和响应模型（F3） | vLLM |
| 3 | Batch-aware attributed GPU time per request (F4) | 批处理感知的逐请求归因 GPU 时间（F4） | vLLM + Tokenomics WG |
| 4 | Report F1 evidence; propose a usage-basis KPI and a self-hosted ActivityWeight (F1, F4, F5) | 提交 F1 证据；提议用量口径 KPI 和自建推理的 ActivityWeight（F1、F4、F5） | Tokenomics Foundation / FOCUS SemConv WG |
| 5 | Submit `results/` as sample data and this demo as a reference implementation | 把 `results/` 作为样例数据、本演示作为参考实现提交 | Tokenomics Foundation (FOCUS 1.6 cycle, June 2027 demo) |
| 6 | Prefer the gRPC-metadata span when trace ids match (F7) | trace id 相同时优先使用 gRPC metadata 中的 span（F7） | llm-d-router |
| 7 | Sample KV-event tracing separately, or emit span events (K2) | KV 事件追踪单独采样，或改为 span event（K2） | llm-d-router |
| 8 | `k8s.pod.name` on model-server spans by default (K4) | 模型服务器 span 默认带 `k8s.pod.name`（K4） | llm-d guides / charts |
