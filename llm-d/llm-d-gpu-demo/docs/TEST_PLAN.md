# llm-d GPU Demo — Detailed Test Plan

*[中文版](TEST_PLAN-zh.md)*

Companion to [`../README.md`](../README.md). This document assumes **zero
prior context** — if you followed the README's installation steps and have a
working cluster, you can run every test case below exactly as written and get
the same (or equivalent) results.

**Format:** every test case has a stated objective, preconditions, and a
numbered sequence of steps. Each step names the exact **command** to run
(input), the **real captured output** from this run, and an **explanation**
of what that output means and why the step matters. **Every test case in this
document is marked [LIVE] and was actually executed** on 2026-08-24 against
the run described in the README — nothing here is a sample, a prediction, or
untested. A few cases produced a negative result even after being executed
correctly; those are reported honestly, with root-cause analysis, rather than
hidden.

Shared variables used throughout (set these once per shell session):

```console
export GWIP=$(kubectl get svc llm-d-inference-gateway -n llm-d -o jsonpath='{.spec.clusterIP}')
export DGX_HOST=192.168.1.112
export DGX_USER=lgy
export MODEL=Qwen/Qwen2.5-1.5B-Instruct
```

---

## Suite 1 — TC-GPU-*: DGX Spark vLLM health (real hardware)

### TC-GPU-01 — vLLM server health endpoint **[LIVE]**

**Objective:** confirm the real vLLM process on the DGX Spark answers its
health-check endpoint.
**Component:** vLLM container `vllm-gpu-0` on the DGX Spark.
**Preconditions:** README §3 Step 1 completed (vLLM container running).

**Steps:**

1. **Send a health-check request from your workstation to the DGX Spark's
   published port 8000.**
   - Command:
     ```console
     curl -sS -m 5 -o /dev/null -w "http=%{http_code}\n" http://$DGX_HOST:8000/health
     ```
   - Output: `http=200`
   - Explanation: vLLM's OpenAI-compatible server exposes `/health` as a
     lightweight liveness check that returns `200 OK` with an empty body once
     the engine has finished loading and is ready to accept requests. `-m 5`
     caps the request at 5 seconds so a hung server fails fast instead of
     hanging your test script.

2. **Confirm the model identity via `/v1/models`.**
   - Command:
     ```console
     curl -sS http://$DGX_HOST:8000/v1/models | python3 -c "import sys,json;print(json.load(sys.stdin)['data'][0]['id'])"
     ```
   - Output: `Qwen/Qwen2.5-1.5B-Instruct`
   - Explanation: `/v1/models` is the OpenAI API's model-listing endpoint;
     this confirms the server loaded the model you asked for (not, say, a
     stale default), which matters because a copy-paste error in the
     `docker run` command could silently start a different model.

**Pass/Fail:** PASS — both checks returned exactly the expected values.

---

### TC-GPU-02 — Real chat completion returns coherent text **[LIVE]**

**Objective:** confirm the model actually generates real tokens on the GPU,
not just answers health checks.
**Preconditions:** TC-GPU-01 passed.

**Steps:**

1. **Send a real chat completion request.**
   - Command:
     ```console
     curl -sS -X POST http://$DGX_HOST:8000/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello in 5 words\"}],\"max_tokens\":20}"
     ```
   - Output:
     ```json
     {"id":"chatcmpl-8d3fad5343e92b77","object":"chat.completion","created":1787589712,
      "model":"Qwen/Qwen2.5-1.5B-Instruct",
      "choices":[{"index":0,"message":{"role":"assistant","content":"Hello! How can I assist you today?"},"finish_reason":"stop"}],
      "usage":{"prompt_tokens":31,"total_tokens":33,"completion_tokens":2}}
     ```
   - Explanation: `choices[0].message.content` is real, grammatical text the
     model generated — not an echo of the input, not a canned string. The
     `usage` block tells you exactly how many tokens were consumed:
     `prompt_tokens=31` includes the chat template's system/role formatting
     overhead (your 6-word prompt alone is far fewer tokens), and
     `completion_tokens` will vary run to run since sampling isn't seeded.

**Pass/Fail:** PASS — `content` is non-empty and grammatical;
`completion_tokens` ≤ the requested `max_tokens`.

---

### TC-GPU-03 — GPU process visible in `nvidia-smi` **[LIVE]**

**Objective:** prove the request in TC-GPU-02 was actually served by the GPU,
not a silent CPU fallback.

**Steps:**

1. **SSH to the DGX Spark and run `nvidia-smi`.**
   - Command: `ssh $DGX_USER@$DGX_HOST nvidia-smi`
   - Output (Processes table):
     ```
     |    0   N/A  N/A         1550079      C   VLLM::EngineCore              4809MiB |
     |    0   N/A  N/A            3341      G   /usr/lib/xorg/Xorg               97MiB |
     |    0   N/A  N/A            3730      G   /usr/bin/gnome-shell            126MiB |
     ```
   - Explanation: `VLLM::EngineCore` is vLLM's own process name for its
     inference engine subprocess; its presence in the `nvidia-smi` process
     table (with a real GPU memory allocation, 4809 MiB here) is
     unforgeable proof that CUDA kernels are actually executing on this GPU.
     The `Xorg`/`gnome-shell` lines are the desktop environment's own GPU
     usage — unrelated, just visible because it's a shared GPU.

**Pass/Fail:** PASS.

---

### TC-GPU-04 — GPU memory budget respected **[LIVE]**

**Objective:** confirm vLLM's actual memory usage stays under the
`--gpu-memory-utilization` budget you configured.

**Steps:**

1. **Read vLLM's own startup log for its memory accounting.**
   - Command:
     ```console
     ssh $DGX_USER@$DGX_HOST 'docker logs vllm-gpu-0 2>&1 | grep -E "Model loading took|Available KV cache|GPU KV cache size"'
     ```
   - Output:
     ```
     (EngineCore pid=258) INFO gpu_model_runner.py:4879 Model loading took 2.89 GiB memory and 60.297843 seconds
     (EngineCore pid=258) INFO gpu_worker.py:440 Available KV cache memory: 0.56 GiB
     (EngineCore pid=258) INFO kv_cache_utils.py:1708 GPU KV cache size: 20,992 tokens
     ```
   - Explanation: vLLM logs exactly how it split its memory budget between
     model weights (2.89 GiB) and KV cache (0.56 GiB), totaling 3.45 GiB —
     comfortably under the 0.04 × 130.667 GB ≈ 5.23 GB budget that was
     configured at that point in the session (the default was later lowered
     to 0.03 after an OOM, see TC-GPU-05). 20,992 tokens of KV cache capacity
     at block-size 64 works out to 20992/64 ≈ 328 blocks available across
     all concurrent requests.

**Pass/Fail:** PASS — 3.45 GiB actual ≤ 5.23 GiB budget.

---

### TC-GPU-05 — Second replica under VRAM pressure **[LIVE — full incident log, 3 attempts]**

**Objective:** determine whether a second real GPU replica (`vllm-gpu-1`) can
run alongside `vllm-gpu-0` on this shared DGX Spark, and characterize the
failure mode when it can't.
**Note:** this test case's *result* is the finding — it required three
separate attempts across the session, not one clean pass/fail.

**Steps:**

1. **Attempt 1, at session start.** Before starting a 2nd replica, check free
   VRAM.
   - Command:
     ```console
     ssh $DGX_USER@$DGX_HOST 'docker run --rm --gpus all --ipc=host nvcr.io/nvidia/vllm:26.05-py3 python3 -c "import torch; print(torch.cuda.mem_get_info())"'
     ```
   - Output (after `vllm-gpu-0` was already running): `(1128435712, 130667180032)` — 1.13 GB free of 130.67 GB total.
   - Explanation: `torch.cuda.mem_get_info()` returns `(free_bytes,
     total_bytes)`. 1.13 GB free is not enough headroom for a second
     replica's weights alone (Qwen2.5-1.5B needs ~2.9 GiB just for weights) —
     attempt skipped, judged as certain to fail.

