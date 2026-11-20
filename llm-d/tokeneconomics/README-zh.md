# llm-d Token 经济学：从每 token 成本到每个合格结果的成本

在真实硬件上，基于 llm-d 端到端实现 Tokenomics Foundation 的
[Value Attribution Data Architecture](https://www.tokeneconomics.com/projects/value-attribution-data-architecture/)
（v0.1.8）。agent 工作负载在 trace 上携带 `focus.workload.id` / `focus.task.id` / `focus.outcome.id`，
它们的 vLLM GPU 用量被关联到 FOCUS 格式的账单，以及自动判定的任务和结果上。产出是论文的五个数据集
（成本与用量 → 遥测 → 任务 → 结果 → 价值）和 KPI：每个合格任务与合格结果的成本、报废率、
每 1 美元价值的花费。两个版本都重放了 KubeCon NA 2026 的那次故障（EPP `prefix-cache-scorer` 权重
3 → 0），并给它标上价格。

English version: [`README.md`](README.md).

## 两个版本

| | [`nonk8s/`](nonk8s/README-zh.md)：不使用 Kubernetes 的 llm-d | [`k8s/`](k8s/README-zh.md)：Kubernetes 上的 llm-d |
|---|---|---|
| 服务路径 | Envoy → EPP → 2 个 vLLM 容器（Docker Compose） | agentgateway → payload processor → EPP → 2 个 vLLM pod（Kind） |
| agent driver | 主机上的进程 | Kubernetes Job |
| 成本与用量 | 合成的 FOCUS 账单行，每 GPU 小时 $4，一个 GPU 作为消费范围 | **OpenCost** 分摊 API，按 pod、按分钟 |
| 故障：任务跨副本拆分 | 0% → 51% | 1% → 45% |
| 故障：每个合格结果成本 | **+22%** | **+10%** |
| 故障：容量 | −15% | −13% |
| 对未受影响负载的溢出效应 | 每 token 成本 +43% | +16% |
| 空闲容量 | 无（满负载） | **占账单 52%**（4 个 GPU 单元中 2 个未分配） |
| 带标识调用的关联率 | 2,953 / 2,953 | 2,923 / 2,923 |

两个版本里，support_bot 的任务门都是 100% 通过，但只有约 35% 的结果合格。因此它的价值为负，而它的
GPU 账单不到 $0.50。对小模型来说，决定经济性的是质量，而不是 GPU 价格。

## 目录结构

```
tokeneconomics/
├── README.md / README-zh.md     本总览
├── docs/
│   ├── design.md / design-zh.md 设计文档（共用）
│   └── findings.md              全部发现，中英文对照
├── tokeneconomics/              共用的 Python 包（只用标准库）
├── scripts/trace-tree.py        共用工具
├── tests/                       离线单元测试（CI 会运行）
├── nonk8s/                      版本 1：报告、配置、脚本、结果、命令输出记录、截图
└── k8s/                         版本 2：报告、OpenCost values、manifests、脚本、结果、命令输出记录、截图
```

所有命令都在本目录下运行，例如 `nonk8s/scripts/run-demo.sh 300 12` 或 `k8s/scripts/run-demo.sh 300 12`。

## 上游后续工作

- llm-d-router [#4378](https://github.com/llm-d/llm-d-router/issues/4378)：把白名单内的 W3C baggage
  （`focus.*`）记录为 EPP request span 的属性。
- vLLM：在请求 span 上补充缓存 token 数、响应模型名和批处理感知的 GPU 时间。
- llm-d-router：KV 事件追踪单独采样（它会淹没 Jaeger，见发现 K2）。
- Tokenomics Foundation / FOCUS SemConv WG：提交以下内容：vLLM 会延续调用方 trace 的证据、
  自建推理的 ActivityWeight、用量口径的 KPI，以及本仓库的代码和数据，作为参考实现。

完整列表与证据：[`docs/findings.md`](docs/findings.md)。
