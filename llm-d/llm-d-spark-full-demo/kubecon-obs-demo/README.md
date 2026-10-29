# KubeCon demo screenshots: from a TTFT alert to its root cause

This folder reproduces, on a real GPU, the incident walked through in the
KubeCon NA 2026 talk *Seeing Through the Stack: End-to-End Observability for
llm-d* (slides 17, 19 and 20), and holds the screenshots taken from that run.

The story in one paragraph: P99 time to first token (TTFT) triples and an SLO
alert fires, while every pod is healthy. A Grafana exemplar on the TTFT panel
links to the trace of one slow request. In that trace the KV-cache index says
the full prompt prefix is cached on one pod and the prefix scorer gives that
pod a perfect score, but the scorer's weight is **0**, so the load scorers
pick the other pod and vLLM recomputes the whole 3.8k-token prefill (569 ms
instead of 52 ms). `helm history` and a one-line config diff show who set the
weight to 0. Every number below and in the screenshots comes from that run.

Everything runs on the same DGX Spark as the parent demo, in a second Kind
cluster, `llm-d-obs`, built with the parent's GPU recipe
([`../README.md`](../README.md) Steps 1-5) and pinned to **llm-d v1.0** and
**llm-d-router v1.0.0**.

- [The screenshots](#the-screenshots)
- [The scenario](#the-scenario)
- [How to run it](#how-to-run-it)
- [What happened in the run (timeline and numbers)](#what-happened-in-the-run)
- [How each screenshot was made](#how-each-screenshot-was-made)
- [Findings along the way](#findings-along-the-way)
- [Files](#files)

---

## The screenshots

| File | Slide | Shows |
| --- | --- | --- |
| [`screenshots/s19-1-alert-firing.png`](screenshots/s19-1-alert-firing.png) | 19, step 1 | Prometheus *Alerts*: the `LLMDTTFTP99OverSLO` rule firing, value 0.618 s against a 250 ms threshold |
| [`screenshots/s17-s19-2-grafana-ttft-exemplar.png`](screenshots/s17-s19-2-grafana-ttft-exemplar.png) | 17, and 19 step 2 | Grafana: P99/P50 of `llm_d_epp_request_ttft_seconds` from 00:10 to 00:25; P99 jumps from ~0.2 s to ~0.6 s at 00:18:45. Hovering the highest exemplar diamond shows its labels, `trace_id a4f86e2f…`, and the *Open in Jaeger UI* link |
| [`screenshots/s19-3-jaeger-trace-annotated.png`](screenshots/s19-3-jaeger-trace-annotated.png) | 19, step 3 | Jaeger: that trace (gateway → EPP → vLLM, 18 spans). A = `match_block_keys` (`longest_chain 59`, `pods_matched 1`), B = `scorer.prefix-cache-scorer` (`score.max 1`, `weight 0`), C = vLLM `llm_request` (`time_in_model_prefill 0.569`, `time_to_first_token 0.765`, `prompt_tokens 3829`) |
| [`screenshots/s20-4-logs-by-trace-id.png`](screenshots/s20-4-logs-by-trace-id.png) | 20, step 4 | `kubectl logs deploy/llm-d-epp \| jq 'select(.trace_id=="a4f86e2f…")'`: the three EPP log lines of that request |
| [`screenshots/extra-grafana-dashboard-ttft-and-hit-rate.png`](screenshots/extra-grafana-dashboard-ttft-and-hit-rate.png) | (backup) | The whole dashboard at the same moment: the TTFT panel above the per-pod vLLM prefix-cache hit rate, which drops from ~100 % to ~65 % at the change |
| [`screenshots/s20-5-root-cause.png`](screenshots/s20-5-root-cause.png) | 20, step 5 | `helm history` (revision 4 at 00:18:07), the one-line diff between the two EPP configs (`weight: 3.0` → `0.0`), and the same attributes from a trace taken with weight 3.0 next to the slow one |

The same request (`trace_id a4f86e2fec8c185a0d94f4bf28e61697`, 2026-10-26
00:21:52 EDT) appears in the Grafana tooltip, the Jaeger trace and the logs.

## The scenario

### Stack

| Piece | Version / setting |
| --- | --- |
| Kind cluster `llm-d-obs` | `kindest/node:v1.37.0`, GB10 GPU time-sliced ×4 ([`kind-config.yaml`](kind-config.yaml), [`../manifests/00-gpu-runtime.yaml`](../manifests/00-gpu-runtime.yaml)) |
| Gateway | agentgateway v1.4.1 (Gateway API + Inference Extension), root span exported ([`../manifests/03-gateway-tracing-policy.yaml`](../manifests/03-gateway-tracing-policy.yaml)) |
| Router | chart `oci://ghcr.io/llm-d/charts/llm-d-router-gateway` **v1.0.0**, EPP image `llm-d-router-endpoint-picker:v1.0.0` ([`helm-values/router-obs.values.yaml`](helm-values/router-obs.values.yaml)) |
| EPP plugin chain | precise prefix cache (KV events from vLLM) + three weighted scorers: `kv-cache-utilization-scorer` 2.0, `queue-scorer` 2.0, `prefix-cache-scorer` **3.0** ([`helm-values/epp-config-before.values.yaml`](helm-values/epp-config-before.values.yaml)) |
| Model servers | 2 × vLLM 0.27.1 (NGC `nvcr.io/nvidia/vllm:26.08-py3`), `Qwen/Qwen2.5-1.5B-Instruct`, `--block-size=64`, **3 GiB KV cache each (~112k tokens)**, KV events + OTLP spans ([`manifests/02-model-servers-obs.yaml`](manifests/02-model-servers-obs.yaml)) |
| Tracing | llm-d v1.0 `install-otel-collector-jaeger.sh` (Collector → in-memory Jaeger), EPP sampling 1.0 ([`helm-values/tracing.values.yaml`](helm-values/tracing.values.yaml)) |
| Metrics | llm-d v1.0 `install-prometheus-grafana.sh`, which finds Jaeger and wires exemplar storage + `exemplarTraceIdDestinations` |
| Alert | [`manifests/ttft-slo-rule.yaml`](manifests/ttft-slo-rule.yaml): P99 of `llm_d_epp_request_ttft_seconds` over 2 m `> 0.25` for 2 m |
| Dashboard | [`grafana/ttft-exemplars-dashboard.json`](grafana/ttft-exemplars-dashboard.json): P99/P50 TTFT with `exemplar: true`, plus per-pod prefix-cache hit rate. None of the shipped llm-d dashboards has a TTFT panel, so this one is our own |

### Traffic

[`scripts/session-traffic.py`](scripts/session-traffic.py), run in-cluster by
[`manifests/session-traffic.yaml`](manifests/session-traffic.yaml): 44
"sessions", each with its own ~3.8k-token system prompt, 3 concurrent
streamed requests (`max_tokens 24`), each picking a session at random.

The sizes are chosen so routing matters:

- all 44 prefixes together ≈ 168k tokens, more than one replica's 112k-token
  KV cache;
- half of them (what each replica holds when every session sticks to one
  replica) ≈ 84k tokens, which fits.

So with prefix-aware routing almost every request is a cache hit; without it,
both replicas see every session, LRU evicts, and prefill comes back.

### The incident

A `helm upgrade` from [`epp-config-before.values.yaml`](helm-values/epp-config-before.values.yaml)
to [`epp-config-after.values.yaml`](helm-values/epp-config-after.values.yaml),
which differ in one line: the `prefix-cache-scorer` weight in the scheduling
profile goes from 3.0 to 0.0. The scorer still runs and still reports its
score on the span (that is what makes the cause visible in the trace), but the
score no longer counts; ties go to whatever the load scorers say.

## How to run it

On the Spark, with the host prerequisites from [`../README.md`](../README.md)
Steps 1-2 in place, the llm-d repo at `~/llm-d`, and this folder at
`~/llm-d-spark-full-demo/kubecon-obs-demo`:

```console
$ git -C ~/llm-d worktree add ~/llm-d-v1.0 v1.0          # llm-d v1.0 recipes
$ cd ~/llm-d-spark-full-demo/kubecon-obs-demo
$ ./scripts/create-cluster.sh                            # Kind + GPU + vLLM image import (~6 min)
$ ./scripts/install-stack.sh                             # gateway, router v1.0.0, vLLM, tracing, Prometheus/Grafana, rules (~4 min)
$ (cd .. && ./scripts/port-forward.sh)                   # Jaeger :16686, Prometheus :9091, Grafana :3000, Gateway :8080
$ curl -s -u admin:admin -H 'Content-Type: application/json' localhost:3000/api/datasources | jq -r '.[] | select(.type=="prometheus") | .uid'
$ sed "s/\${DS_UID}/<that uid>/g" grafana/ttft-exemplars-dashboard.json \
    | curl -s -u admin:admin -H 'Content-Type: application/json' -X POST localhost:3000/api/dashboards/db -d @-
```

GB10 has unified memory: check what CUDA can actually allocate before Step 9
(see the parent README §3). On this run ComfyUI was holding 41 GB of cached
models with an empty queue; its `/free` endpoint released them without
stopping it (CUDA free memory 6.9 GB → 51.5 GB).

Then the incident itself:

```console
# phase A: healthy baseline (~10 min)
$ kubectl -n llm-d create configmap session-traffic --from-file=scripts/session-traffic.py
$ kubectl apply -f manifests/session-traffic.yaml
$ kubectl -n llm-d logs -f deploy/session-traffic        # one line per 30 s: p50/p90/p99 TTFT seen by the client

# the "bad change"
$ helm upgrade llm-d oci://ghcr.io/llm-d/charts/llm-d-router-gateway --version v1.0.0 \
    -f helm-values/epp-config-after.values.yaml -f helm-values/tracing.values.yaml -f helm-values/router-obs.values.yaml \
    --set provider.name=none --set httpRoute.create=true --set httpRoute.inferenceGatewayName=llm-d-inference-gateway -n llm-d

# phase B: wait ~3 min for the alert (2 m rate window + for: 2m)
$ curl -s localhost:9091/api/v1/alerts | jq -r '.data.alerts[] | "\(.labels.alertname) \(.state) \(.value)"'
```

Revert by running the same `helm upgrade` with `epp-config-before.values.yaml`.

### Choosing the demo request

Grafana draws only a subset of the exemplars (it thins them per query step),
so the request has to be one of the diamonds on screen. We hovered the
highest diamond after the change, read its `trace_id` from the tooltip, and
checked in Jaeger that it shows the cause (prefix cached on one pod, weight 0,
long prefill). `scripts/capture-ui.py` then finds the diamond carrying that
`trace_id` and screenshots its tooltip.

To list candidates from the API instead:

```console
$ curl -s localhost:9091/api/v1/query_exemplars --data-urlencode 'query=llm_d_epp_request_ttft_seconds_bucket{namespace="llm-d"}' \
    --data-urlencode "start=$(($(date +%s)-600))" --data-urlencode "end=$(date +%s)" \
  | jq -r '.data[].exemplars[] | "\(.value) \(.labels.trace_id)"' | sort -rn | head
```

## What happened in the run

All times EDT, 2026-10-25/26.

| Time | Event |
| --- | --- |
| 23:43 | Stack installed (helm revision 1), smoke test OK, vLLM `0.27.1` on the GB10 |
| 00:01 | First attempt: prefix weight 3.0 → **0.5** (rev 2). **No effect**: the queue scorer reads the *waiting* queue, which stays 0 at this load, so the load scorers tie and even a 0.5 prefix weight still decides. TTFT and the 99 % hit rate did not move. Reverted at 00:06 (rev 3) and restarted the traffic from a clean state |
| 00:07 | Phase A starts: 44 sessions. Client TTFT p50 0.09-0.12 s, p99 0.15-0.16 s; vLLM prefix-cache hit rate **99.1 %** |
| 00:18:07 | Rev 4: prefix weight **0.0**. The EPP rollout causes ~1 s of HTTP 500s (see findings) |
| 00:19 | Client p99 0.5-0.8 s, p90 ~0.45 s, p50 0.13-0.16 s; hit rate drops to **64-65 %**; EPP P99 TTFT (Prometheus, 2 m) **~0.60 s** |
| 00:19:04 | `LLMDTTFTP99OverSLO` pending, **firing** two minutes later (value 0.615) |
| 00:21:52 | The demo request `a4f86e2f…`: TTFT 0.765 s, prefill 0.569 s for 3829 prompt tokens |
| 00:33 | Grafana, Prometheus and Jaeger captured |
| 00:42:44 | Rev 5: weight back to 3.0; the session traffic keeps running |
| 07:09:37 | The "before" trace `ee729b07…` is taken from that traffic, still on rev 5 (weight 3.0): prefill 52 ms. It is the first trace returned by a Jaeger query for requests after the revert that has `llm_request`, `scorer.prefix-cache-scorer` and `match_block_keys`, `pods_matched == 1` and prefill under 0.1 s. It is a different session from `a4f86e2f…` (3,839 vs 3,829 prompt tokens), so it is the same kind of request, not the same prompt |

The two traces side by side (`scripts/compare-traces.py traces/before-ee729b07.json traces/after-a4f86e2f.json`):

```text
                              prefix w=3.0    prefix w=0.0
trace_id                          ee729b07        a4f86e2f
longest_chain                           59              59
pods_matched                             1               1
prefix scorer weight                     3               0
prefix scorer score.max                  1               1
picker top_scores             [6.93, 3.86]    [3.93, 3.86]
vLLM prefill                         52 ms          569 ms
vLLM TTFT                            66 ms          765 ms
```

The two traces are different chat sessions of the same traffic, so this compares the same kind of request (one session's ~3.8k-token system prompt), not the same prompt. The index sees the same thing in both (59 of 59 blocks cached on one pod).
With weight 3.0 that pod wins by 3 points; with weight 0.0 the two pods are
0.07 apart on load alone and the request lands on the one without the
prefix. Both full traces are saved under [`traces/`](traces/) because the
in-memory Jaeger drops old traces within ~20 minutes at this request rate.

## How each screenshot was made

All UI screenshots were taken on the Spark with headless Chromium
(Playwright) against the port-forwards, at device scale factor 2, light
theme. Nothing was edited except cropping, the A/B/C annotations, and hiding
some tag rows in Jaeger (below).

**Alert** — `scripts/capture-ui.py` opens `/alerts?search=LLMDTTFT` on
Prometheus, expands the rule and screenshots the page; the image is the rule
card cropped out of it.

**Grafana panel** — the dashboard above in `viewPanel` + `kiosk` mode, light
theme, absolute range 00:10:00-00:25:00 (so the calibration warm-up, whose
first request took 33 s, is out of frame). The script collects the exemplar
markers (`data-testid="data-testid Exemplar marker"`), hovers them by mouse
coordinates (an open tooltip covers its neighbours, so it moves away and
presses Escape in between, and waits ~1.3 s for the tooltip), and saves the
frame where the tooltip shows the chosen `trace_id` (that run rendered the
whole dashboard, kept as the *extra* image above). The slide image is the
single-panel view from [`scripts/hover-top-exemplar.py`](scripts/hover-top-exemplar.py),
which hovers the highest diamond after the change; that diamond is the
`a4f86e2f…` exemplar. Before the change the
panel's P99 reads a flat ~200 ms: the slowest 1 % fall in the 0.1-0.2 s
histogram bucket and `histogram_quantile` interpolates to near its top; the
client measured 0.15-0.16 s.

**Jaeger** — the trace page at a 1100 px viewport with the span-name column
dragged wider (so names are not truncated).
[`scripts/capture-jaeger.py`](scripts/capture-jaeger.py) saves the span tree,
then expands `match_block_keys`, `scorer.prefix-cache-scorer` and
`llm_request` one at a time and screenshots each one's *Tags* table with the
other tags hidden (Jaeger has no tag filter; the hidden rows are fairness,
endpoint counts and the like). [`scripts/compose-jaeger.py`](scripts/compose-jaeger.py)
pastes the three tables, enlarged 1.4×, next to their rows and boxes them A,
B, C. At slide size a full-width Jaeger screenshot is unreadable; this keeps
the evidence legible.

**Logs and root cause** — real command output, saved to text right after the
run, drawn as a terminal window by [`scripts/render-terminal.py`](scripts/render-terminal.py)
(monospace, 2× scale, diff colouring, the trace id and key values
highlighted). The logs are from the revision-4 EPP pod; that pod was replaced
at the revert, so they cannot be re-read today.

## Findings along the way

1. **agentgateway + router v1.0.0: every request counts as an error.**
   `llm_d_epp_request_error_total{error_code="ModelServerError"}` grew at the
   same rate as `llm_d_epp_request_total` (ratio 0.997), so the shipped
   `EPPHighErrorRatio` and `EPPCriticalErrorRatio` alerts fired from the
   first minute, and the EPP `request` span is marked `ERROR /
   ModelServerError` (the red icon in the Jaeger screenshot), while every
   client got HTTP 200 and a complete stream. `pkg/epp/handlers/server.go`
   flags the error when the `:status` response header's `RawValue` is not
   `"200"` (added for Envoy in llm-d-router#3330, still the same on `main`);
   agentgateway appears to send the status in `Value`, leaving `RawValue`
   empty (confirmed in agentgateway `crates/agentgateway/src/http/ext_proc/headers.rs`,
   v1.4.1 and `main`). Filed as
   [llm-d/llm-d-router#3641](https://github.com/llm-d/llm-d-router/issues/3641).
2. **An EPP rollout drops about a second of traffic.** Each `helm upgrade`
   restarted the single EPP replica; agentgateway logged `ext_proc failed:
   ... Connection refused` and returned 500 for ~1 s (65-112 requests at
   this load with 1 s client backoff; without backoff the generator spun
   57k errors in that second). With `failureMode: FailOpen` one might
   expect fail-open here; it is the ext_proc *connect* failing.
3. **A modest weight change may do nothing.** Dropping the prefix weight to
   0.5 had no effect, because `queue-scorer` reads the waiting queue, which
   is empty below saturation, so the load scorers tie. Worth knowing when
   tuning weights: the trace's `llm_d.epp.picker.top_scores` shows by how
   much each decision was won.
4. **Related gaps the demo runs into**, tracked upstream: P/D sidecar
   connector logs carry no `trace_id`
   ([llm-d/llm-d-router#3629](https://github.com/llm-d/llm-d-router/issues/3629)),
   no logs pipeline recipe, so step 4 is `kubectl logs | jq`
   ([llm-d/llm-d#2926](https://github.com/llm-d/llm-d/issues/2926)),
   exemplars only on the EPP
   ([llm-d/llm-d-router#3584](https://github.com/llm-d/llm-d-router/issues/3584)).
5. **Jaeger all-in-one keeps few traces.** The pre-change traces were gone
   20 minutes later. Save the traces you will need (`/api/traces/<id>`).
6. **Tailscale SSH and `ssh -N` tunnels** kept dropping from the laptop;
   running the browser on the Spark itself avoided tunnels altogether.

## Files

```text
kind-config.yaml                         second Kind cluster (llm-d-obs), same GPU + HF cache mounts
helm-values/epp-config-before.values.yaml  EPP plugin chain, prefix-cache-scorer weight 3.0
helm-values/epp-config-after.values.yaml   the incident: weight 0.0 (one-line diff)
helm-values/router-obs.values.yaml       EPP v1.0.0 image, no tokenizer sidecar, ServiceMonitor
helm-values/tracing.values.yaml          EPP -> otel-collector, sampling 1.0
manifests/02-model-servers-obs.yaml      2x vLLM on the GB10, 3 GiB KV each
manifests/ttft-slo-rule.yaml             the P99 TTFT SLO alert
manifests/session-traffic.yaml           in-cluster traffic generator
grafana/ttft-exemplars-dashboard.json    TTFT P99/P50 with exemplars + hit rate
scripts/create-cluster.sh                Kind + GPU runtime + image import
scripts/install-stack.sh                 gateway, router, vLLM, tracing, monitoring, rules
scripts/session-traffic.py               multi-session long-prefix load
scripts/capture-ui.py                    Grafana / Prometheus / Jaeger screenshots (headless Chromium)
scripts/hover-top-exemplar.py            the single-panel Grafana frame with the exemplar tooltip
scripts/capture-jaeger.py                Jaeger span tree + per-span Tags tables
scripts/compose-jaeger.py                annotated Jaeger image for the slide
scripts/compare-traces.py                routing attributes of two traces side by side
scripts/render-terminal.py               command output -> terminal-style PNG
traces/                                  the two traces used on the slides (Jaeger JSON)
screenshots/                             the slide images
```
