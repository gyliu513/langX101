# llm-d Token Economics: from cost per token to cost per qualified outcome

An end-to-end implementation, on real hardware, of the Tokenomics Foundation's
[Value Attribution Data Architecture](https://www.tokeneconomics.com/projects/value-attribution-data-architecture/)
(v0.1.8) on top of llm-d. Agent workloads carry `focus.workload.id` / `focus.task.id` /
`focus.outcome.id` on their traces. Their vLLM GPU usage is joined to a FOCUS-shaped bill
and to automatically judged Tasks and Outcomes. The results are the paper's five datasets
(Cost and Usage → Telemetry → Task → Outcome → Value) and its KPIs: cost per qualified
task and outcome, scrap rate, and spend per dollar of value. Both variants replay the
KubeCon NA 2026 incident (EPP `prefix-cache-scorer` weight 3 → 0) to price it.

中文版见 [`README-zh.md`](README-zh.md).

## Two variants

| | [`nonk8s/`](nonk8s/README.md): llm-d without Kubernetes | [`k8s/`](k8s/README.md): llm-d on Kubernetes |
|---|---|---|
| Serving path | Envoy → EPP → 2 vLLM containers (Docker Compose) | agentgateway → payload processor → EPP → 2 vLLM pods (Kind) |
| Agent driver | a host process | a Kubernetes Job |
| Cost and Usage | synthesized FOCUS rows, $4 per GPU-hour, one GPU scope | **OpenCost** allocation API, per pod per minute |
| Incident: tasks split across replicas | 0% → 51% | 1% → 45% |
| Incident: cost per qualified outcome | **+22%** | **+10%** |
| Incident: capacity | −15% | −13% |
| Spill-over on an unaffected workload | +43% cost per token | +16% |
| Idle capacity | none (fully loaded) | **52% of the bill** (2 of 4 GPU units unallocated) |
| Linked calls joined | 2,953 / 2,953 | 2,923 / 2,923 |

In both variants, support_bot passes its Task gate 100% of the time but only about 35% of
its Outcomes survive. That makes its value negative, while its GPU bill is under $0.50.
For a small model, quality decides the economics, not GPU price.

## Layout

```
tokeneconomics/
├── README.md / README-zh.md     this overview
├── docs/
│   ├── design.md / design-zh.md design document (shared)
│   └── findings.md              all findings, English / Chinese side by side
├── tokeneconomics/              shared Python package (standard library only)
├── scripts/trace-tree.py        shared tool
├── tests/                       offline unit tests (run by CI)
├── nonk8s/                      variant 1: report, configs, scripts, results, captures, screenshots
└── k8s/                         variant 2: report, OpenCost values, manifests, scripts, results, captures, screenshots
```

Run every command from this folder, for example `nonk8s/scripts/run-demo.sh 300 12` or
`k8s/scripts/run-demo.sh 300 12`.

## Upstream follow-ups

- llm-d-router [#4378](https://github.com/llm-d/llm-d-router/issues/4378): record allowlisted
  W3C baggage (`focus.*`) as attributes on the EPP request span.
- vLLM: cached tokens, response model and batch-aware GPU time on the request span.
- llm-d-router: sample KV-event tracing separately (it floods Jaeger, finding K2).
- Tokenomics Foundation / FOCUS SemConv WG: evidence that vLLM continues the caller's trace,
  a self-hosted ActivityWeight, a usage-basis KPI, and this code and data as a reference
  implementation.

Full list with evidence: [`docs/findings.md`](docs/findings.md).
