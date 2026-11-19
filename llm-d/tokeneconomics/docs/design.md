# Design: value attribution for llm-d (token-economics demo)

中文版见 [`design-zh.md`](design-zh.md).

## 1. Goal

Show, on a real llm-d stack, the full chain the Tokenomics Foundation's
[Value Attribution Data Architecture](https://www.tokeneconomics.com/projects/value-attribution-data-architecture/)
(v0.1.8, "the paper") proposes:

```
Cost and Usage  ->  Telemetry  ->  Task  ->  Outcome  ->  Value
(the GPU bill)     (who used it)  (work)    (verified)   (worth)
```

and use it to answer the questions our KubeCon NA 2026 talk ("Seeing Through the
Stack") stopped short of. That talk reached **cost per token** with OpenCost. This
demo goes three layers further: **cost per qualified task (CPQT)**, **cost per
qualified outcome (CPQO)** and **value**, using the same KubeCon incident (the
`prefix-cache-scorer` weight changed from 3 to 0).

Non-goals: a production pipeline, a finance-grade bill, or a new upstream API.
Everything runs on one DGX Spark without Kubernetes, with the Python standard
library only.

## 2. Requirements

| # | Requirement | How the demo meets it |
|---|---|---|
| R1 | Join GPU spend to business results with shared keys, not guesses | `focus.workload.id` / `focus.task.id` / `focus.outcome.id` on every model call, joined on `trace_id` |
| R2 | Work with **zero** upstream changes (the paper's "no `focus.*` from upstream" scenario) | lineage keys live on the client's root span; vLLM's own span supplies usage; we join at ingest |
| R3 | Count 100% of the bill (no happy-path bias) | `UNLINKED` and `IDLE` reserved values; failed tasks kept as scrap |
| R4 | Real quality gates, not invented pass rates | workloads whose results are checked automatically against ground truth |
| R5 | Not Kubernetes-only | runs on the `llm-d-spark-nonk8s-demo` stack (Docker Compose, file discovery); cost input is a FOCUS-shaped table you can replace with an OpenCost export |
| R6 | Reproducible | deterministic task generators (seeded), one script, outputs as CSV + SQLite |

## 3. Architecture

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

### 3.1 Where each attribution key comes from (paper section 2.2.2)

| Paper layer | Who in this demo | What it adds |
|---|---|---|
| 1. Agent harness / application | `tokeneconomics/driver.py` | `focus.workload.id`, `focus.task.id`, `focus.outcome.id` (the ticket / alert exists before the run, so the outcome id is known at start) on the root span and in W3C baggage |
| 2. Gateway, router, inference engine | Envoy, EPP, vLLM | trace context only. vLLM's `llm_request` span carries `gen_ai.usage.prompt_tokens`, `completion_tokens`, `gen_ai.latency.time_in_model_prefill/decode` |
| 3. Telemetry collector | OTel Collector | nothing extra today (could add host / GPU resource attributes) |
| 4. Enterprise enrichment | `tokeneconomics/build.py` | joins root-span keys onto the vLLM leaf span by `trace_id`; supplies the billing scope (`ServiceProviderName`, `BillingAccountId`, `ResourceId` ...) from `configs/demo.toml` |

Nothing upstream emits `focus.*` today, and nothing needs to for this demo. The
paper warns that vLLM "did not continue the caller's trace" in its authors'
testing. With `--otlp-traces-endpoint` on vLLM 0.27.1 it **does** continue it here,
which is what makes the `trace_id` join possible.

### 3.2 Why join on `trace_id` instead of reading baggage

`baggage` reaches every hop, since Envoy forwards the header, but **no component
copies baggage entries onto its spans**, and the OTel Collector cannot see
baggage. The root span is the only place the keys are recorded. A small EPP change
would put them on the router's spans as well; see [README §9](../README.md#9-future-plan).

## 4. Data model mapping

All five tables follow the paper's column names (section 3). Columns the paper
does not define are prefixed `x_`, as FOCUS does for custom columns.

### 4.1 CostAndUsage: a bill for a self-hosted GPU

A self-hosted GPU has no cloud invoice, so the demo synthesizes FOCUS rows. Each
charge period gets one row for the GPU, with
`EffectiveCost = gpu_hourly_usd × period / 3600` (`PricingCategory = Committed`,
`ConsumedUnit = GPU Hours`).

* **Consumption Scope** = provider + billing account + `ResourceId = spark-3bee/gpu0`.
  Both vLLM replicas share this one GPU, so they are one scope. The replica is
  kept as `x_ServingReplica` on Telemetry.
* **Charge period**: 60 s (configurable). FOCUS bills hourly or daily. The demo
  compresses time so that each phase spans several periods.
* **Kubernetes**: replace this table with OpenCost's FOCUS export, keyed by
  node / GPU. **Without Kubernetes**: amortized hardware + power + operations per
  GPU-hour, which is what `demo.toml` encodes.

### 4.2 Telemetry: leaf spans and ActivityWeight

* **Leaf span for the GPU scope** = vLLM `llm_request`. It is the deepest span
  that consumed the billed resource (paper section 2.3.1). Envoy and EPP spans are
  not counted toward GPU cost.
* **Row grain** = (charge period, WorkloadId, TaskId, OutcomeId, replica).
  `trace_id` / `span_id` are dropped after the join.
* **`CacheReadTokenCount`** comes from the client: vLLM returns
  `usage.prompt_tokens_details.cached_tokens` (with
  `--enable-prompt-tokens-details`), and the driver stamps it on its root span as
  `gen_ai.usage.cache_read.input_tokens`. vLLM's span has no cache attribute.
* **`ActivityWeight`**: the paper suggests token-price weighting (output 3-5×
  input, cached reads 0.1×), which fits pay-per-token APIs. For a self-hosted
  engine the cost driver is GPU time, so the default is
  `method = "gpu_time"`: `time_in_model_prefill + time_in_model_decode` as measured
  by vLLM. `method = "tokens"` is available for comparison.
  **Caveat:** under continuous batching, requests share forward passes, so the sum
  of per-request model time exceeds wall-clock GPU time. As a *relative* weight
  inside one period it is still a fair split, but it should not be read as
  absolute GPU-seconds.
* **`IDLE`**: a charge period with no activity becomes an `IDLE` row that keeps
  its cost, instead of disappearing (the paper's open question in section 2.3.2).
  Inside an active period, idle capacity is spread over the users, as the paper
  describes.

### 4.3 Task and Outcome: the two gates

| Workload | Task (Gate 1, in flight) | Outcome (Gate 2, after delivery) |
|---|---|---|
| `support_bot`: billing dispute agent. Long (~3.9k-token) unique invoice history per ticket; step 1 *investigate*, step 2 *tool call* on the same conversation, up to 2 retries | The refund-calculator call is well formed **and** its `amount_usd` matches an invoice that exists for that plan (the tool validates it against the record) | The refund is correct to the cent, i.e. the agent used the **most recent** invoice. Otherwise the customer reopens the ticket inside the settlement window |
| `triage_bot`: alert triage. ~250-token prompt, one call | JSON with allowed labels | Severity **and** component match ground truth; otherwise the alert is re-escalated |
| playground | none: no keys, so `UNLINKED` | none |

Units and human costs follow the paper's section 2.4.3:

* Task quantities are in **minutes**: `Baseline` = a human doing the work,
  `Observed` = minutes the AI delivered, `Friction` = human review even when it
  passes, `Rework` = human clean-up when it fails.
* `support_bot` Outcomes are a discrete unit (`deflected_tickets`), so minutes
  cannot be subtracted from them. Friction and rework are monetized as a
  **separate negative Value claim** (`Friction and Rework`) under the same CFO
  lens.
* `triage_bot` Outcomes are in minutes, so friction and rework roll up from the
  Task and the recall cost is subtracted directly.

Settlement: an Outcome is `Pending` until `window_seconds` after its Task ends,
then `Settled` (frozen). Recalls inside the window update the Pending entry; the
demo never needs an amending entry.

### 4.4 Value

| Workload | Stakeholder | Category | Multiplier | Status |
|---|---|---|---|---|
| support_bot | CFO | Cost Reduction | $8.50 per deflected ticket | Reported |
| support_bot | CFO | Friction and Rework | −$1.50 per human minute | Reported |
| triage_bot | CTO | Engineering Capacity | $1.50 per net minute | Reported |

All claims are `Reported`, never `Booked`: there is no independent attestor in a
demo. `RealizedValue` is set only for Settled outcomes. `PlannedValue` encodes the
business case (90% qualified).

### 4.5 KPIs (`tokeneconomics/kpis.sql`)

`kpi_infra` (paper section 4.1), `kpi_workload` (sections 4.2-4.4), `kpi_phase`
(portfolio, scrap rate with `UNLINKED` as its own line, `IDLE` kept apart). Two
deliberate deviations:

* **GPU-s per qualified outcome** sits next to CPQO. On a fixed-price GPU, an
  incident that wastes GPU time does not change the bill in the same period; it
  consumes capacity. GPU-s/QO shows that waste in physical units, independent of
  how the bill is spread.
* **Spend per $1 of value** replaces ROI %. With a 1.5B model on one GPU, compute
  cost is tiny next to human labor, so ROI percentages become meaningless huge
  numbers.

## 5. Experiment design

| Phase | EPP config | Expected |
|---|---|---|
| `baseline` | `prefix-cache-scorer` weight 3 (upstream default) | step 2 / retries land on the replica that holds the ticket's prefix: high KV hit ratio, short prefill |
| `incident` | weight 0 (the KubeCon bad config) | follow-up steps scatter across replicas: lower hit ratio, more prefill GPU time per qualified outcome. The gates are unaffected, so the *quality* KPIs should not move |

Same seed, concurrency and duration in both phases. `scripts/run-demo.sh` runs
both phases, restores weight 3, waits out the settlement window, then builds the
datasets and the report.

## 6. Known limitations

* Small numbers: one GB10 with a 1.5B model costs cents per phase, so costs are
  shown with 4-5 decimals. They scale linearly with `gpu_hourly_usd`.
* Summed per-request model time over-counts under batching (section 4.2).
* `UNLINKED` calls have no root span, so their cached tokens are unknown
  (reported as 0).
* The EPP span is a sibling of Envoy's span under the client root, not a child
  (`llm-d-spark-nonk8s-demo` §10.2). This does not affect the join, because both
  hang under the driver's root.
* There is no P/D disaggregation and no tiered KV offload, so one GPU scope and
  one cache tier.