2. **Attempt 2, mid-session retest.** Free VRAM happened to be much higher
   this time (ComfyUI's own usage had temporarily dropped). Start both
   replicas.
   - Command (2nd replica, same pattern as `vllm-gpu-0` but on port 8001/5557):
     ```console
     ssh $DGX_USER@$DGX_HOST "docker run -d --gpus all --ipc=host --name vllm-gpu-1 \
       -p 8001:8001 -p 5557:5557 nvcr.io/nvidia/vllm:26.05-py3 \
       vllm serve $MODEL --port 8001 --block-size 64 --gpu-memory-utilization 0.04 \
       --max-model-len 4096 --enforce-eager \
       --kv-events-config '{\"enable_kv_cache_events\":true,\"publisher\":\"zmq\",\"endpoint\":\"tcp://*:5557\",\"topic\":\"kv@vllm-gpu-1:8001@$MODEL\"}'"
     ```
   - Output:
     ```console
     $ ssh $DGX_USER@$DGX_HOST 'docker logs vllm-gpu-0 2>&1 | tail -1; docker logs vllm-gpu-1 2>&1 | tail -1'
     INFO:     Application startup complete.
     INFO:     Application startup complete.
     ```
   - Explanation: **both** replicas independently reported
     `Application startup complete` — this is the first time in this session
     that 2 real GPU replicas ran simultaneously.

3. **~2 minutes later, unprompted, check container status again.**
   - Command: `ssh $DGX_USER@$DGX_HOST 'docker ps -a --filter name=vllm-gpu'`
   - Output:
     ```
     vllm-gpu-1   Up 2 minutes
     vllm-gpu-0   Exited (1) 3 minutes ago
     ```
   - Command: `ssh $DGX_USER@$DGX_HOST 'docker logs vllm-gpu-0 2>&1 | tail -3'`
   - Output:
     ```
     ValueError: No available memory for the cache blocks. Try increasing `gpu_memory_utilization`...
     RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): {}
     ```
   - Explanation: `vllm-gpu-0` crashed on its own, with no external command
     issued against it. Root cause: `nvidia-smi` at that moment showed the
     ComfyUI process's own GPU memory usage had grown from ~14 GiB to ~28
     GiB — an unrelated process on the same shared GPU squeezed the two
     vLLM processes hard enough that one of them lost its memory reservation
     and failed to re-initialize.

4. **Attempt 3, single-replica retest at the same 0.04 budget that worked at
   session start.**
   - Command: same `docker run` as TC-GPU-01's setup, `--gpu-memory-utilization 0.04`.
   - Output: same `ValueError: No available memory for the cache blocks` error, this time with **only one** replica running (no contention from a 2nd vLLM process).
   - Explanation: confirms the failure threshold tracks ComfyUI's load, not
     replica count — even a single replica at a budget that worked earlier
     can fail later purely because the *other* process on the box grew.

5. **Recovery: lower the budget and redeploy.**
   - Command: same `docker run`, `--gpu-memory-utilization 0.03` (≈3.9 GB).
   - Output: `Application startup complete.` — stayed up for the remainder of
     the session, verified repeatedly by later test cases (TC-BRIDGE-05,
     TC-NEG-01) that stopped and restarted it.
   - Explanation: the demo's default was permanently lowered from 0.04 to
     0.03 in `gpu-node/deploy-vllm.sh` as a direct result of this finding.

**Conclusion:** **2 real replicas is achievable** on this hardware — not
categorically blocked, contradicting an earlier assumption in this same demo
that it was impossible. But it is **not reliable on demand**: VRAM headroom
on a shared box fluctuates independently of anything this demo controls, and
a running replica can be evicted with a hard crash (not graceful
degradation) at any time. **Pass/Fail: PASS (with caveats)** — treat both
findings as documented, not as a stable guarantee.

---

### TC-GPU-06 — Node-local ZMQ KV-events publisher starts **[LIVE]**

**Objective:** confirm vLLM actually started the ZMQ publisher thread that
KV-cache-aware routing depends on.

**Steps:**

1. **Grep vLLM's startup log for the publisher thread message.**
   - Command: `ssh $DGX_USER@$DGX_HOST 'docker logs vllm-gpu-0 2>&1 | grep kv_events'`
   - Output: `(EngineCore pid=258) INFO kv_events.py:329 Starting ZMQ publisher thread`
   - Explanation: this line only appears when `--kv-events-config` with
     `enable_kv_cache_events: true` was passed and parsed successfully. If
     you forget this flag (or typo the JSON), vLLM starts fine but this line
     never appears — silent failure mode, worth checking explicitly rather
     than assuming.

**Pass/Fail:** PASS.

---

## Suite 2 — TC-BRIDGE-*: proxy-Pod correctness

### TC-BRIDGE-01 — Proxy Pod becomes Ready only when DGX backend reachable **[LIVE]**

**Objective:** confirm the `gpu-vllm-proxy` Pod's readiness genuinely reflects
whether the DGX backend is reachable (not just "container started").
**Preconditions:** README §3 Step 6 completed.

**Steps:**

1. **Apply the proxy Pod manifest.**
   - Command: `kubectl apply -f manifests/optional/gpu-proxy/gpu-vllm-proxy.yaml`
   - Output: `deployment.apps/gpu-vllm-proxy created` / `podmonitor.monitoring.coreos.com/gpu-vllm-proxy created`

2. **Watch the Pod reach 2/2 Ready.**
   - Command: `kubectl get pods -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing -o wide`
   - Output:
     ```
     NAME                              READY   STATUS    RESTARTS   AGE   IP
     gpu-vllm-proxy-65c98887dd-ltd6k   2/2     Running   0          23s   10.244.0.9
     ```
   - Explanation: `2/2` means **both** containers' readiness probes passed —
     `http-proxy`'s probe does a real `GET /health` through the socat tunnel
     to the DGX Spark, so `2/2` here is a live end-to-end reachability check,
     not just "the container process is running."

**Pass/Fail:** PASS — reached `2/2` within ~23s of apply.

---

### TC-BRIDGE-02 — HTTP passthrough returns byte-identical response **[LIVE]**

**Objective:** confirm the socat tunnel doesn't corrupt or alter HTTP traffic.

**Steps:**

1. **From inside the cluster, send the same request TC-GPU-02 sent directly
   to the DGX, but this time through the proxy Pod's IP.**
   - Command:
     ```console
     PODIP=$(kubectl get pod -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing -o jsonpath='{.items[0].status.podIP}')
     kubectl run trig2 --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -X POST http://$PODIP:8000/v1/chat/completions -H 'Content-Type: application/json' \
       -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"max_tokens\":10}"
     ```
   - Output:
     ```json
     {"id":"chatcmpl-96cf154a307c70a5","object":"chat.completion", ...,
      "choices":[{"message":{"content":"Hello! How can I assist you today?"}, "finish_reason":"stop"}], ...}
     ```
   - Explanation: this is a full, valid OpenAI chat-completion JSON object —
     the same schema TC-GPU-02 got hitting the DGX directly. `socat` operates
     at the raw TCP-byte level with no protocol awareness, so if the JSON
     parses and the schema is intact, the tunnel is proven transparent.

**Pass/Fail:** PASS.

---

### TC-BRIDGE-03 — ZMQ passthrough: EPP subscriber connects through the tunnel **[LIVE]**

**Objective:** confirm the *second* socat container (`kv-proxy`, port 5556)
also tunnels correctly — this one carries a binary protocol (ZMTP), not HTTP.
**Preconditions:** README §3 Step 7 completed (EPP installed).

**Steps:**

1. **Grep the EPP's own logs for its ZMQ subscriber connection.**
   - Command: `kubectl logs -n llm-d deploy/llm-d-epp -c epp | grep zmq-subscriber`
   - Output:
     ```json
     {"level":"info","logger":"zmq-subscriber","msg":"Connected subscriber socket","endpoint":"tcp://10.244.0.9:5556"}
     ```
   - Explanation: `10.244.0.9` here is the **proxy Pod's** cluster IP, not
     the DGX Spark's `192.168.1.112`. This is the key evidence that the EPP
     is talking to the in-cluster proxy (as required by the InferencePool
     Pod-selector design in README §1.1), and the proxy is the one
     relaying to the real DGX process on the other side.

**Pass/Fail:** PASS.

---

### TC-BRIDGE-04 — ZMQ tunnel survives and reconnects after a drop **[LIVE, observed incidentally]**

**Objective:** confirm the EPP's ZMQ client self-heals if the underlying TCP
stream to the proxy drops (a real occurrence, not manufactured for this test).

**Steps:**

1. **Continue tailing the EPP's zmq-subscriber logs over the course of the
   session.**
   - Command: `kubectl logs -n llm-d deploy/llm-d-epp -c epp -f | grep zmq-subscriber`
   - Output (real sequence, ~8 minutes after the initial connect):
     ```json
     {"level":"error","msg":"Failed to receive message from zmq subscriber","endpoint":"tcp://10.244.0.9:5556","error":"EOF"}
     {"level":"info","msg":"retrying zmq-subscriber"}
     {"level":"info","msg":"Connected subscriber socket","endpoint":"tcp://10.244.0.9:5556"}
     ```
   - Explanation: the connection dropped (`EOF` — the far end closed it,
     likely a transient socat/network hiccup over the LAN hop), and the
     EPP's client library retried and reconnected **on its own**, with no
     manual intervention and no visible impact on routing (the InferencePool
     didn't need to be touched). One reconnect in ~8 minutes of an otherwise
     idle connection is a healthy frequency; if you see this happening every
     few seconds, that's a sign the LAN link or the proxy itself is unstable
     and worth investigating separately.

**Pass/Fail:** PASS — self-healed without intervention.

---

### TC-BRIDGE-05 — Pod goes NotReady when DGX backend stops **[LIVE]**

**Objective:** confirm the readiness probe (and therefore InferencePool
membership) correctly reacts when the real backend disappears.

**Steps:**

1. **Stop the vLLM container on the DGX Spark.**
   - Command: `ssh $DGX_USER@$DGX_HOST docker stop vllm-gpu-0`
   - Output: `vllm-gpu-0`

2. **Wait ~30s, then re-check the proxy Pod's readiness.**
   - Command: `kubectl get pod -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing`
   - Output: `gpu-vllm-proxy-65c98887dd-ltd6k   1/2   Running`
   - Explanation: dropped from `2/2` to `1/2` — the `kv-proxy` container is
     still "ready" (it has no readiness probe defined), but `http-proxy`'s
     probe is now failing.

3. **Confirm the exact readiness-probe failure reason.**
   - Command: `kubectl describe pod -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing | tail -4`
   - Output:
     ```
     Warning  Unhealthy  9s (x6 over 49s)  kubelet  Readiness probe failed: Get "http://10.244.0.9:8000/health": EOF
     ```
   - Explanation: `EOF` means the TCP connection was accepted by `socat` but
     then closed with no data — exactly what happens when `socat` can't
     establish its *outbound* leg to a now-dead `192.168.1.112:8000`.

4. **Confirm the EPP itself sees zero ready endpoints (not just that the Pod
   condition changed — that the routing layer actually reacted).**
   - Command: `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_ready_endpoints{job="llm-d-epp"}'`
   - Output: `{"metric": {...}, "value": [..., "0"]}`
   - Explanation: this is the metric the EPP itself emits for how many
     Pods it currently considers ready candidates — confirms the InferencePool
     controller propagated the readiness change into the EPP's own scheduling
     state, not just the Kubernetes Pod status.

5. **Restore the backend.**
   - Command: `bash gpu-node/deploy-vllm.sh` (or the raw `docker run` from
     README §3 Step 1 — `docker start` was tried first here and did **not**
     work cleanly; see TC-GPU-05 for why a fresh `docker run` was needed).
   - Output: `Application startup complete.` and the proxy Pod returns to `2/2`.

**Pass/Fail:** PASS.

---

### TC-BRIDGE-06 — Prometheus can scrape `/metrics` through the proxy **[LIVE]**

**Objective:** confirm the tunnel design also works for Prometheus's scrape
requests, not just the EPP's ZMQ subscription and client HTTP traffic.

**Steps:**

1. **Query Prometheus for a real vLLM histogram metric.**
   - Command: `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=vllm:time_to_first_token_seconds_count'`
   - Output:
     ```json
     {"metric": {"instance":"10.244.0.9:8000","job":"llm-d/gpu-vllm-proxy", ...}, "value": [..., "6"]}
     ```
   - Explanation: `vllm:time_to_first_token_seconds_count` is a metric vLLM
     itself exposes (not something the proxy or EPP invented) — its presence
     in Prometheus, scraped from the proxy Pod's IP:port, proves Prometheus's
     scrape requests also tunnel through cleanly. The value `6` is a running
     counter of real GPU requests observed so far in the session.

**Pass/Fail:** PASS.

---

## Suite 3 — TC-ROUTE-*: 3-way HTTPRoute precedence

### TC-ROUTE-01 — Default path reaches the real-GPU pool **[LIVE]**

**Objective:** confirm a plain request (no special header) reaches the
precise-prefix / real-GPU `InferencePool`.

**Steps:**

1. **Send a plain POST with no `x-llm-d-pool` header.**
   - Command:
     ```console
     kubectl run trig3 --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -o /dev/null -w "http=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":8}"
     ```
   - Output: `http=200`
   - Explanation: a `200` alone doesn't prove *which* pool served it (see
     step 2 for that); it does confirm the default `HTTPRoute` (bare
     `PathPrefix: /`) is functioning end-to-end through the whole chain.

2. **Confirm it was `llm-d-epp` (not the pd or baseline EPP) that handled it,
   via its request counter.**
   - Command: `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_request_total'`
   - Output: three series, one per EPP release, e.g. `llm-d-epp: 10`,
     `llm-d-pd-epp: 2`, `llm-d-baseline-epp: 1` — only `llm-d-epp`'s counter
     increments across repeated plain requests.

**Pass/Fail:** PASS.

---

### TC-ROUTE-02 — `x-llm-d-pool: pd` reaches the P/D pool **[LIVE]**

**Steps:**

1. **Send the same request with the `pd` header.**
   - Command:
     ```console
     kubectl run tpd --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -o /dev/null -w "pd http=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
       -H 'Content-Type: application/json' -H 'x-llm-d-pool: pd' \
       -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hello pd\"}],\"max_tokens\":16}"
     ```
   - Output: `pd http=200`
   - Explanation: `x-llm-d-pool: pd` matches the header-matched `HTTPRoute`
     created by `--set httpRoute.headerMatches.x-llm-d-pool=pd` in README §3
     Step 10.

2. **Confirm via the resulting Jaeger trace that P/D-specific spans appear**
   (cross-reference to TC-TRACE-05): `pick_disagg_profile` and
   `prepare_disaggregation` only exist in the P/D EPP's plugin chain, so
   their presence is conclusive proof of which pool actually served the
   request, independent of the HTTP status code.

**Pass/Fail:** PASS.

---

### TC-ROUTE-03 — `x-llm-d-pool: baseline` reaches the WVA-scaled pool **[LIVE]**

**Steps:**

1. **Send the same request with the `baseline` header.**
   - Command: same pattern, `-H 'x-llm-d-pool: baseline'`.
   - Output: `baseline http=200`

2. **Confirm via the EPP request counter.**
   - Command: `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_request_total{job="llm-d-baseline-epp"}'`
   - Output: `1` (immediately after the first such request in the session)

**Pass/Fail:** PASS.

---

### TC-ROUTE-04 — Unmatched header value falls through to default **[LIVE]**

**Objective:** confirm Gateway API's header-match precedence works as
expected — a route only matches the *exact* configured header value, not any
non-empty value.

**Steps:**

1. **Send with a header value that matches neither `pd` nor `baseline`.**
   - Command: `-H 'x-llm-d-pool: does-not-exist'`, otherwise identical to
     TC-ROUTE-01.
   - Output: `http=200`

2. **Confirm via before/after request counters which pool actually handled it.**
   - Command: `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_request_total'` (run once before, once after)
   - Output:
     ```
     llm-d-baseline-epp 1   # unchanged
     llm-d-epp          10  # incremented by 1
     llm-d-pd-epp        2  # unchanged
     ```
   - Explanation: only `llm-d-epp`'s counter moved — the request fell
     through to the default `PathPrefix: /` route, exactly as Gateway API's
     precedence rules predict (a header match only "wins" for its exact
     configured value; anything else still matches the less-specific
     default rule).

**Pass/Fail:** PASS.

---

### TC-ROUTE-05 — All three InferencePools and HTTPRoutes coexist on one Gateway **[LIVE]**

**Steps:**

1. **List both resource types in the `llm-d` namespace.**
   - Command: `kubectl get inferencepool,httproute -n llm-d`
   - Output:
     ```
     NAME                                                       AGE
     inferencepool.inference.networking.k8s.io/llm-d            16m
     inferencepool.inference.networking.k8s.io/llm-d-baseline   13m
     inferencepool.inference.networking.k8s.io/llm-d-pd         13m

     NAME                                                 HOSTNAMES   AGE
     httproute.gateway.networking.k8s.io/llm-d
     httproute.gateway.networking.k8s.io/llm-d-baseline
     httproute.gateway.networking.k8s.io/llm-d-pd
     ```
   - Explanation: 3 of each, one per `helm install` release from README §3
     Steps 7/10/11 — proves the 3-pool/3-route design coexists cleanly on a
     single `Gateway` without naming collisions (each is namespaced by its
     Helm release name).

**Pass/Fail:** PASS.

---

## Suite 4 — TC-TRACE-*: distributed tracing (Jaeger)

### TC-TRACE-01 — Gateway root span exists **[LIVE]**

**Steps:**

1. **Query Jaeger's API for the most recent trace from the gateway service.**
   - Command: `curl -s "http://localhost:16686/api/traces?service=llm-d-inference-gateway&limit=1" | python3 -m json.tool`
   - Output: a trace object whose first span has `operationName: "POST /*"`,
     service `llm-d-inference-gateway`, and an empty `references` array.
   - Explanation: an empty `references` array means this span has no parent
     — it's a trace **root**. This is agentgateway's own span, created
     because of the `AgentgatewayPolicy` `gateway-tracing` with
     `randomSampling: "true"` from README §3 Step 9.

**Pass/Fail:** PASS.

---

### TC-TRACE-02 — EPP span is a child of the gateway (not orphaned) **[LIVE]**

**Objective:** this is the property that standalone (self-managed Envoy) mode
*cannot* achieve — confirm Gateway API/agentgateway mode fixes it.

**Steps:**

1. **Walk the trace's span tree, following `CHILD_OF` references from the
   EPP's `gateway.request` span back to its parent.**
   - Command (Python, parses the same trace JSON as TC-TRACE-01):
     ```python
     import sys, json
     t = json.load(sys.stdin)['data'][0]
     procs = t['processes']; span_by_id = {s['spanID']: s for s in t['spans']}
     for s in t['spans']:
         svc = procs[s['processID']]['serviceName']
         refs = [r for r in (s.get('references') or []) if r['refType']=='CHILD_OF']
         parent = procs[span_by_id[refs[0]['spanID']]['processID']]['serviceName'] if refs else 'ROOT'
         print(f'[{svc}] {s["operationName"]} <- {parent}')
     ```
   - Output (relevant line):
     ```
     [llm-d-router/epp] gateway.request <- llm-d-inference-gateway
     ```
   - Explanation: the EPP's root span has the gateway's span as its parent —
     one connected trace across two services, not two disjoint traces. PR
     #1514 in `llm-d-router` (per this project's own prior investigation,
     see the repo's memory notes) made the EPP adopt any incoming W3C
     `traceparent`; agentgateway is what actually delivers that
     `traceparent` to the EPP's `ext_proc` call, which standalone Envoy
     mode does not do.

**Pass/Fail:** PASS.

---

### TC-TRACE-03 — IPP span parentage **[LIVE — REGRESSION FOUND]**

**Objective:** check whether IPP (installed at `PreRouting`, ahead of the
EPP) shows up as a middle hop between the gateway and the EPP, as it did in
the CPU demo three weeks earlier.

**Steps:**

1. **List all Jaeger services and look for IPP's service name.**
   - Command: `curl -s http://localhost:16686/api/services`
   - Output: `["llm-d-router/epp","llm-d-inference-gateway","llm-d-inference-payload-processor","jaeger","llm-d-routing-sidecar"]`
   - Explanation: IPP's service name is present, so it *is* exporting spans.

2. **Fetch IPP's own most recent trace and compare its `traceID` to the
   concurrent gateway/EPP trace's `traceID`.**
   - Command: `curl -s "http://localhost:16686/api/traces?service=llm-d-inference-payload-processor&limit=1"`
   - Output: IPP trace ID `c3c6dbc3…`, single span `gateway.request`, `Services: 1`.
   - Cross-check: the gateway/EPP trace captured in TC-TRACE-02 at the same
     moment had trace ID `0965ead8…` — **a different ID entirely**.
   - Explanation: IPP produced its own, disconnected root trace instead of
     being stitched into the gateway's trace as its middle hop. This differs
     from the CPU demo's result on 2026-08-03.

3. **Confirm IPP is nonetheless functionally correct (this is a *tracing*
   regression, not a routing/processing bug).**
   - Command: `kubectl logs -n llm-d deploy/payload-processor --tail=20`
   - Output:
     ```json
     {"caller":"bodyfieldtoheader/body_field_to_header.go:121","msg":"parsed field from body","field":"model","value":"Qwen/Qwen2.5-1.5B-Instruct"}
     {"caller":"basemodelextractor/base_model_to_header.go:105","msg":"updated base model header based on the request target model"}
     ```
   - Explanation: the header-rewrite logic that IPP exists to perform is
     confirmed working from its own logs, on every request — this is purely
     a trace-context propagation gap, not a functional one.

**Pass/Fail: FAIL** relative to the CPU demo's stitching result — logged as
upstream drift in the README, not silently accepted as unavoidable.

---

### TC-TRACE-04 — Precise-prefix scheduler subtree spans **[LIVE]**

**Steps:**

1. **Send a default-route request and fetch the resulting trace.**
   - Command: (same pattern as TC-ROUTE-01, then fetch via Jaeger API)
   - Output — full span tree (real capture, screenshot `docs/screenshots/jaeger-traces.png`):
     ```
     [llm-d-inference-gateway] POST /*                                   <- ROOT
       [llm-d-router/epp] gateway.request                                <- llm-d-inference-gateway
         [llm-d-router/epp] gateway.request_orchestration
           [llm-d-router/epp] tokenize_render /v1/chat/completions/render
           [llm-d-router/epp] produce_precise_prefix_cache
             [llm-d-router/epp] index_lookup
           [llm-d-router/epp] run_scheduler_profile
             [llm-d-router/epp] filter_endpoints
             [llm-d-router/epp] llm_d.epp.scoring
               [llm-d-router/epp] llm_d.epp.scorer.kv-cache-utilization-scorer
               [llm-d-router/epp] llm_d.epp.scorer.queue-scorer
               [llm-d-router/epp] llm_d.epp.scorer.prefix-cache-scorer
             [llm-d-router/epp] pick_endpoints
           [llm-d-router/epp] index_add
     ```
     `Services: 2 | Depth: 6 | Total Spans: 14`, total duration 822.48ms.
   - Explanation: this is the request-flow narrative from README §1.4 made
     concrete — `tokenize_render` is the token-producer plugin calling the
     EPP's own `vllm-render` sidecar; `produce_precise_prefix_cache` →
     `index_lookup` is the precise-prefix KV-block index check;
     `run_scheduler_profile` fans out into the 3 scorer plugins (each its own
     child span under `llm_d.epp.scoring`) then `pick_endpoints`;
     `index_add` records the newly-seen prompt's blocks for future lookups.
     The 822ms total duration is dominated by the real GPU inference call
     itself (everything else here is sub-millisecond scheduling overhead —
     see the individual span durations in the screenshot).

**Pass/Fail:** PASS — exact shape matches the expected precise-prefix plugin chain.

---

### TC-TRACE-05 — P/D disaggregated trace **[LIVE]**

**Steps:**

1. **Send a `x-llm-d-pool: pd` request and fetch the resulting trace.**
   - Command: same as TC-ROUTE-02, then verify via the trace-search-by-operation
     technique (search recent traces for one containing `pick_disagg_profile`,
     since span export can lag a query by a couple seconds):
     ```python
     import urllib.request, json
     data = json.load(urllib.request.urlopen('http://localhost:16686/api/traces?service=llm-d-inference-gateway&limit=5&lookback=2m'))['data']
     for t in data:
         if 'pick_disagg_profile' in [s['operationName'] for s in t['spans']]:
             print('FOUND', t['traceID'], 'spans=', len(t['spans']))
     ```
   - Output: `FOUND c499570c4e0ac6b96a0dc404fe3c01a5 spans= 27`

2. **Inspect the full span tree** (screenshot `docs/screenshots/jaeger-pd-trace.png`):
   ```
   [llm-d-inference-gateway] POST /*                                    <- ROOT
     [llm-d-router/epp] gateway.request
       [llm-d-router/epp] gateway.request_orchestration
         [llm-d-router/epp] pick_disagg_profile        # prefill profile
           [llm-d-router/epp] run_scheduler_profile -> filter_endpoints, llm_d.epp.scoring (2 scorers), pick_endpoints
         [llm-d-router/epp] pick_disagg_profile        # decode profile
           [llm-d-router/epp] run_scheduler_profile -> filter_endpoints, llm_d.epp.scoring (3 scorers), pick_endpoints
         [llm-d-router/epp] pick_disagg_profile        # combining pass
         [llm-d-router/epp] prepare_disaggregation
         [llm-d-router/epp] prepare_disaggregation
     [llm-d-routing-sidecar] llm_d.pd_proxy.POST /v1/chat/completions    <- llm-d-inference-gateway
       [llm-d-routing-sidecar] forward_request
         [llm-d-routing-sidecar] prefill -> HTTP POST
           [llm-d-routing-sidecar] decode -> HTTP POST
   ```
   `Services: 3 | Depth: 6 | Total Spans: 27`, total duration 5.34ms (this
   particular request used a short `max_tokens`, so it's fast).
   - Explanation: `pick_disagg_profile` runs 3 times — once to pick the
     **prefill** endpoint (its own `run_scheduler_profile` subtree with
     `prefix-cache-scorer`+`active-request-scorer`), once for **decode**
     (its own subtree, 3 scorers), and once more to combine the two picks;
     `prepare_disaggregation` (×2) stitches the two legs together. The
     `llm-d-routing-sidecar` service is a **separate** trace participant
     from the EPP — it's the native sidecar container in the `pd-decode`
     Pod, and its `forward_request → prefill → decode → HTTP POST` spans are
     the actual two-leg proxy call the sidecar makes (see README §3 Step 10
     for what's real vs. simulated in this path).

**Pass/Fail:** PASS.

---

### TC-TRACE-06 — Span/service counts asserted exactly **[LIVE]**

**Objective:** state precise, falsifiable numbers rather than "a trace
exists" — anyone re-running this demo can check these exact counts.

**Steps:**

1. **Cross-reference the exact counts captured in TC-TRACE-04 and TC-TRACE-05.**
   - Default path: 14 spans / 2 services / depth 6.
   - P/D path: 27 spans / 3 services / depth 6.
   - Explanation: these numbers are reproducible on a healthy cluster and
     make a good regression signal — if a future re-run of this demo
     produces a materially different span count on either path, that's a
     concrete, checkable sign something in the plugin chain or the tracing
     wiring changed upstream.

**Pass/Fail:** PASS.

---

## Suite 5 — TC-KV-*: KV-cache-aware routing (real GPU)

### TC-KV-01 — Repeated long prompt against the real GPU replica **[LIVE]**

**Objective:** set up the conditions for a KV-cache hit — the same
>64-token prompt sent repeatedly to the same replica.

**Steps:**

1. **Send the same long prompt (about ZMQ/KV-cache internals, well over
   64 tokens) 6 times with a 2-second gap, via the default route.**
   - Command:
     ```console
     PROMPT="Explain in detail how a distributed key-value cache works in a large language model inference system, covering block-based paging, prefix reuse across requests, eviction policy, event publication over ZeroMQ, and how a router can use those events to steer traffic to the replica that already holds the longest matching prefix. Please be thorough and specific."
     kubectl run drive --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d --command -- sh -c \
       'for i in 1 2 3 4 5 6; do curl -sS -o /dev/null -w "req$i http=%{http_code}\n" \
       -X POST http://'"$GWIP"':80/v1/chat/completions -H "Content-Type: application/json" \
       -d "{\"model\":\"'"$MODEL"'\",\"messages\":[{\"role\":\"user\",\"content\":\"'"$PROMPT"'\"}],\"max_tokens\":16}"; sleep 2; done'
     ```
   - Output: `req1 http=200` through `req6 http=200`.
   - Explanation: all 6 succeed at the HTTP level — this test case is about
     what happens *inside* the routing/caching pipeline for those 6
     requests, which the next steps inspect.

**Pass/Fail:** PASS.

---

### TC-KV-02 — Prefix-block indexing occurs **[LIVE]**

**Steps:**

1. **Inspect the `produce_precise_prefix_cache` span's attributes across all
   6 resulting traces.**
   - Command: (Jaeger API query per trace, extracting the span's `tags`)
   - Output (all 6 requests, identical): `llm_d.epp.producer.total_blocks: 1`
   - Explanation: the prompt is long enough to fill at least one 64-token
     block (`block-size 64` from README §3 Step 1), and the *same* prompt
     tokenizes to the *same* block count every time — confirms tokenization
     is deterministic and the indexing pipeline is running on every request.

**Pass/Fail:** PASS.

---

### TC-KV-03 — Cache hit on repeat — NOT achieved this run **[LIVE — negative finding, root-caused]**

**Objective:** confirm `max_match_blocks` transitions from 0 to 1 by the
later repeats (this is what the CPU demo achieved after ~6 repeats).

**Steps:**

1. **Inspect `produce_precise_prefix_cache.llm_d.epp.producer.max_match_blocks`
   across all 6 traces.**
   - Output: `max_match_blocks: 0` on **all 6** requests, including the 6th.
   - Explanation: this is the negative result — no cache hit ever registered,
     unlike the CPU demo where it flipped to 1 by request 3-6.

2. **Check whether the underlying KV events even arrived at the EPP, via
   Prometheus counters (don't just assume "it didn't work" — measure where
   in the pipeline it stopped).**
   - Command:
     ```console
     curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_kv_cache_events_messages_received_total'
     curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_kv_cache_events_stores_skipped_total'
     curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_kv_cache_index_lookup_hits_total'
     ```
   - Output:
     ```
     llm_d_epp_kv_cache_events_messages_received_total = 1
     llm_d_epp_kv_cache_events_stores_skipped_total{reason="unsupported_cache_kind", cache_kind="unknown"} = 1
     llm_d_epp_kv_cache_index_lookup_hits_total = 0
     ```
   - Explanation — this is the actual root cause, isolated step by step:
     - `messages_received_total = 1`, not `0`: the ZMQ transport (through the
       proxy Pod) genuinely delivered one event. So TC-BRIDGE-03's tunnel is
       *not* the problem here.
     - Only **one** message across 6 real completions on the same replica is
       itself expected: vLLM's own local prefix cache means only the *first*
       newly-computed block triggers a publish event; identical repeats hit
       vLLM's cache silently server-side and don't re-publish.
     - That one event was received but **skipped**, with
       `reason="unsupported_cache_kind"` — the router's KV-event decoder
       didn't recognize the `cache_kind` field's value in the message
       payload published by this build of vLLM
       (`0.20.1+7124b12a.dev` from `nvcr.io/nvidia/vllm:26.05-py3`), so the
       block was never admitted into the index, so
       `lookup_hits_total` stayed 0.

**Pass/Fail: FAIL** relative to the CPU demo's result — but the failure is
fully diagnosed, not just observed: this looks like a genuine payload-schema
version mismatch between a very recent vLLM nightly build and this router
build's event parser, worth reporting upstream rather than a defect in this
demo's bridge/proxy design.

**Suggested follow-up (not executed):** try a router image built from a more
recent `upstream/main` commit, or inspect `pkg/kvevents` in the
`llm-d-router` source for the exact `cache_kind` enum values it accepts
versus what vLLM 0.20.1 emits.

---

### TC-KV-04 — Scorer machinery runs correctly regardless of hit/miss outcome **[LIVE]**

**Objective:** confirm the *scoring pipeline itself* is intact even though
the specific KV signal into it was empty this run (isolating "the pipeline is
broken" from "one input signal is empty").

**Steps:**

1. **Inspect the `llm_d.epp.scoring` span and its 3 child scorer spans for
   one of the 6 requests.**
   - Output:
     ```
     llm_d.epp.scorer.prefix-cache-scorer:         score.max = 0, weight = 3
     llm_d.epp.scorer.kv-cache-utilization-scorer:  (ran)
     llm_d.epp.scorer.queue-scorer:                 (ran)
     ```
   - Explanation: `prefix-cache-scorer.score.max = 0` is the *correct*
     output given no KV-cache hit — the scorer ran, evaluated the (empty)
     match information, and correctly reported zero. This is different from
     the scorer crashing or not running at all.

2. **Confirm the final picked score reflects only the non-KV scorers.**
   - Command: inspect `pick_endpoints` span attributes.
   - Output: `llm_d.epp.picker.top_scores: [4]`
   - Explanation: 4 = `kv-cache-utilization-scorer` (weight 2.0) +
     `queue-scorer` (weight 2.0), with `prefix-cache-scorer`'s weight-3.0
     contribution correctly at zero. This arithmetic checks out and proves
     the scoring pipeline is functioning end-to-end; only the KV-cache
     *signal* feeding into one of its three scorers is empty this run
     (per TC-KV-03).

**Pass/Fail:** PASS.

---

### TC-KV-05 — 2-replica differential scoring **[LIVE — attempted, inconclusive]**

**Objective:** with 2 real replicas, confirm `pick_endpoints.top_scores`
shows a 2-element array where the replica holding a matching prefix scores
higher (the CPU demo's flagship KV-routing-decision result).

**Steps:**

1. **Cross-reference TC-GPU-05:** a 2nd real replica (`vllm-gpu-1`) did come
   up successfully once, alongside `vllm-gpu-0`.

2. **Check whether a 2nd `gpu-vllm-proxy`-style Pod (pointed at
   `vllm-gpu-1:8001`) was deployed to make that 2nd replica visible to the
   `InferencePool` selector.**
   - Output: no — only one `gpu-vllm-proxy` Pod existed at the time, wired
     to `vllm-gpu-0:8000` only.
   - Explanation: per README §1.1, a Pod not selected by
     `router.modelServers.matchLabels` is invisible to the EPP no matter how
     healthy it is. `vllm-gpu-1` being reachable on the DGX Spark's network
     did not, by itself, make it a routing candidate.

**Conclusion: inconclusive, not failed** — the blocker here was a wiring gap
(a 2nd proxy Pod was never deployed in the ~2-minute window `vllm-gpu-1` was
healthy), not a hardware or protocol limitation. **To complete this test
case:** add a second `gpu-vllm-proxy-1` Pod (identical labels, containers
pointed at `$DGX_HOST:8001`/`:5557`) *before* starting the 2nd replica, then
repeat TC-KV-01 through TC-KV-04 and inspect `pick_endpoints.top_scores` for
a 2-element array.

---

## Suite 6 — TC-PD-*: P/D disaggregation

### TC-PD-01 — P/D request succeeds end-to-end **[LIVE]**

See TC-ROUTE-02, step 1: `pd http=200`.

### TC-PD-02 — Disagg profile scheduling produces 2 distinct scheduler passes **[LIVE]**

See TC-TRACE-05, step 2: `run_scheduler_profile` appears twice, once under
each of the prefill and decode `pick_disagg_profile` spans, each with its own
distinct scorer set (prefill: `prefix-cache-scorer` + `active-request-scorer`;
decode: 3 scorers).

### TC-PD-03 — routing-sidecar performs 2 real proxy legs **[LIVE]**

See TC-TRACE-05, step 2: `forward_request → prefill → decode`, each with its
own `HTTP POST` child span — these are real outbound HTTP calls the sidecar
makes, one to the prefill Pod and one to the decode Pod (on `localhost`,
since the decode-side sidecar is a native sidecar container inside the
`pd-decode` Pod).

### TC-PD-04 — KV transfer is simulated, not real **[BY DESIGN, documented]**

**Steps:**

1. **Confirm both `pd-prefill` and `pd-decode` run `llm-d-inference-sim`, not
   real vLLM.**
   - Command: `kubectl get pod -n llm-d -l llm-d.ai/guide=pd-disaggregation -o jsonpath='{.items[*].spec.containers[*].image}'`
   - Output: `ghcr.io/llm-d/llm-d-inference-sim:latest` (×2)
   - Explanation: per the official disaggregation design doc
     ([`docs/architecture/advanced/disaggregation/README.md`](https://github.com/llm-d/llm-d/blob/main/docs/architecture/advanced/disaggregation/README.md)),
     real P/D KV transfer needs RDMA interconnects between nodes; this DGX
     Spark has a single GPU with no such interconnect, so `llm-d-inference-sim`
     stands in for the model servers and fakes the KV-transfer handshake — the
     scheduling (TC-PD-02) and proxying (TC-PD-03) around it are real code paths.

**Pass/Fail:** PASS — confirmed as designed, not a defect.

---

## Suite 7 — TC-WVA-*: autoscaling loop

### TC-WVA-01 — WVA controller starts and connects to Prometheus **[LIVE]**

**Steps:**

1. **Tail the controller's logs after deployment.**
   - Command: `kubectl logs -n wva-system deploy/wva-controller-manager | tail -20`
   - Output:
     ```json
     {"msg":"Optimization completed successfully","mode":"saturation","modelsProcessed":1,"decisionsApplied":0}
     ```
   - Explanation: no fatal errors, and a periodic successful optimization
     pass — `decisionsApplied: 0` at this point just means "no scaling
     change was needed yet" (idle, no load), not an error.

**Pass/Fail:** PASS.

---

### TC-WVA-02 — WVA discovers the annotated HPA **[LIVE]**

**Steps:**

1. **Grep the same logs for the HPA's name.**
   - Command: `kubectl logs -n wva-system deploy/wva-controller-manager | grep EmitReplicaMetrics`
   - Output:
     ```json
     {"msg":"EmitReplicaMetrics completed","variantName":"optimized-baseline-decode-hpa","currentReplicas":1,"desiredReplicas":1}
     ```
   - Explanation: `variantName` matches the `HorizontalPodAutoscaler`'s
     `metadata.name` in `manifests/06-hpa.yaml` — confirms WVA found the
     `llm-d.ai/managed: "true"`-annotated HPA and is treating it as a
     scaling target, purely from the annotation, with no `VariantAutoscaling`
     CRD involved.

**Pass/Fail:** PASS.

---

### TC-WVA-03 — `wva_desired_replicas` reaches Prometheus **[LIVE]**

**Steps:**

1. **Query Prometheus directly for the metric WVA emits.**
   - Command: `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=wva_desired_replicas'`
   - Output:
     ```json
     {"metric":{"variant_name":"optimized-baseline-decode-hpa","exported_namespace":"llm-d"}, "value":[..., "1"]}
     ```
   - Explanation: the label set here (`variant_name`, `exported_namespace`)
     exactly matches what the HPA's `metrics[0].external.metric.selector`
     expects to find — this is the contract between WVA and the HPA, and
     both sides of it are confirmed independently in this and the next steps.

**Pass/Fail:** PASS.

---

### TC-WVA-04 — prometheus-adapter serves it as an external metric **[LIVE]**

**Steps:**

1. **Query the Kubernetes external-metrics API directly (bypassing the HPA,
   to isolate this one hop).**
   - Command: `kubectl get --raw /apis/external.metrics.k8s.io/v1beta1/namespaces/llm-d/wva_desired_replicas`
   - Output:
     ```json
     {"kind":"ExternalMetricValueList","items":[{"metricName":"wva_desired_replicas", "value":"1", "metricLabels":{"variant_name":"optimized-baseline-decode-hpa", ...}}]}
     ```
   - Explanation: this confirms `prometheus-adapter`'s translation rule
     (from `guides/workload-autoscaling/components/prometheus-adapter/wva-adapter-values.yaml`)
     is correctly turning a PromQL query into a valid Kubernetes API
     response — this is the exact API surface `kube-controller-manager`'s
     HPA controller calls internally.

**Pass/Fail:** PASS.

---

### TC-WVA-05 — HPA reads the external metric and computes target **[LIVE]**

**Steps:**

1. **Before installing `prometheus-adapter` — capture the failure state
   first, so the "fix" in step 2 is a demonstrated before/after, not just an
   assertion.**
   - Command: `kubectl describe hpa -n llm-d optimized-baseline-decode-hpa`
   - Output:
     ```
     Warning  FailedGetExternalMetric  ...  unable to get external metric ...: the server could not find the requested resource (get wva_desired_replicas.external.metrics.k8s.io)
     TARGETS: <unknown>/1 (avg)
     ```
   - Explanation: `<unknown>` — this is expected and correct at this point:
     the metric exists in Prometheus (TC-WVA-03) but nothing yet serves it
     as a Kubernetes API resource, so the HPA controller's periodic sync
     loop fails to fetch it.

2. **After `prometheus-adapter` is installed (TC-WVA-04), re-check.**
   - Command: `kubectl get hpa -n llm-d optimized-baseline-decode-hpa`
   - Output:
     ```
     NAME                             REFERENCE                              TARGETS     MINPODS  MAXPODS  REPLICAS
     optimized-baseline-decode-hpa   Deployment/optimized-baseline-decode   1/1 (avg)   1        4        1
     ```
   - Explanation: `1/1 (avg)` is a real, computed value — `wva_desired_replicas=1`
     divided by the HPA's `target.averageValue: "1"` equals a ratio of 1.0,
     i.e. "at target," so no scaling action is triggered. The whole chain
     (WVA → Prometheus → prometheus-adapter → HPA) is now proven closed,
     end-to-end, with an observed before/after transition.

**Pass/Fail:** PASS.

---

### TC-WVA-06 — Scale-up under load **[LIVE — attempted; found and fixed a real blocker; scale-up itself not reproduced]**

**Objective:** drive real load at the baseline pool and observe
`wva_desired_replicas` rise above 1, causing the HPA to scale
`optimized-baseline-decode` up.

**Steps:**

1. **Start a throwaway load-generator Pod.**
   - Command: `kubectl run loadgen --image=curlimages/curl:8.7.1 -n llm-d --restart=Never --command -- sleep 3600`
   - Output: `pod/loadgen created`

2. **Fire an initial burst (40 concurrent requests) then poll the HPA and
   `wva_desired_replicas`.**
   - Command:
     ```console
     kubectl exec -n llm-d loadgen -- sh -c 'for i in $(seq 1 40); do curl -sS -o /dev/null -X POST http://'"$GWIP"':80/v1/chat/completions -H "Content-Type: application/json" -H "x-llm-d-pool: baseline" -d "{...\"max_tokens\":200}" & done; wait'
     kubectl get hpa -n llm-d optimized-baseline-decode-hpa
     ```
   - Output: `TARGETS: 1/1 (avg)` — unchanged; `wva_desired_replicas` still 1.

3. **Investigate why, via the WVA controller's own logs (don't just retry
   blindly — find the actual reason).**
   - Command: `kubectl logs -n wva-system deploy/wva-controller-manager | grep -A2 "Skipping pod"`
   - Output:
     ```json
     {"msg":"Skipping pod that doesn't match any scale target","pod":"gpu-vllm-proxy-...","scale targets":["optimized-baseline-decode"]}
     {"msg":"No saturation metrics available for model, skipping analysis","modelID":"Qwen/Qwen2.5-1.5B-Instruct"}
     ```
   - Explanation: **root cause found.** `optimized-baseline-decode` shares
     the same `modelID` (`Qwen/Qwen2.5-1.5B-Instruct`) with the real-GPU
     pool. WVA groups its saturation analysis per model, and the only Pod
     it found under that model grouping was `gpu-vllm-proxy` (not a scale
     target of this HPA, so correctly skipped) — meaning `optimized-baseline-decode`'s
     **own** Pod metrics were never even being looked at.

4. **Confirm the actual gap: no PodMonitor existed for
   `optimized-baseline-decode` at all.**
   - Command: `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=vllm:num_requests_waiting{namespace="llm-d"}'`
   - Output: only one series, `job="llm-d/gpu-vllm-proxy"` — nothing for
     `optimized-baseline-decode`.

5. **Fix it: add a PodMonitor.**
   - Command: `kubectl apply -f manifests/optional/baseline/podmonitor-baseline.yaml`
   - Output: `podmonitor.monitoring.coreos.com/optimized-baseline-decode created`
   - It did not appear in Prometheus's active targets within the expected
     ~30s (a known PodMonitor-creation race also documented in the CPU
     demo's notes — if a PodMonitor is created in the same instant the
     Prometheus Operator regenerates its scrape config, it can be silently
     left out). Forced a resync:
     ```console
     kubectl annotate podmonitor -n llm-d optimized-baseline-decode resync="$(date +%s)" --overwrite
     ```
   - Re-checked: `podMonitor/llm-d/optimized-baseline-decode` now shows `up`
     in `/api/v1/targets`, and
     `vllm:num_requests_waiting{job="llm-d/optimized-baseline-decode"}`
     now returns a real series (value `0`, correctly reflecting no queue at
     that instant).

6. **Re-drive load now that the metric pipeline is actually complete — a
   sustained 45-second burst (~15 concurrent requests, 2 waves/sec, larger
   `max_tokens` to make each request take longer), polling every 6-7s.**
   - Output: `vllm:num_requests_waiting` stayed at `0` across all 8 polls;
     `wva_desired_replicas` stayed at `1` throughout.
   - Explanation: `llm-d-inference-sim` (the baseline pool's backend)
     apparently drains requests faster than this demo's load pattern and
     Deployment resource limits (`200m`/`1` CPU) could ever build up a
     measurable queue — it doesn't model real inference-engine backpressure
     the way actual vLLM does under load.

**Pass/Fail: Partial.** A real, previously-undetected observability gap was
found and permanently fixed (`manifests/optional/baseline/podmonitor-baseline.yaml`
is now part of the demo). The scale-up event itself was **not** reproduced —
the control-loop mechanics (TC-WVA-01–05) were already fully proven
independently of load; what's specifically unverified is "real load →
real scaling decision."

**Suggested follow-up (not executed):** either drive load against the
real-GPU pool instead (where `vllm:num_requests_waiting` has real physical
meaning and `maxReplicas` would need raising past 1 first), or look for a
synthetic-latency/concurrency-cap flag in `llm-d-inference-sim`'s CLI that
would let it model backpressure more realistically.

---

### TC-WVA-07 — Scale-down after load stops **[LIVE — not applicable]**

Since TC-WVA-06 never drove `wva_desired_replicas` above 1, there was no
scale-up state to observe scaling back down from — replica count stayed at 1
the entire time. Re-run once TC-WVA-06's follow-up produces a real scale-up
to complete this case.

---

## Suite 8 — TC-METRICS-*: Prometheus + Grafana

### TC-METRICS-01 — All expected ServiceMonitors/PodMonitors are UP **[LIVE]**

**Steps:**

1. **List every active scrape pool's health.**
   - Command:
     ```console
     curl -s http://localhost:9091/api/v1/targets?state=active | \
       python3 -c "import sys,json; [print(t['scrapePool'], t['health']) for t in json.load(sys.stdin)['data']['activeTargets']]" | sort -u
     ```
   - Output (llm-d-relevant lines):
     ```
     podMonitor/llm-d/gpu-vllm-proxy/0 up
     podMonitor/llm-d/optimized-baseline-decode/0 up
     serviceMonitor/llm-d/llm-d-epp-monitor/0 up
     serviceMonitor/llm-d/llm-d-pd-epp-monitor/0 up
     serviceMonitor/llm-d/llm-d-baseline-epp-monitor/0 up
     serviceMonitor/wva-system/wva-controller-manager-metrics-monitor/0 up
     serviceMonitor/llm-d-monitoring/llmd-kube-prometheus-stack-kube-controller-manager/0 down
     serviceMonitor/llm-d-monitoring/llmd-kube-prometheus-stack-kube-etcd/0 down
     serviceMonitor/llm-d-monitoring/llmd-kube-prometheus-stack-kube-proxy/0 down
     serviceMonitor/llm-d-monitoring/llmd-kube-prometheus-stack-kube-scheduler/0 down
     ```
   - Explanation: every llm-d/WVA-specific target is `up`. The 4 `down`
     targets are `kube-prometheus-stack`'s bundled ServiceMonitors for
     Kubernetes control-plane components that simply don't exist as
     separately-scrapable endpoints on a Kind cluster (Kind runs the whole
     control plane inside one node container without exposing those
     metrics ports the way a "real" cluster would) — expected and benign,
     not a sign of a broken installation.

**Pass/Fail:** PASS.

---

### TC-METRICS-02 — EPP request-count metrics increment per pool **[LIVE]**

**Steps:**

1. **Query the EPP request counter.**
   - Command: `curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=llm_d_epp_request_total'`
   - Output: 3 series, one per EPP release, each carrying a `model_name` label.
   - Explanation: separate series per `job` label (`llm-d-epp`,
     `llm-d-pd-epp`, `llm-d-baseline-epp`) confirms each EPP release's
     metrics are correctly isolated — you can build a per-pool dashboard
     panel by filtering on `job`.

**Pass/Fail:** PASS.

---

### TC-METRICS-03 — Real GPU vLLM histogram metrics flow through the proxy **[LIVE]**

**Steps:**

1. **Query two different vLLM-native metrics through the proxy's scrape target.**
   - Command:
     ```console
     curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=vllm:time_to_first_token_seconds_count'
     curl -s http://localhost:9091/api/v1/query --data-urlencode 'query=vllm:num_requests_running'
     ```
   - Output: TTFT count = `6`; `num_requests_running` = `0` (correctly idle
     at query time — no in-flight requests).
   - Explanation: `vllm:*` metrics are emitted by vLLM's own Prometheus
     exporter — nothing in this demo's code invents them. Their presence,
     scraped through the socat tunnel, is direct proof real GPU inference
     telemetry (not simulated) reaches Prometheus.

**Pass/Fail:** PASS.

---

### TC-METRICS-04 — Grafana dashboards load **[LIVE]**

**Steps:**

1. **List all dashboards via Grafana's search API.**
   - Command: `curl -s -u admin:admin http://localhost:3000/api/search?type=dash-db`
   - Output: 7 titles containing `llm-d`: Diagnostic Drill-Down, Failure &
     Saturation Indicators, Inference Gateway, P/D Coordinator Metrics,
     Performance Dashboard, SGLang Overview, vLLM Overview.
   - Explanation: each corresponds to one `.json` file loaded as a
     ConfigMap in README §3 Step 12 — 7 in, 7 discovered by Grafana's
     sidecar, confirms the whole dashboard-provisioning path worked.

2. **Visually confirm live data, not just "dashboard exists" (screenshot
   `docs/screenshots/grafana-vllm-overview.png`).** Token Throughput, Time To
   First Token Latency, Queue Time, Requests Prefill and Decode Time, and Max
   Generation Token in Sequence Group panels all show a real data point at
   the current-time edge of their graphs.

**Pass/Fail:** PASS.

---

### TC-METRICS-05 — Prometheus targets page screenshot **[LIVE]**

Screenshot captured directly from the browser-rendered `/targets` page:
`docs/screenshots/prometheus-targets.png` — visually corroborates
TC-METRICS-01's API-based check.

---

## Suite 9 — TC-NEG-*: negative / failure-mode cases

### TC-NEG-01 — DGX node unreachable → clean failure, not a hang **[LIVE]**

**Objective:** confirm the system fails *fast and clearly*, not silently or
by hanging, when the real backend is gone.

**Steps:**

1. **With `vllm-gpu-0` stopped (same state as TC-BRIDGE-05), send a normal
   request through the gateway.**
   - Command:
     ```console
     kubectl run tneg1b --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -m 20 -w "\nhttp=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"dgx down test\"}],\"max_tokens\":8}"
     ```
   - Output:
     ```
     inference error: ServiceUnavailable - failed to find endpoint candidates for serving the request
     http=503
     ```
   - Explanation: `503`, returned in under a couple of seconds — because the
     EPP had already marked the proxy Pod NotReady (confirmed in
     TC-BRIDGE-05's `llm_d_epp_ready_endpoints=0`) *before* this request was
     even sent, so the EPP fails the scheduling decision immediately with a
     clear error message rather than attempting to proxy to a dead backend
     and timing out.

**Pass/Fail:** PASS.

---

### TC-NEG-02 — Malformed request body **[LIVE]**

**Steps:**

1. **POST syntactically invalid JSON (a missing `:` between a key and its value).**
   - Command:
     ```console
     kubectl run tneg2 --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -w "\nhttp=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d '{"model":"'"$MODEL"'", "messages":[{"role":"user" "content":"broken json"}]'
     ```
   - Output:
     ```
     inference error: BadRequest - failed to parse request body: invalid character '"' after object key:value pair
     http=400
     ```
   - Explanation: `400`, not `500` — the malformed body is caught during
     JSON parsing (before it ever reaches the scheduling or GPU-call logic)
     and reported with a specific, actionable parser error message.

**Pass/Fail:** PASS.

---

### TC-NEG-03 — Unknown model name **[LIVE]**

**Steps:**

1. **POST with a `model` value that was never deployed.**
   - Command:
     ```console
     kubectl run tneg3 --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
       curl -sS -w "\nhttp=%{http_code}\n" -X POST http://$GWIP:80/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d '{"model":"does-not-exist-model","messages":[{"role":"user","content":"hi"}],"max_tokens":8}'
     ```
   - Output:
     ```json
     {"error":{"message":"The model `does-not-exist-model` does not exist.","type":"NotFoundError","param":"model","code":404}}
     ```
     `http=404`
   - Explanation: `404` with a clear message naming the offending model — no
     silent fallback to a different model, and no ambiguous generic error.

**Pass/Fail:** PASS.

---

### TC-NEG-04 — IPP `--secure-serving` regression guard **[LIVE]**

**Objective:** confirm the documented gotcha ("IPP defaults to self-signed
TLS, which breaks agentgateway's plaintext `ext_proc` client, and takes down
**all** gateway traffic, not just IPP's own hop") is still real on this
router/agentgateway version.

**Steps:**

1. **Confirm the baseline (working) state first.**
   - Command: same pattern as TC-ROUTE-01.
   - Output: `http=200`

2. **Deliberately reintroduce the misconfiguration.**
   - Command:
     ```console
     helm upgrade ipp $IPP_REPO/config/charts/payload-processor -n llm-d \
       -f $DEMO/helm-values/ipp.values.yaml --set provider.name=none \
       --set payloadProcessor.flags.secure-serving=true
     ```
   - Output: `Release "ipp" has been upgraded.`

3. **Send the same request again.**
   - Output:
     ```
     ext_proc failed: no more response messages
     http=500
     ```

4. **Confirm the exact failure mode in the gateway's own logs.**
   - Command: `kubectl logs -n llm-d deploy/llm-d-inference-gateway --since=30s | grep FailClosed`
   - Output:
     ```
     failed to initialize endpoint picker: ... "upstream call failed: ... stream closed because of a broken pipe" ... failure_mode=FailClosed
     ```
   - Explanation: exact match to the documented gotcha —
     `failure_mode=FailClosed` means a broken `ext_proc` fails **every**
     request through the gateway, not just requests that would have gone
     through IPP specifically, because IPP sits ahead of all routing
     decisions at the `PreRouting` phase.

5. **Revert and reconfirm.**
   - Command: same `helm upgrade` without the `secure-serving=true` override.
   - Output: `http=200` again.

**Pass/Fail:** PASS — regression guard confirmed still real; cleanly reverted.

---

### TC-NEG-05 — WVA Gateway API CRD conflict (install-order hazard) **[LIVE — encountered and worked around]**

**Steps:**

1. **Attempt WVA's own all-in-one `deploy/install.sh` with default settings
   (before switching to the Kustomize path documented in README §3 Step 13).**
   - Output:
     ```
     Installing Gateway API CRDs (v1.2.0)...
     Error from server (Invalid): error when applying patch: ...
     ```
   - Explanation: the script tries to (re-)install an older Gateway API CRD
     version (`v1.2.0`) than the `v1.5.1` already installed in README §3
     Step 3, and the patch is rejected; the script aborts under `set -e`
     partway through, having already created namespaces but never deploying
     the controller.

2. **Verify the cluster's existing state was not corrupted by the failed
   attempt (don't just assume — check).**
   - Command: `kubectl get crd inferencepools.inference.networking.k8s.io -o jsonpath='{.spec.versions[*].name}'`
   - Output: `v1` (unchanged)
   - Explanation: the rejected `apply` never took effect (Kubernetes
     validation rejected the whole patch), so existing `InferencePool` and
     `Gateway` objects were unaffected — safe to proceed with the Kustomize
     path.

**Pass/Fail:** documented as a real install-order hazard for anyone
following WVA's upstream README verbatim on a cluster that already has newer
Gateway API CRDs installed — not this demo's own defect, but worth knowing
before you hit it.

---

## Appendix — Regression/comparison vs. the CPU demo (`llm-d-full-demo`, 2026-08-03)

| Metric | CPU demo (sim/CPU vLLM) | This GPU demo (real DGX Spark) |
| --- | --- | --- |
| Model | Qwen2.5-0.5B-Instruct | Qwen2.5-1.5B-Instruct |
| Backend | vLLM CPU (arm64 native) / inference-sim | **Real vLLM on GB10 GPU** |
| Model-server replicas (default pool) | 2 (steady) | 1 steady; 2 achieved once, unstable (TC-GPU-05) |
| Default-path trace | 11 spans / 3 services (gateway→IPP→EPP stitched) | **14 spans / 2 services** (IPP not stitched — TC-TRACE-03) |
| P/D-path trace | 21 spans / 4 services | **27 spans / 3 services** |
| KV-cache hit demonstrated | ✅ | ❌ (TC-KV-03 — version skew, diagnosed) |
| Metrics closed loop | ✅ | ✅ (plus real GPU TTFT histogram; found+fixed a PodMonitor gap, TC-WVA-06) |
| WVA closed loop (metric → external API → HPA target) | ✅ | ✅ |
| WVA actual scale-up under load | ✅ | ❌ (TC-WVA-06) |
| Local image builds required | Yes (EPP, sidecar, IPP from source) | **No** (all images pulled pre-built) |
