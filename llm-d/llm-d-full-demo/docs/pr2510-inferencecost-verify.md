# Verifying llm-d PR #2510: OpenCost inference-cost recipe on the Kind stack

- PR: <https://github.com/llm-d/llm-d/pull/2510> — `Added recipe for inference cost` (branch `simanadler:cost-v1-small`, commit `717daa2`)
- Companion OpenCost change (already merged): <https://github.com/opencost/opencost/pull/3845>
- Verified: 2026-09-16, on the Kind cluster built by this folder's [README](../README.md). The environment is kept, see [§7](#7-environment-is-kept-how-to-look-at-it).
- 中文版：[pr2510-inferencecost-verify-zh.md](pr2510-inferencecost-verify-zh.md)

## 0. One-line verdict

**The OpenCost side works; the PR's installer does not, as shipped.** Run exactly as the README says
(`./install-opencost.sh --image ghcr.io/opencost/opencost:develop-latest@sha256:e0c0… -y`), the script
deploys OpenCost and then **dies silently** before running any of its own checks, leaving an orphaned
`kubectl port-forward` behind — and the prices it just printed and "confirmed" are **silently replaced by
the Helm chart's placeholder prices** ($1.25/core-hr, $0.50/GiB-hr), so every `$` number it produces is
wrong by 40–120×. Both are one-to-five-line fixes; with them applied the script completes, the config
checks run, and OpenCost emits correct `llm_*` gauges and REST results for real traffic.

