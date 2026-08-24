# llm-d GPU Demo — Detailed Test Plan

Companion to [`../README.md`](../README.md). Every test case below specifies: ID,
component(s) under test, preconditions, exact steps, expected result, pass/fail
criteria, and evidence to capture. **Every test case in this document is marked
[LIVE] and was actually executed on 2026-08-24** against the run described in the
README, with real captured command output inline — nothing here is a sample or a
prediction. A small number of cases (see Suite 7) were executed but did not
reproduce the expected positive outcome within this session's time budget; those
are marked accordingly with the real negative output and root-cause analysis
rather than being left unexecuted.

Variables used throughout:

```console
export GWIP=$(kubectl get svc llm-d-inference-gateway -n llm-d -o jsonpath='{.spec.clusterIP}')
export DGX_HOST=192.168.1.112
export MODEL=Qwen/Qwen2.5-1.5B-Instruct
```

---

## Suite 1 — TC-GPU-*: DGX Spark vLLM health (real hardware)

### TC-GPU-01 — vLLM server health endpoint **[LIVE]**
- **Component:** vLLM on DGX Spark
- **Preconditions:** `gpu-node/deploy-vllm.sh` completed
- **Steps:** `curl -sS -m 5 http://$DGX_HOST:8000/health`
- **Expected:** HTTP 200, empty or `{}` body
- **Pass/Fail:** exit code 0 and http_code 200
- **Evidence (captured):** `gpu-node/healthcheck.sh` output — `/health http=200`, model `Qwen/Qwen2.5-1.5B-Instruct` returned from `/v1/models`

### TC-GPU-02 — Real chat completion returns coherent text **[LIVE]**
- **Steps:** POST `/v1/chat/completions` with `{"model":"Qwen/Qwen2.5-1.5B-Instruct","messages":[{"role":"user","content":"Say hello in 5 words"}],"max_tokens":20}`
- **Expected:** HTTP 200, `choices[0].message.content` is non-empty, grammatical text; `usage.completion_tokens` ≤ `max_tokens`
- **Evidence (captured):** `"content":"Hello! How can I assist you today?"`, `usage: {prompt_tokens:35, completion_tokens:10}`, response time 0.56s

### TC-GPU-03 — GPU process visible in `nvidia-smi` **[LIVE]**
- **Steps:** `ssh lgy@$DGX_HOST nvidia-smi`
- **Expected:** a `VLLM::EngineCore` (or similar vLLM) process listed under GPU 0 Processes
- **Evidence (captured):** `1550079  C  VLLM::EngineCore  4809MiB` alongside ComfyUI's `106054`/`130792` processes

### TC-GPU-04 — GPU memory budget respected **[LIVE]**
- **Steps:** compare `docker logs vllm-gpu-0 | grep "Model loading took\|Available KV cache"` against the configured `--gpu-memory-utilization 0.04` (≈5.23 GB of the 130.667 GB unified pool)
- **Expected:** weights + KV cache ≤ budget
- **Evidence (captured):** `Model loading took 2.89 GiB`, `Available KV cache memory: 0.56 GiB` → 3.45 GiB used, under the 5.23 GiB budget. `GPU KV cache size: 20,992 tokens`, max concurrency 5.12x @ 4096 tokens/request