| What | Result |
| --- | --- |
| `helm install` of OpenCost with `INFERENCE_COST_ENABLED=true` | works, pod `2/2 Running` |
| Installer completes and runs its llm-d config checks | **No** — exits silently at `(( i++ ))` under `set -e` (line 300) |
| Prices the installer prints are the prices OpenCost uses | **No** — chart's `customPricing.costModel` defaults win; `node_cpu_hourly_cost` = **1.25** instead of 0.031611 |
| `llm_total_hourly_cost` for 2 sim pods (2 cores, 5 GiB each) | **$11.52/hr** as shipped → **$0.159/hr** after fix |
| `llm_cost_per_million_tokens`, `/inferenceCost/total`, `/inferenceCost/timeseries` after 30 requests | works: 1440 prompt / 3600 generation tokens (exactly 30 × 48 / 30 × 120), `allocation_method=compute_time` |
| `llm_*` gauges scraped into Prometheus via the ServiceMonitor | works (`release: llmd` label matches) |
| `metrics-config` label whitelist ConfigMap | has no effect (wrong key format **and** never loaded by the collector); would break the join if it ever did |
| Installer's model-name check (#4) | skipped on this guide ("Could not compare") — it filters pods by a label this guide doesn't set, so it misses the real `Qwen/Qwen2.5-0.5B-Instruct` ≠ `Qwen2.5-0.5B-Instruct` mismatch |
| README statements about `install-prometheus-grafana.sh` and `--served-model-name` | not true on this branch (they were part of #1926 that this PR deliberately drops) |

Concrete patch for all of it: [pr2510-inferencecost-fix.diff](pr2510-inferencecost-fix.diff) (verified end-to-end, [§5](#5-the-fixes-verified)).

## 1. What the PR adds

8 files, +1320/−2. No code, only a recipe:

| File | Role |
| --- | --- |
| `guides/recipes/observability/inferencecost/install-opencost.sh` | 783-line installer/validator: detects Prometheus, prompts for prices, writes 2 ConfigMaps, `helm install opencost-charts/opencost`, then port-forwards to Prometheus and runs 5 config checks |
| `…/manifests/metrics-config.yaml` | ConfigMap `metrics-config` with an OpenCost `kube_pod_labels` whitelist |
| `…/values/opencost-base.yaml`, `opencost-with-prometheus.yaml` | "reference" Helm values — **not read by the installer** (it generates its own values inline) |
| `…/values/prometheus-test.yaml`, `test-guide.md` | an isolated OpenShift test setup using the standalone `prometheus` chart (not tested here — no OpenShift) |
| `…/README.md` | recipe docs |
| `docs/operations/observability/metrics.md` | documents the three `llm_*` gauges; references a Grafana dashboard `llm-d-inference-cost.json` that **is not in this PR** |

The OpenCost side (`INFERENCE_COST_ENABLED`, `INFERENCE_MODEL_LABEL=llm-d.ai/model`, …) joins vLLM's
`vllm:*_tokens_total{model_name}` with pod allocation cost grouped by the `llm-d.ai/model` label and emits
`llm_total_hourly_cost`, `llm_cost_per_million_tokens`, `llm_cache_savings_fraction`.

## 2. Environment

| Component | Value |
| --- | --- |
| Kind cluster `llm-d`, 1 node (arm64, 14 CPU, 23 GiB) | Kubernetes v1.35.0 |
| kube-prometheus-stack | chart 91.2.1, release `llmd`, ns `llm-d-monitoring`, KSM v2.20.0, **no** `metricLabelsAllowlist` |
| llm-d | `llm-d-router-gateway` chart, agentgateway v1.1.0, 2× `precise-prefix-vllm` (vLLM sim, CPU), EPP with `PodMonitor decode` scraping vLLM |
| vLLM pod labels | `llm-d.ai/model=Qwen2.5-0.5B-Instruct`, `llm-d.ai/role=decode` — **no** `llm-d.ai/inference-serving`, no `llm-d.ai/inference-shared` anywhere |
| vLLM metric label | `model_name="Qwen/Qwen2.5-0.5B-Instruct"` (the sim's `--model`, no `--served-model-name`) |
| OpenCost | chart `opencost-2.5.31`, image `ghcr.io/opencost/opencost:develop-latest@sha256:e0c09b26…` as the README specifies, UI `opencost-ui:1.121.2` |
| Tools | helm 3, kubectl, jq, `/opt/homebrew/bin/bash` 5.3 (also checked `/bin/bash` 3.2) |

## 3. What I did

### 3.1 Run the installer exactly as documented

```
$ git clone -b cost-v1-small https://github.com/simanadler/llm-d.git
$ ./guides/recipes/observability/inferencecost/install-opencost.sh \
    --image "ghcr.io/opencost/opencost:develop-latest@sha256:e0c09b268d8243c45323fffec8ceea1434e9f7e982905af651b1adebfc7e3135" -y
ℹ️  Found Prometheus: http://llmd-kube-prometheus-stack-prometheus.llm-d-monitoring.svc.cluster.local:9090
  CPU ($/core-hour):             0.031611
  RAM ($/GiB-hour):              0.004237
  GPU ($/GPU-hour):              0.95  <-- most important for llm-d
ℹ️  Prices: CPU=$0.031611  RAM=$0.004237  GPU=$0.95  Storage=$0.00005479452
configmap/opencost-custom-pricing created
configmap/metrics-config created
ℹ️  OpenCost image: opencost/opencost:develop-latest@sha256:e0c0…        ← registry dropped from the log line
NAME: opencost-llm-d-monitoring … STATUS: deployed
✅ OpenCost installed.
ℹ️    kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9092:80   ← port is 9090 on kube-prometheus-stack
ℹ️  Starting temporary port-forward to Prometheus for config checks...
Forwarding from 127.0.0.1:19090 -> 9090
Forwarding from [::1]:19090 -> 9090
                                     ← nothing else, ever
```

The bash process was gone but its child survived:

```
$ ps -eo pid,ppid,command | grep -E "install-opencost|port-forward"
37777     1 kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 19090:9090
```

Because the orphan keeps stdout open, `./install-opencost.sh … | tee log` never returns. Root cause
(`start_prometheus_portforward`, line 300):

```bash
set -euo pipefail
…
  while [[ $i -lt 15 ]]; do
    if curl -sf --max-time 2 "http://localhost:${PROM_LOCAL_PORT}/api/v1/query?query=up" …; then return 0; fi
    sleep 1
    (( i++ ))      # i==0 → expression value 0 → exit status 1 → set -e kills the script
  done
```

The first `curl` always fails (port-forward isn't up yet 0 ms after `&`), so this line is hit with `i=0`
on every run:

```
$ bash -c 'set -euo pipefail; i=0; echo before; (( i++ )); echo after'
before
$ echo $?
1
```

`wait_for_prometheus_scrape`, `check_llmd_config` and `stop_prometheus_portforward` therefore never run.
The README's "the script checks: 1… 5…" has never executed on any machine.

### 3.2 What OpenCost did with the cluster as-is

Pod came up `2/2`, env correct (`INFERENCE_COST_ENABLED=true`, `INFERENCE_MODEL_LABEL=llm-d.ai/model`,
`PROMETHEUS_SERVER_ENDPOINT=http://llmd-kube-prometheus-stack-prometheus…:9090`). Logs:

```
INF Inference Cost enabled: true
INF Found configmap opencost-custom-pricing, watching...
INF ERROR UPDATING opencost-custom-pricing CONFIG: error updating provider config:
    error setting custom pricing field: no such field: Default.json in obj
INF InferenceCost: collector started (interval=2m0s)
INF InferenceCost: collected allocation costs for 1 model/namespace combinations
WRN InferenceCost: remapping metric key "Qwen/Qwen2.5-0.5B-Instruct:llm-d" → "Qwen2.5-0.5B-Instruct:llm-d"
    (model-name mismatch with allocation label)
```

Two things to note already: the pricing ConfigMap is rejected, and OpenCost `develop` has a **fallback
remap** for the `model_name` ≠ pod-label case, which is why this guide worked at all (see §4.5).

`/metrics` had the gauges, `/inferenceCost/total` answered, but with no traffic since install the token
fields were 0 — and the hourly rate was absurd for two 0.5B sim pods:

```
llm_total_hourly_cost{cost_basis="allocation",model_name="Qwen2.5-0.5B-Instruct",namespace="llm-d"} 11.522528767585754
```

### 3.3 Where $11.52/hr comes from

```
$ curl -s $PROM/api/v1/query --data-urlencode 'query=node_cpu_hourly_cost'  → 1.25
$ curl -s $PROM/api/v1/query --data-urlencode 'query=node_ram_hourly_cost'  → 0.5
```

Those are not the GCP numbers the installer printed; they are the **opencost Helm chart's placeholder
`customPricing.costModel`** (`CPU: 1.25`, `RAM: 0.50`, `storage: 0.25`). 2 pods × (2 cores × 1.25 + 6.52 GiB
× 0.50) = 11.52. ✓

Why: the chart's `customPricing.createConfigmap` defaults to **true**, so `helm install` renders its own
`ConfigMap/opencost-custom-pricing` with flat keys from `costModel`. The installer had pre-created a
ConfigMap of the same name with a single `default.json` key **and** stamped it with
`meta.helm.sh/release-name` so Helm would adopt it — so Helm merged the two:

```
$ kubectl get cm -n llm-d-monitoring opencost-custom-pricing -o jsonpath='{.data}' | jq
{
  "CPU": "1.25", "RAM": "0.5", "GPU": "0.95", "storage": "0.25", …   ← chart defaults, what OpenCost reads
  "default.json": "{ \"CPU\": \"0.031611\", \"RAM\": \"0.004237\", … }"   ← the user's prices, ignored,
                                                                              and the cause of "no such field: Default.json"
}
```

OpenCost's ConfigMap watcher applies every data key as a pricing field, so the flat chart defaults win and
`default.json` throws. Net effect: **the confirmed prices are never used**, on every install, without any
error surfaced to the user. On a real GPU cluster this is less visible (the GPU price 0.95 happens to be the
same in both), but CPU/RAM are off by 40× / 118×, and `storage` by 4,500×.

Also observed: after fixing the ConfigMap in place OpenCost logged `CustomPricing Config Updated: modified`
but kept emitting `node_cpu_hourly_cost 1.25` until the pod was restarted — node prices are computed at
startup. So prices must be right on the **first** start; "update later via `--pricing-config`" (the
installer's own hint) does not work without a rollout restart either.

### 3.4 Run the validation-only path (with the one-line fix)

With `(( i++ ))` → `i=$(( i + 1 ))` the second run (OpenCost already present) reaches the checks:

```
  [PASS] kube-state-metrics exposes llm-d.ai/model in kube_pod_labels (2 pod(s))
⚠️    [WARN] No pods found with llm-d.ai/inference-shared=true
  [PASS] vLLM token metrics (vllm:prompt_tokens_total) present in Prometheus (2 series)
⚠️    Could not compare model names (no metrics or no pods found)
  [PASS] INFERENCE_COST_ENABLED=true in OpenCost pod
✅ All checks passed — llm-d is correctly configured for OpenCost inference cost tracking.
```

Two of those lines are wrong on this cluster:

- Check #1 "kube-state-metrics exposes …" passes, but this KSM has **no** `--metric-labels-allowlist`. The
  series comes from OpenCost's **own** `kube_pod_labels` emitter, which the ServiceMonitor scrapes:
  ```
  kube_pod_labels{label_llm_d_ai_model="Qwen2.5-0.5B-Instruct", job="opencost-llm-d-monitoring", instance="10.244.0.30:9003"}
  ```
- Check #4 selects pods with `-l llm-d.ai/inference-serving=true`. This guide (and `precise-prefix-cache-routing`,
  `inference-scheduling`, … in the repo) doesn't set that label, so the check silently skips — and reports
  "All checks passed" while `model_name` is really `Qwen/Qwen2.5-0.5B-Instruct` ≠ `Qwen2.5-0.5B-Instruct`.

### 3.5 Generate traffic and read the cost metrics

```
$ kubectl run cost-drive --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d --command -- sh -c \
  'for i in $(seq 1 30); do curl -sS -o /dev/null -w "req$i http=%{http_code}\n" -X POST http://10.96.108.250:80/v1/chat/completions \
   -H "Content-Type: application/json" -d "{\"model\":\"Qwen/Qwen2.5-0.5B-Instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"Explain prefill vs decode …\"}],\"max_tokens\":120}"; done'
req1 http=200 … req30 http=200
```

One collector cycle (2 min) later:

```
$ curl -s localhost:9003/metrics | grep ^llm_
llm_cost_per_million_tokens{allocation_method="compute_time",cost_basis="allocation",phase="prompt",     …} 454.30
llm_cost_per_million_tokens{allocation_method="compute_time",cost_basis="allocation",phase="generation", …} 19.35
llm_cost_per_million_tokens{allocation_method="",            cost_basis="allocation",phase="",           …} 148.43
llm_cache_savings_fraction{model_name="Qwen2.5-0.5B-Instruct",namespace="llm-d",workload_type="inference"} 0
llm_total_hourly_cost{cost_basis="allocation",model_name="Qwen2.5-0.5B-Instruct",namespace="llm-d",…}    11.52

$ curl -s "localhost:9003/inferenceCost/total?window=1h" | jq '.data.inferenceCosts'
"Qwen2.5-0.5B-Instruct:llm-d": {
  "properties": { "modelName": "Qwen2.5-0.5B-Instruct", "namespace": "llm-d", "controller": "precise-prefix-vllm", "container": "modelserver", … },
  "promptTokens": 1440, "generationTokens": 3600, "totalTokens": 5040,
  "costPerMillionTokens": 338.26, "inputCostPerMillionTokens": 1032.75, "outputCostPerMillionTokens": 60.46,
  "allocationMethod": "compute_time", "cacheSavingsFraction": 0
}
```

Token counts are exact (30 requests × 48 prompt tokens, 30 × 120 `max_tokens`), the phase split uses vLLM's
`request_prefill/decode_time` histograms (`compute_time`), and the join key was remapped to the pod-label
name. So **the feature itself works on the Kind sim stack**; only the `$` inputs were wrong (still the
$1.25/$0.50 placeholders here — see §5 for the corrected run).

The `/inferenceCost/timeseries?…&aggregate=model_name&accumulate=hour` endpoint also works; note the hour before
OpenCost was installed comes back keyed by the *metric* name (`Qwen/Qwen2.5-0.5B-Instruct`, no allocation
data to remap against) and later hours by the *label* name — a small OpenCost quirk worth knowing when
graphing.

## 4. Findings, ranked

### 4.1 Blocker — installer exits silently, leaves an orphaned port-forward (script line 300)

`(( i++ ))` with `i=0` under `set -euo pipefail`. Symptoms: no config checks, no summary, a stray
`kubectl port-forward … 19090:9090` per run, and a hang if the script is piped. Fix: `i=$(( i + 1 ))`
(or `(( ++i ))` / `i+=1`).

### 4.2 Blocker — confirmed prices are silently replaced by the chart's placeholders

See §3.3. Fix: don't pre-create `opencost-custom-pricing`; render the confirmed prices into the values the
chart already understands:

```yaml
  customPricing:
    enabled: true
    configmapName: opencost-custom-pricing
    createConfigmap: true
    provider: custom
    costModel:
      description: "llm-d on-prem pricing (configured during install)"
      CPU: "0.031611"
      spotCPU: "0.006655"
      RAM: "0.004237"
      …
```

The installer already has the prices in `${OPENCOST_PRICING_JSON}`, so this is one `jq` line in the heredoc
(see the diff). `--pricing-config FILE` keeps working unchanged. Also document that changing prices later
needs `helm upgrade … && kubectl rollout restart deploy/opencost-<ns>`.

### 4.3 `metrics-config` whitelist: wrong key format, and a no-op today

OpenCost matches the whitelist against raw `pod.Labels` keys
([`podlabelmetrics.go`](https://github.com/opencost/opencost/blob/develop/pkg/metrics/podlabelmetrics.go):
`for lname := range pod.Labels { if _, ok := kpmc.labelsWhitelist[lname]; !ok { delete(...) } }`), i.e.
`"llm-d.ai/model": true`, not the Prometheus-sanitized `"llm_d_ai_model": true` the PR writes. Had the
whitelist taken effect, **every** label would have been dropped — including `llm-d.ai/model`, which is the
join key this whole recipe depends on.

It does not take effect, though: the collector copies `MetricsConfig` by value at registration, and the
ConfigMap watcher writes `/tmp/custom-config/metrics.json` afterwards; the file lives in the container's
`/tmp`, so it is also gone on restart. Observed after a fresh restart:

```
kube_pod_labels{label_app_kubernetes_io_part_of="llm-d",label_llm_d_ai_guide="precise-prefix-cache-routing",
                label_llm_d_ai_model="Qwen2.5-0.5B-Instruct",label_llm_d_ai_role="decode",label_pod_template_hash="5bdc47b459",…} 1
```

Recommend either dropping `manifests/metrics-config.yaml` (OpenCost emits all labels by default, which is
what makes the join work today) or fixing the keys to raw names and stating that it's best-effort.

### 4.4 Model-name check (#4) uses the wrong pod selector

`-l llm-d.ai/inference-serving=true` → use `-l llm-d.ai/model` (the label the recipe is actually about).
With that change the check correctly reports on this cluster:

```
  [FAIL] model_name mismatch between vLLM metrics and pod labels: Qwen/Qwen2.5-0.5B-Instruct
❌   Fix: add --served-model-name=<short-name> to vllm serve args, matching the llm-d.ai/model pod label
```

### 4.5 README claims that are not true on this branch

- "`install-prometheus-grafana.sh` … automatically configures kube-state-metrics to expose `llm-d.ai/*` pod
  labels" — it doesn't (`grep metricLabelsAllowlist` finds nothing outside `inferencecost/`; that change was
  in #1926 and was dropped here). Also, the allowlist is described as "required for OpenCost to join
  allocation costs by model", but OpenCost emits its own `kube_pod_labels` with all labels and the join
  worked without any KSM change. Either wire the allowlist back in or soften the text.
- "All llm-d guides set `--served-model-name=<short-name>`" — they don't (only `gpt-oss`, `tiered-prefix-cache`,
  `agentic-serving` and `multimodal` set it, and to the *long* name). OpenCost `develop` tolerates this via
  the `remapping metric key …` fallback, which the README should mention instead of "must match exactly".
- Shared-infra label `llm-d.ai/inference-shared` is set by no guide in the repo, so the "shared cost
  distribution" path is unreachable from any guide as-is (check #2 is only a WARN, fine, but worth a note).
- Verification commands use `svc/opencost`; the actual Service is `opencost-<namespace>` (the script derives
  the release name from the namespace), e.g. `svc/opencost-llm-d-monitoring`. Same in `metrics.md`.
- "File layout" says `values/opencost-base.yaml` is "applied by installer" — the installer never reads
  `values/`. `test-guide.md` and `values/prometheus-test.yaml` are missing from the layout.
- `metrics.md` adds `llm-d-inference-cost.json` to the dashboard table; no such file exists in this PR.

### 4.6 `wait_for_prometheus_scrape` always times out on kube-prometheus-stack

It polls `count(kube_state_metrics_build_info)`. KSM v2 serves that metric on its telemetry port (8081),
which the kube-prometheus-stack ServiceMonitor doesn't scrape, so it never appears and every install waits
the full 120 s. Poll something the checks actually need, e.g. `count(kube_pod_labels)` or
`count(kube_node_info)`.

### 4.7 Smaller things in the script

- `"${image_sets[@]}"` on an empty array is fatal under `set -u` with bash < 4.4 (`/bin/bash` 3.2 on macOS)
  → the no-`--image` path dies with `image_sets[@]: unbound variable`. Use `${image_sets[@]+"${image_sets[@]}"}`.
- `check_llmd_config; local check_rc=$?` — under `set -e` a failing check exits before
  `stop_prometheus_portforward`, orphaning the port-forward again. Use `check_rc=0; check_llmd_config || check_rc=$?`.
- Post-install hint `svc/${prom_svc_name} 9092:80` — kube-prometheus-stack's Prometheus Service is `9090`
  (80 is the standalone `prometheus` chart used only in `test-guide.md`).
- `OpenCost image:` log line omits the registry.
- `helm repo list | grep -q https://opencost.github.io/opencost-helm-chart` then `helm repo add opencost-charts …`
  — if the user already has the repo under another alias the install still references `opencost-charts/opencost`
  and fails; minor.

## 5. The fixes, verified

Patch: [pr2510-inferencecost-fix.diff](pr2510-inferencecost-fix.diff) (8 hunks against
`install-opencost.sh`, 1 against `manifests/metrics-config.yaml`). Round-trip on the same cluster:

```
$ ./install-opencost.fixed.sh -u                              # clean removal, release + both ConfigMaps
$ ./install-opencost.fixed.sh --image ghcr.io/opencost/opencost:develop-latest@sha256:e0c0… -y
…
ℹ️  OpenCost image: ghcr.io/opencost/opencost:develop-latest@sha256:e0c09b26…
✅ OpenCost installed.
ℹ️    kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9092:9090
✅ Port-forward to Prometheus established on localhost:19090
⚠️  Timed out waiting for Prometheus scrape — running checks anyway.      ← §4.6, not patched in the diff
  [PASS] kube-state-metrics exposes llm-d.ai/model in kube_pod_labels (2 pod(s))
⚠️    [WARN] No pods found with llm-d.ai/inference-shared=true
  [PASS] vLLM token metrics (vllm:prompt_tokens_total) present in Prometheus (2 series)
  [FAIL] model_name mismatch between vLLM metrics and pod labels: Qwen/Qwen2.5-0.5B-Instruct
❌ 1 check(s) failed. Resolve the issues above and re-run.
$ pgrep -f 'port-forward.*19090' | wc -l
0
```

And the numbers are now the ones the installer printed:

```
$ curl -s localhost:9003/metrics | grep -E '^node_(cpu|ram)_hourly_cost'
node_cpu_hourly_cost 0.031611
node_ram_hourly_cost 0.004237
$ curl -s localhost:9003/metrics | grep ^llm_total_hourly_cost
llm_total_hourly_cost{cost_basis="allocation",model_name="Qwen2.5-0.5B-Instruct",…} 0.15929625316052876
```

2 pods × (2 cores × 0.031611 + 5 GiB × 0.004237) = 0.169 ≈ 0.159 ✓ (was 11.52). `kubectl logs` shows no
`no such field` error. Window totals for the hour of the switch still blend the old placeholder samples —
expected, the allocation query reads `node_*_hourly_cost` history from Prometheus.

## 6. Suggested review comments (ready to post)

1. **`install-opencost.sh:300`** — `(( i++ ))` returns 1 when `i` is 0 and the script runs under
   `set -euo pipefail`, so `start_prometheus_portforward` kills the whole script on the first retry (the
   port-forward is never ready on the first `curl`). Every run I did ended here, with an orphaned
   `kubectl port-forward` and none of the config checks executed. `i=$(( i + 1 ))` fixes it.
2. **Pricing is silently ignored.** The chart's `customPricing.createConfigmap` defaults to `true`, so Helm
   renders its own `opencost-custom-pricing` (flat keys, `CPU: 1.25`, `RAM: 0.50`, `storage: 0.25`) and,
   because the pre-created ConfigMap carries the Helm adoption annotations, merges it over yours. OpenCost then
   uses the chart placeholders and logs `no such field: Default.json`. On my cluster that's
   `node_cpu_hourly_cost 1.25` vs the printed 0.031611 and `llm_total_hourly_cost` $11.52/hr for two 0.5B sim
   pods. Suggest dropping the pre-created ConfigMap and passing the prices via
   `opencost.customPricing.costModel` (one `jq` line in the existing heredoc); verified that gives 0.031611 /
   $0.159/hr. Also note that price changes need a pod restart to affect `node_*_hourly_cost`.
3. **`manifests/metrics-config.yaml`** — the whitelist keys must be raw label names (`llm-d.ai/model`), not
   `llm_d_ai_model`; OpenCost matches against `pod.Labels`. With the current keys, if it ever applied, it
   would strip `llm-d.ai/model` and break the join. In practice it never applies (collector snapshots the
   config at startup; the watcher writes `/tmp/custom-config/metrics.json` later) — suggest removing the file
   or fixing the keys and marking it best-effort.
4. **Check #4** filters pods by `llm-d.ai/inference-serving=true`, which most guides (incl. this one) don't
   set, so it prints "Could not compare" and the summary says "All checks passed" while `model_name` is
   really `Qwen/Qwen2.5-0.5B-Instruct`. `-l llm-d.ai/model` makes it catch the mismatch.
5. **README** — on this branch `install-prometheus-grafana.sh` does not set `metricLabelsAllowlist`, and the
   guides do not set `--served-model-name=<short-name>` (both were in #1926). OpenCost `develop` remaps the
   name (`WRN InferenceCost: remapping metric key …`), so it works, but the doc should say that rather than
   "must match exactly". `svc/opencost` → `svc/opencost-<namespace>`; `values/*.yaml` aren't used by the
   installer; `metrics.md` lists a dashboard that isn't in the PR.
6. **`wait_for_prometheus_scrape`** polls `kube_state_metrics_build_info`, which kube-prometheus-stack doesn't
   scrape (KSM v2 telemetry port) — always a 120 s timeout. Poll `kube_pod_labels` instead.
7. Minor: `"${image_sets[@]}"` breaks bash 3.2 (`/bin/bash` on macOS) when `--image` is omitted;
   `check_llmd_config; local check_rc=$?` under `set -e` leaks the port-forward on failure; the Prometheus hint
   says `9092:80` but kube-prometheus-stack listens on 9090.

## 7. Environment is kept: how to look at it

OpenCost is installed from the **fixed** script (release `opencost-llm-d-monitoring`, ns `llm-d-monitoring`).

```bash
kubectl config use-context kind-llm-d
kubectl get pods -n llm-d-monitoring -l app.kubernetes.io/name=opencost           # 2/2 Running

# gauges + REST
kubectl port-forward -n llm-d-monitoring svc/opencost-llm-d-monitoring 9003:9003 &
curl -s localhost:9003/metrics | grep ^llm_
curl -s "localhost:9003/inferenceCost/total?window=1h" | jq .
curl -s "localhost:9003/inferenceCost/timeseries?window=6h&aggregate=model_name&accumulate=hour" | jq .

# UI
kubectl port-forward -n llm-d-monitoring svc/opencost-llm-d-monitoring 9090:9090 &   # http://localhost:9090

# more traffic (sim ≈ 6 s/request), then wait ≤ 2 min for the collector
GWIP=$(kubectl get svc -n llm-d llm-d-inference-gateway -o jsonpath='{.spec.clusterIP}')
kubectl run drive --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d --command -- sh -c \
  "for i in \$(seq 1 10); do curl -sS -o /dev/null -w 'req\$i %{http_code}\n' -X POST http://$GWIP/v1/chat/completions \
   -H 'Content-Type: application/json' -d '{\"model\":\"Qwen/Qwen2.5-0.5B-Instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":64}'; done"

# in Prometheus (scraped via the ServiceMonitor)
kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9091:9090 &
curl -s localhost:9091/api/v1/query --data-urlencode 'query=llm_total_hourly_cost' | jq .

# remove
./install-opencost.fixed.sh -u        # or: helm uninstall opencost-llm-d-monitoring -n llm-d-monitoring
```

To reproduce the two blockers, run the **unpatched** script from the PR branch on any cluster: it stops after
`Forwarding from [::1]:19090 -> 9090`, and `kubectl get cm opencost-custom-pricing -o yaml` shows `CPU: "1.25"`
next to a `default.json` key.

## 8. Files added by this verification

| File | What |
| --- | --- |
| `docs/pr2510-inferencecost-verify.md` | this document |
| `docs/pr2510-inferencecost-verify-zh.md` | Chinese version |
| `docs/pr2510-inferencecost-fix.diff` | the patch for `install-opencost.sh` + `manifests/metrics-config.yaml` that the round-trip in §5 used |