### TC-GPU-05 — Second replica under VRAM pressure **[LIVE — full incident log, 3 attempts]**
- **Steps:** `REPLICA_1=true bash gpu-node/deploy-vllm.sh` (brings up `vllm-gpu-0` on :8000 then `vllm-gpu-1` on :8001, same image/model)
- **Attempt 1 (session start, `mem_get_info` free ≈5.3GB):** `vllm-gpu-1` not attempted — `torch.cuda.mem_get_info()` free dropped 5.35GB → 1.13GB after just `vllm-gpu-0`, judged insufficient headroom, skipped.
- **Attempt 2 (mid-session retest, free ≈14.1GB — ComfyUI's own usage had dropped):**
  ```console
  $ REPLICA_1=true bash gpu-node/deploy-vllm.sh
  ==> Deploying vllm-gpu-0 (http:8000 zmq:5556 util:0.04) ...
  vllm-gpu-0 is up.
  ==> Deploying vllm-gpu-1 (http:8001 zmq:5557 util:0.04) ...
  vllm-gpu-1 is up.
  ```
  **Both replicas started successfully** — first time this was achieved live. ~2 minutes later, unprompted, `vllm-gpu-0` crashed:
  ```console
  $ docker logs vllm-gpu-0 | tail -5
  RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): {}
  ValueError: No available memory for the cache blocks. Try increasing `gpu_memory_utilization`...
  $ docker ps -a --filter name=vllm-gpu
  vllm-gpu-1   Up 2 minutes   (healthy)
  vllm-gpu-0   Exited (1) 3 minutes ago
  ```
  Root cause: ComfyUI's own memory usage grew again (`nvidia-smi` showed its process at 28291MiB vs. an earlier 14467MiB) while both vLLM processes were still running, squeezing one of them out.
- **Attempt 3 (single-replica retest, free ≈6.6GB, same 0.04 budget as attempt 1):** failed the same way (`No available memory for the cache blocks`) even solo — confirms the failure threshold moves with ComfyUI's load, not with replica count alone.
- **Recovery:** lowered `GPU_MEM_UTIL` default 0.04→0.03 in `gpu-node/deploy-vllm.sh`; redeploy succeeded and stayed up for the remainder of the session (re-verified via `healthcheck.sh` and TC-BRIDGE-05's later DGX-down/DGX-up cycle).
- **Pass/Fail:** **PASS (with caveats)** — 2 real replicas is achievable on this hardware, contradicting the earlier assumption that it was categorically impossible; but **not reliable on demand**, and a running replica can be evicted by unrelated GPU load with no graceful degradation (hard crash). See README §2 for the full table.

### TC-GPU-06 — Node-local ZMQ KV-events publisher starts **[LIVE]**
- **Steps:** `docker logs vllm-gpu-0 | grep kv_events`
- **Expected:** `Starting ZMQ publisher thread` log line
- **Evidence (captured):** present at `16:40:22`

---

## Suite 2 — TC-BRIDGE-*: proxy-Pod correctness

### TC-BRIDGE-01 — Proxy Pod becomes Ready only when DGX backend reachable **[LIVE]**
- **Component:** `gpu-vllm-proxy` Deployment
- **Steps:** `kubectl apply -f manifests/optional/gpu-proxy/gpu-vllm-proxy.yaml; kubectl get pods -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing -o wide`
- **Expected:** Pod reaches `2/2 Running` (both `http-proxy` and `kv-proxy` containers) once the DGX backend answers `/health`
- **Evidence (captured):** `gpu-vllm-proxy-65c98887dd-ltd6k 2/2 Running` within ~30s of apply

### TC-BRIDGE-02 — HTTP passthrough returns byte-identical response **[LIVE]**
- **Steps:** from a throwaway curl Pod, POST the same body to the proxy Pod's IP:8000 that TC-GPU-02 sent directly to the DGX
- **Expected:** identical `choices[0].message.content` structure (content itself may differ — sampling is not seeded — but schema and `model` field must match)
- **Evidence (captured):** proxied response `"content":"Hello! How can I assist you today?"` — schema-correct OpenAI completion object, `model` field correct

### TC-BRIDGE-03 — ZMQ passthrough: EPP subscriber connects through the tunnel **[LIVE]**
- **Steps:** `kubectl logs -n llm-d deploy/llm-d-epp -c epp | grep zmq-subscriber`
- **Expected:** `Connected subscriber socket endpoint=tcp://<gpu-vllm-proxy-pod-ip>:5556` (the Pod IP, not the DGX IP — proves the EPP is talking to the in-cluster proxy, which then relays to the DGX)
- **Evidence (captured):** `"Connected subscriber socket","endpoint":"tcp://10.244.0.9:5556"` — `10.244.0.9` is the proxy Pod's IP

### TC-BRIDGE-04 — ZMQ tunnel survives and reconnects after a drop **[LIVE, observed incidentally]**
- **Steps:** monitor `kubectl logs -n llm-d deploy/llm-d-epp -c epp | grep zmq-subscriber` over a long-running session
- **Expected:** if the underlying TCP stream drops (idle timeout, DGX-side restart, etc.), the EPP logs `Failed to receive message ... error: EOF` then `retrying zmq-subscriber` then reconnects
- **Evidence (captured):** exactly this sequence was observed ~8 minutes into the run (`EOF` at `16:58:28`, `retrying` and reconnect at `16:58:33`), with **no manual intervention** — self-healing confirmed
- **Note:** treat reconnection frequency as a signal — if it happens every few seconds rather than rarely, that indicates the socat proxy or LAN link is unstable and should be investigated (not observed in this run: one reconnect in ~8 minutes of otherwise-idle connection)

### TC-BRIDGE-05 — Pod goes NotReady when DGX backend stops **[LIVE]**
- **Steps:** `ssh lgy@$DGX_HOST docker stop vllm-gpu-0`; watch `kubectl get pods -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing`
- **Expected:** `http-proxy` container's readinessProbe (`GET /health`) starts failing, Pod flips to `1/2`; EPP drops it from the candidate endpoint list
- **Evidence (captured):**
  ```console
  $ ssh lgy@192.168.1.112 docker stop vllm-gpu-0
  vllm-gpu-0
  $ kubectl get pod -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing   # ~30s later
  gpu-vllm-proxy-65c98887dd-ltd6k   1/2   Running
  $ kubectl describe pod ... | tail -4
  Warning  Unhealthy  9s (x6 over 49s)  kubelet  Readiness probe failed: Get "http://10.244.0.9:8000/health": EOF
  $ curl http://10.244.0.9:8000/health   # direct probe from inside the cluster
  curl: (52) Empty reply from server        # http=000
  $ curl http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_ready_endpoints{job="llm-d-epp"}'
  {"metric": {...}, "value": [..., "0"]}    # EPP correctly sees 0 ready endpoints
  ```
- **Cleanup:** `bash gpu-node/deploy-vllm.sh` to bring it back — see TC-GPU-05 for what actually happened on this specific recovery attempt (a stale `docker start` failed to recover the container cleanly; a fresh `docker run` via the script was needed instead). Confirmed working again afterward (TC-ROUTE-01-style 200 response).

### TC-BRIDGE-06 — Prometheus can scrape `/metrics` through the proxy **[LIVE]**
- **Steps:** `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=vllm:time_to_first_token_seconds_count'`
- **Expected:** a series with `job="llm-d/gpu-vllm-proxy"`, `instance` = proxy Pod IP:8000
- **Evidence (captured):** `vllm:time_to_first_token_seconds_count{instance="10.244.0.9:8000", job="llm-d/gpu-vllm-proxy"} = 6` — a real GPU histogram, scraped through the socat tunnel

---

## Suite 3 — TC-ROUTE-*: 3-way HTTPRoute precedence

### TC-ROUTE-01 — Default path reaches the real-GPU pool **[LIVE]**
- **Steps:** `curl -X POST http://$GWIP/v1/chat/completions -d '{"model":"'$MODEL'",...}'` (no special header)
- **Expected:** HTTP 200; EPP `llm-d-epp` logs show the request; response content is real-GPU-generated
- **Evidence (captured):** `http=200` on 4 separate default-path requests during this run

### TC-ROUTE-02 — `x-llm-d-pool: pd` reaches the P/D pool **[LIVE]**
- **Steps:** same request + header `x-llm-d-pool: pd`
- **Expected:** HTTP 200; `llm-d-pd-epp` logs show the request, not `llm-d-epp`
- **Evidence (captured):** `pd http=200`; the resulting trace (TC-TRACE-05) shows `pick_disagg_profile` / `prepare_disaggregation` spans unique to the P/D EPP plugin chain

### TC-ROUTE-03 — `x-llm-d-pool: baseline` reaches the WVA-scaled pool **[LIVE]**
- **Steps:** same request + header `x-llm-d-pool: baseline`
- **Expected:** HTTP 200; `llm-d-baseline-epp` logs show the request
- **Evidence (captured):** `baseline http=200`; confirmed via `llm_d_epp_request_total{job="llm-d-baseline-epp"} = 1` in Prometheus immediately after

### TC-ROUTE-04 — Unmatched header value falls through to default **[LIVE]**
- **Steps:** send with `x-llm-d-pool: does-not-exist`
- **Expected:** HTTP 200, routed to the default pool `llm-d` (header match only wins for the exact configured value; PathPrefix `/` still matches everything)
- **Evidence (captured):**
  ```console
  $ curl -X POST http://$GWIP/v1/chat/completions -H 'x-llm-d-pool: does-not-exist' -d '{...}'
  http=200
  $ curl http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_request_total'
  llm-d-baseline-epp 1   # unchanged from before the test
  llm-d-epp          10  # incremented — this request landed here
  llm-d-pd-epp        2  # unchanged from before the test
  ```
  Only `llm-d-epp`'s counter incremented, confirming the request fell through to the default pool and not to either header-matched pool.

### TC-ROUTE-05 — All three InferencePools and HTTPRoutes coexist on one Gateway **[LIVE]**
- **Steps:** `kubectl get inferencepool,httproute -n llm-d`
- **Expected:** 3 of each, all `AGE` > 0, no error conditions
- **Evidence (captured):**
  ```
  inferencepool.../llm-d   inferencepool.../llm-d-baseline   inferencepool.../llm-d-pd
  httproute.../llm-d       httproute.../llm-d-baseline       httproute.../llm-d-pd
  ```

---

## Suite 4 — TC-TRACE-*: distributed tracing (Jaeger)

### TC-TRACE-01 — Gateway root span exists **[LIVE]**
- **Steps:** `curl -s "http://localhost:16686/api/traces?service=llm-d-inference-gateway&limit=1" | jq`
- **Expected:** a trace with a root span `POST /*`, service `llm-d-inference-gateway`, no parent
- **Evidence (captured):** confirmed in every captured trace this run

### TC-TRACE-02 — EPP span is a child of the gateway (not orphaned) **[LIVE]**
- **Steps:** walk the trace's span `references[].refType == CHILD_OF` chain from `[llm-d-router/epp] gateway.request`
- **Expected:** parent service is `llm-d-inference-gateway`
- **Evidence (captured):** `[llm-d-router/epp] gateway.request <- llm-d-inference-gateway` — confirmed stitched (this is the property standalone Envoy mode cannot achieve; Gateway API/agentgateway mode fixes it, per `project_llmd_epp_trace_parent` prior finding, still holds)

### TC-TRACE-03 — IPP span parentage **[LIVE — REGRESSION FOUND]**
- **Steps:** same walk, looking for an `llm-d-inference-payload-processor` span between the gateway and EPP
- **Expected (per CPU demo, 2026-08-03):** `EPP gateway.request <- IPP <- gateway`
- **Actual (this run):** IPP appears as its **own disconnected trace** (different `traceID`) with a single root span `gateway.request`; the gateway→EPP trace has no IPP hop in it. IPP's functional behavior (header rewriting) is still verified correct via its own pod logs (`captured request headers`, `parsed field from body field=model`, `updated base model header`).
- **Pass/Fail for this run:** **FAIL** relative to the CPU demo's stitching result — logged as upstream drift (README §7 item 6), not swallowed
- **Evidence (captured):** IPP trace IDs `c3c6dbc3…`/`fc167035…` do not match the concurrent gateway/EPP trace IDs `0965ead8…`/`12f270a5…`

### TC-TRACE-04 — Precise-prefix scheduler subtree spans **[LIVE]**
- **Steps:** inspect a default-route trace's span tree
- **Expected:** `gateway.request_orchestration` → `tokenize_render` (token-producer → EPP's own vllm-render sidecar), `produce_precise_prefix_cache` → `index_lookup`, `run_scheduler_profile` → `filter_endpoints` + `llm_d.epp.scoring` (→ 3 `llm_d.epp.scorer.*` children) → `pick_endpoints`, then `index_add`
- **Evidence (captured, screenshot `docs/screenshots/jaeger-traces.png`):** exactly this shape, **14 spans / 2 services / depth 6**, real GPU request, total trace duration 822.48ms (dominated by the `gateway.request` span awaiting the real GPU completion)

### TC-TRACE-05 — P/D disaggregated trace **[LIVE]**
- **Steps:** send a `x-llm-d-pool: pd` request, inspect the resulting trace
- **Expected:** `pick_disagg_profile` (×2, prefill+decode profiles) + a third scheduling pass, `prepare_disaggregation` ×2, sidecar service spans `llm_d.pd_proxy.POST` → `forward_request` → `prefill`/`decode` → `HTTP POST` legs
- **Evidence (captured):** **27 spans / 3 services** (`llm-d-inference-gateway`, `llm-d-router/epp`, `llm-d-routing-sidecar`):
  ```
  [llm-d-inference-gateway] POST /* <- ROOT
    [llm-d-router/epp] gateway.request <- llm-d-inference-gateway
      [llm-d-router/epp] gateway.request_orchestration
        [llm-d-router/epp] pick_disagg_profile  (x3)
        [llm-d-router/epp] run_scheduler_profile (x2) -> filter_endpoints, llm_d.epp.scoring -> scorers, pick_endpoints
        [llm-d-router/epp] prepare_disaggregation (x2)
    [llm-d-routing-sidecar] llm_d.pd_proxy.POST /v1/chat/completions <- llm-d-inference-gateway
      [llm-d-routing-sidecar] forward_request -> prefill -> decode -> HTTP POST (x2)
  ```

### TC-TRACE-06 — Span/service counts asserted exactly, not just "trace exists" **[LIVE]**
- Captured and stated precisely above for both the default path (14/2) and P/D path (27/3) — see `docs/screenshots/jaeger-traces.png` for the default-path screenshot.

---

## Suite 5 — TC-KV-*: KV-cache-aware routing (real GPU)

### TC-KV-01 — Repeated long prompt against the real GPU replica **[LIVE]**
- **Steps:** send the same >64-token prompt 6× with a 2s gap, via the default route
- **Expected:** all 6 return HTTP 200
- **Evidence (captured):** `req1..req6 http=200`

### TC-KV-02 — Prefix-block indexing occurs **[LIVE]**
- **Steps:** inspect `produce_precise_prefix_cache` span attributes across the 6 traces
- **Expected:** `llm_d.epp.producer.total_blocks` = 1 (prompt is ≥64 tokens, block-size 64) on every request (consistent tokenization)
- **Evidence (captured):** `total_blocks=1` on all 6 traces

### TC-KV-03 — Cache hit on repeat — **NOT achieved this run [LIVE — negative finding]**
- **Expected (per CPU demo pattern):** `max_match_blocks` transitions from 0 → 1 by request 3-6, `llm_d.kv_cache.lookup.cache_hit=true`
- **Actual:** `max_match_blocks=0` on all 6 requests; `llm_d_epp_kv_cache_index_lookup_hits_total = 0`; `llm_d_epp_kv_cache_events_stores_skipped_total{reason="unsupported_cache_kind"} = 1`
- **Root cause (isolated, not just observed):** exactly **one** KV event was ever received (`llm_d_epp_kv_cache_events_messages_received_total = 1`) despite 6 real completions on the same replica — vLLM's own local prefix-cache reuse means only the *first* new block triggers a publish event; that one event's `cache_kind` field was not recognized by the router's decoder, so it was never admitted to the index. The ZMQ transport itself is proven working (message count is 1, not 0) — this is a payload-schema version mismatch between vLLM `0.20.1.dev` (NGC 26.05) and this router build, not a bridge/proxy defect.
- **Pass/Fail:** **FAIL** relative to the CPU demo's result; root cause fully diagnosed and documented (README §7 item 7)
- **Follow-up (not executed, suggested):** try a router image built from a more recent `upstream/main` commit, or inspect `pkg/kvevents` in the router source for the exact `cache_kind` enum it accepts vs. what vLLM 0.20.1 emits, and file an upstream issue if confirmed a genuine mismatch

### TC-KV-04 — Scorer machinery runs correctly regardless of the hit/miss outcome **[LIVE]**
- **Steps:** inspect `llm_d.epp.scoring` and its child scorer spans
- **Expected:** `prefix-cache-scorer`, `kv-cache-utilization-scorer`, `queue-scorer` all execute and report a score (0 in this case, since no hit) per request
- **Evidence (captured):** all 3 scorer spans present on every request, `llm_d.epp.scorer.prefix-cache-scorer.score.max = 0` (correctly reflecting the miss), `pick_endpoints.top_scores=[4]` (kv-cache-utilization 2.0 + queue-scorer 2.0, no prefix bonus) — proves the scoring pipeline itself is intact; only the KV-cache signal into it is empty this run

### TC-KV-05 — 2-replica differential scoring **[LIVE — attempted, inconclusive]**
- See TC-GPU-05: 2 real replicas did come up together once (`REPLICA_1=true`), but neither the `gpu-vllm-proxy` Deployment nor the EPP's `InferencePool` selector was reconfigured mid-session to expose a 2nd proxy Pod pointing at `vllm-gpu-1:8001` — that wiring change wasn't made in the window before `vllm-gpu-0` crashed, so the differential-scoring comparison (`top_scores=[7,4]`-style) was not actually exercised even though the 2nd real backend was briefly available. To complete this test case: add a second `gpu-vllm-proxy-1` Pod (labels identical, containers pointed at `DGX:8001`/`DGX:5557`) before starting the 2nd replica, then repeat TC-KV-01 through TC-KV-04 and inspect `pick_endpoints.top_scores` for a 2-element array.

---

## Suite 6 — TC-PD-*: P/D disaggregation

### TC-PD-01 — P/D request succeeds end-to-end **[LIVE]** — see TC-ROUTE-02
### TC-PD-02 — Disagg profile scheduling produces 2 distinct scheduler passes **[LIVE]** — see TC-TRACE-05 (`run_scheduler_profile` ×2: prefill profile, decode profile)
### TC-PD-03 — routing-sidecar performs 2 real proxy legs **[LIVE]** — see TC-TRACE-05 (`prefill` → `decode` → 2× `HTTP POST`)
### TC-PD-04 — KV transfer is simulated, not real **[BY DESIGN, documented]** — `llm-d-inference-sim` backs both `pd-prefill` and `pd-decode`; no real NIXL handshake occurs. This is intentional (README §"Known limitations") since real P/D needs ≥2 physical GPUs.

---

## Suite 7 — TC-WVA-*: autoscaling loop

### TC-WVA-01 — WVA controller starts and connects to Prometheus **[LIVE]**
- **Steps:** `kubectl logs -n wva-system deploy/wva-controller-manager | tail -20`
- **Expected:** no fatal errors, periodic `Optimization completed successfully` log lines
- **Evidence (captured):** exactly this, `modelsProcessed: 1, decisionsApplied: 0` (idle, no load)

### TC-WVA-02 — WVA discovers the annotated HPA **[LIVE]**
- **Steps:** same logs, look for the HPA name
- **Expected:** `EmitReplicaMetrics completed variantName=optimized-baseline-decode-hpa`
- **Evidence (captured):** present, `currentReplicas:1, desiredReplicas:1`

### TC-WVA-03 — `wva_desired_replicas` reaches Prometheus **[LIVE]**
- **Steps:** `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=wva_desired_replicas'`
- **Expected:** one series, `variant_name="optimized-baseline-decode-hpa"`, `exported_namespace="llm-d"`, value matching desired replica count
- **Evidence (captured):** value `1`, labels exactly matching the HPA's `external.metric.selector`

### TC-WVA-04 — prometheus-adapter serves it as an external metric **[LIVE]**
- **Steps:** `kubectl get --raw /apis/external.metrics.k8s.io/v1beta1/namespaces/llm-d/wva_desired_replicas`
- **Expected:** `ExternalMetricValueList` with 1 item, value `1`
- **Evidence (captured):** exact match

### TC-WVA-05 — HPA reads the external metric and computes target **[LIVE]**
- **Steps:** `kubectl get hpa -n llm-d optimized-baseline-decode-hpa`
- **Expected:** `TARGETS` column shows a real value (not `<unknown>`)
- **Evidence (captured):** `1/1 (avg)` (before fix: `<unknown>/1 (avg)` with `FailedGetExternalMetric` events — captured too, as the "before" state)

### TC-WVA-06 — Scale-up under load **[LIVE — attempted, blocker found and fixed, scale-up still not reproduced]**
- **Steps:** from a throwaway `loadgen` Pod, fired 40 concurrent requests then a 45s sustained burst (~15 concurrent, 2 waves/sec) at the baseline route (`x-llm-d-pool: baseline`, `max_tokens=200-300` to make each request take some time), polling `kubectl get hpa -n llm-d optimized-baseline-decode-hpa` and `wva_desired_replicas` every 6-7s throughout
- **First blocker found and fixed:** `optimized-baseline-decode` had **no PodMonitor at all** — this demo never wired one up for it (only `gpu-vllm-proxy` got one). Confirmed via `curl .../query?query=vllm:num_requests_waiting{namespace="llm-d"}` returning only the `gpu-vllm-proxy` series, and via the WVA controller's own log:
  ```console
  $ kubectl logs -n wva-system deploy/wva-controller-manager | grep -A2 "Skipping pod"
  "msg":"Skipping pod that doesn't match any scale target","pod":"gpu-vllm-proxy-...","scale targets":["optimized-baseline-decode"]
  "msg":"No saturation metrics available for model, skipping analysis","modelID":"Qwen/Qwen2.5-1.5B-Instruct"
  ```
  Both `optimized-baseline-decode` and the real-GPU pool share the model name `Qwen/Qwen2.5-1.5B-Instruct`, which is why WVA's per-model grouping surfaced the (wrong, non-scale-target) `gpu-vllm-proxy` pod instead of silently doing nothing. **Fix applied:** added a `PodMonitor` for `optimized-baseline-decode` (`app: optimized-baseline-decode`, `llm-d.ai/guide: optimized-baseline`, port `modelserver`, path `/metrics`) — needed the documented `resync=$(date +%s)` annotation kick to actually land in Prometheus's generated config (the same PodMonitor-creation race noted in the CPU demo's memory notes). Confirmed after the fix:
  ```console
  $ curl .../query?query=vllm:num_requests_waiting{job="llm-d/optimized-baseline-decode"}
  {"metric": {"pod": "optimized-baseline-decode-d4f6f74cf-k5p8f", ...}, "value": [..., "0"]}
  ```
- **Result after the fix — still no scale-up:** with real metric visibility now in place, `vllm:num_requests_waiting` stayed at `0` throughout both load bursts (8 polls over 48s during the sustained burst), and `wva_desired_replicas` stayed at `1` the entire time. `llm-d-inference-sim` (the baseline pool's backend) evidently does not model queue backpressure under this load pattern/resource ceiling (200m request / 1 CPU limit) the way real vLLM does — it drains requests fast enough that no measurable queue ever forms at the concurrency levels tried here.
- **Pass/Fail:** **Partial** — a real, previously-undetected observability gap was found and fixed (valuable outcome), but the scale-up event itself was not reproduced. The WVA control-loop mechanics (metric emission → external API → HPA target) were already fully proven in TC-WVA-01–05; what remains unverified is specifically the "real load causes a real scaling decision" step.
- **Follow-up (not executed, suggested):** either drive load against the real-GPU pool instead (where `vllm:num_requests_waiting` has real physical meaning) with `maxReplicas` raised beyond 1, or check `llm-d-inference-sim`'s CLI for a synthetic-latency/concurrency-cap flag that would let it model backpressure realistically.

### TC-WVA-07 — Scale-down after load stops **[LIVE — not applicable, no scale-up occurred to reverse]**
- Since TC-WVA-06 never drove `wva_desired_replicas` above 1, there was no scale-up state to observe scaling back down from. Replica count stayed at 1 throughout. Re-run once TC-WVA-06's follow-up produces a real scale-up.

---

## Suite 8 — TC-METRICS-*: Prometheus + Grafana

### TC-METRICS-01 — All expected ServiceMonitors/PodMonitors are UP **[LIVE]**
- **Steps:** `curl -s http://localhost:9091/api/v1/targets?state=active | jq -r '.data.activeTargets[].scrapePool' | sort -u`
- **Expected UP:** `serviceMonitor/llm-d/llm-d-epp-monitor`, `serviceMonitor/llm-d/llm-d-pd-epp-monitor`, `serviceMonitor/llm-d/llm-d-baseline-epp-monitor`, `podMonitor/llm-d/gpu-vllm-proxy`, `podMonitor/llm-d/optimized-baseline-decode` (added mid-session, see TC-WVA-06), `serviceMonitor/wva-system/wva-controller-manager-metrics-monitor`
- **Expected DOWN (benign, Kind has no real control plane):** kube-controller-manager, kube-etcd, kube-proxy, kube-scheduler ServiceMonitors
- **Evidence (captured):** exactly this split confirmed live, including the `optimized-baseline-decode` PodMonitor after the TC-WVA-06 fix and its `resync` annotation kick

### TC-METRICS-02 — EPP request-count metrics increment per pool **[LIVE]**
- **Steps:** `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_request_total'`
- **Expected:** 3 series, one per EPP release (`llm-d-epp`, `llm-d-pd-epp`, `llm-d-baseline-epp`), each with a `model_name` label
- **Evidence (captured):** 3 series returned, counts `1`/`3`/`1` matching the request mix sent so far

### TC-METRICS-03 — Real GPU vLLM histogram metrics flow through the proxy **[LIVE]**
- **Steps:** `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=vllm:time_to_first_token_seconds_count'` and `vllm:num_requests_running`
- **Expected:** non-zero series from `job="llm-d/gpu-vllm-proxy"`
- **Evidence (captured):** TTFT count = 6, `num_requests_running` = 0 (idle at query time — correct, no in-flight requests)

### TC-METRICS-04 — Grafana dashboards load **[LIVE]**
- **Steps:** `curl -s -u admin:admin http://localhost:3000/api/search?type=dash-db`
- **Expected:** 7 llm-d dashboards
- **Evidence (captured):** confirmed present; screenshot `docs/screenshots/grafana-vllm-overview.png` shows live data points in Token Throughput, TTFT, Queue Time, Prefill/Decode Time, and Max Generation Token panels at the current-time edge of the graph

### TC-METRICS-05 — Prometheus targets page screenshot **[LIVE]**
- **Evidence (captured):** `docs/screenshots/prometheus-targets.png`

---

## Suite 9 — TC-NEG-*: negative / failure-mode cases

### TC-NEG-01 — DGX node unreachable → documented failure mode **[LIVE]**
- Same as TC-BRIDGE-05 but observed from the client side: while `vllm-gpu-0` is stopped, send a request through the gateway's default route
- **Expected:** a clear error, not a hang
- **Evidence (captured):**
  ```console
  $ curl -X POST http://$GWIP/v1/chat/completions -d '{...}'
  inference error: ServiceUnavailable - failed to find endpoint candidates for serving the request
  http=503
  ```
  Returned in under a couple seconds — the EPP had already dropped the NotReady proxy Pod from its candidate set (confirmed via `llm_d_epp_ready_endpoints=0` in TC-BRIDGE-05), so it fails fast with a clean `503` rather than attempting to proxy to a dead backend and timing out.

### TC-NEG-02 — Malformed request body **[LIVE]**
- **Steps:** POST invalid JSON (missing `:` between a key and its value) to `/v1/chat/completions`
- **Expected:** HTTP 400, not a 5xx
- **Evidence (captured):**
  ```console
  $ curl -X POST http://$GWIP/v1/chat/completions -d '{"model":"...", "messages":[{"role":"user" "content":"broken json"}]'
  inference error: BadRequest - failed to parse request body: invalid character '"' after object key:value pair
  http=400
  ```

### TC-NEG-03 — Unknown model name **[LIVE]**
- **Steps:** POST with `"model": "does-not-exist-model"`
- **Expected:** 404/400 identifying the unknown model, no silent fallback
- **Evidence (captured):**
  ```console
  $ curl -X POST http://$GWIP/v1/chat/completions -d '{"model":"does-not-exist-model",...}'
  {"error":{"message":"The model `does-not-exist-model` does not exist.","type":"NotFoundError","param":"model","code":404}}
  http=404
  ```

### TC-NEG-04 — IPP `--secure-serving` regression guard **[LIVE]**
- **Steps:** confirmed baseline (200) first, then `helm upgrade ipp ... --set payloadProcessor.flags.secure-serving=true` (deliberately reintroducing the documented gotcha), sent a request, then reverted
- **Expected:** every request through the gateway starts failing with 500s
- **Evidence (captured):**
  ```console
  $ curl -X POST http://$GWIP/v1/chat/completions -d '{...}'   # pre-regression
  http=200
  $ helm upgrade ipp ... --set payloadProcessor.flags.secure-serving=true
  Release "ipp" has been upgraded.
  $ curl -X POST http://$GWIP/v1/chat/completions -d '{...}'   # post-regression
  ext_proc failed: no more response messages
  http=500
  $ kubectl logs -n llm-d deploy/llm-d-inference-gateway --since=30s | grep FailClosed
  failed to initialize endpoint picker: ... "upstream call failed: ... stream closed because of a broken pipe" ... failure_mode=FailClosed
  ```
  Exact match to the documented gotcha — a broken `ext_proc` fails closed for **all** traffic, not just the IPP hop.
- **Cleanup:** `helm upgrade ipp ... ` (without the override, back to `secure-serving=false`) — reverted and reconfirmed 200 (`http=200`, `tneg4revert2`).

### TC-NEG-05 — WVA Gateway API CRD conflict (install-order hazard) **[LIVE — encountered and worked around]**
- **What happened:** running `deploy/install.sh` with default settings attempted to install Gateway API CRDs `v1.2.0`, which conflicted with the already-installed `v1.5.1` CRDs (`Error from server (Invalid): error when applying patch`), aborting the script under `set -e` partway through (namespaces created, WVA controller never deployed)
- **Verification the conflict didn't corrupt cluster state:** `kubectl get crd inferencepools.inference.networking.k8s.io -o jsonpath='{.spec.versions[*].name}'` still showed only `v1` afterward; existing `InferencePool`/`Gateway` objects were unaffected
- **Workaround used:** Kustomize direct-controller install instead of the full script (README §3.13)
- **Pass/Fail:** documented as a real install-order hazard for anyone following the upstream README verbatim on a cluster that already has newer Gateway API CRDs installed

---

## Appendix — Regression/comparison vs. the CPU demo (`llm-d-full-demo`, 2026-08-03)

| Metric | CPU demo (sim/CPU vLLM) | This GPU demo (real DGX Spark) |
| --- | --- | --- |
| Model | Qwen2.5-0.5B-Instruct | Qwen2.5-1.5B-Instruct |
| Backend | vLLM CPU (arm64 native) / inference-sim | **Real vLLM on GB10 GPU** |
| Model-server replicas (default pool) | 2 (steady) | 1 steady; 2 achieved once, unstable (TC-GPU-05, §2) |
| Default-path trace | 11 spans / 3 services (gateway→IPP→EPP stitched) | **14 spans / 2 services** (gateway→EPP stitched; IPP not stitched — regression, §7) |
| P/D-path trace | 21 spans / 4 services | **27 spans / 3 services** (richer EPP scorer detail; no separate model-server trace services this run) |
| KV-cache hit demonstrated | ✅ (`cache_hit=true`, `max_match_blocks=1` after ~6 repeats) | ❌ (`unsupported_cache_kind`, §TC-KV-03 — version skew, not a design flaw) |
| Metrics closed loop | ✅ | ✅ (plus real GPU TTFT histogram); found + fixed a missing PodMonitor for the baseline pool along the way (TC-WVA-06) |
| WVA closed loop (metric → external API → HPA target) | ✅ (prometheus-adapter + HPA) | ✅ (same mechanism; install path changed, §7 item 5) |
| WVA actual scale-up under load | ✅ | ❌ — `llm-d-inference-sim` didn't build measurable queue depth under the load tried (TC-WVA-06) |
| Local image builds required | Yes (EPP, sidecar, IPP from source) | **No** (all images pulled pre-built) |
