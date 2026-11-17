#!/usr/bin/env python3
"""End-to-end test for llm-d without Kubernetes on the DGX Spark.

Runs on the Spark itself (everything is on 127.0.0.1). Standard library only.

    python3 scripts/e2e-test.py            # all checks
    python3 scripts/e2e-test.py -k prefix  # only checks whose name contains "prefix"

Each check prints PASS / FAIL / WARN with the evidence it used. The script
never edits the EPP config; the hot-reload and failure checks restore the
endpoints file and the stopped replica before they return.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENVOY = "http://127.0.0.1:8081"
REPLICAS = {"vllm-0": "http://127.0.0.1:8000", "vllm-1": "http://127.0.0.1:8001"}
EPP_METRICS = "http://127.0.0.1:9090/metrics"
ENVOY_ADMIN = "http://127.0.0.1:19000"
JAEGER = "http://127.0.0.1:16686"
PROM = "http://127.0.0.1:9091"
GRAFANA = "http://127.0.0.1:3000"
ENDPOINTS = os.path.join(ROOT, "configs/epp/endpoints.yaml")

RESULTS = []


def env_model():
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            if line.startswith("MODEL="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("no MODEL in .env — run scripts/up.sh first")


MODEL = None


def http(url, body=None, timeout=120, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read().decode()


def report(name, ok, detail, warn=False):
    tag = "PASS" if ok else ("WARN" if warn else "FAIL")
    RESULTS.append((tag, name))
    print(f"[{tag}] {name}: {detail}", flush=True)


def counter(base, metric):
    """Sum a Prometheus counter on one vLLM replica."""
    _, _, text = http(base + "/metrics", timeout=10)
    total = 0.0
    for line in text.splitlines():
        if line.startswith(metric) and not line.startswith("#"):
            name = line.split("{")[0].split(" ")[0]
            if name == metric:
                total += float(line.rsplit(" ", 1)[1])
    return total


def snapshot(metric="vllm:request_success_total"):
    return {n: counter(b, metric) for n, b in REPLICAS.items()}


def delta(before, after):
    return {k: round(after[k] - before[k]) for k in before}


def chat(content, max_tokens=32, headers=None, stream=False):
    body = {"model": MODEL, "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens, "temperature": 0, "stream": stream}
    return http(ENVOY + "/v1/chat/completions", body, headers=headers)


RUN_ID = "%08x" % (int(time.time() * 1000) & 0xFFFFFFFF)  # fresh prefix every run: no cache left over from earlier runs


def context(rules):
    return (f"[manual revision {RUN_ID}] You are a support assistant for the Aurora rail network. Policy manual follows. "
            + " ".join(f"Rule {i}: trains on line {i % 7} must hold for {i % 5 + 1} minutes at junction {i}."
                       for i in range(1, rules)))


# ~2k tokens: below Nemotron-3's forced 4224-token attention block (hybrid Mamba)
SHORT_CONTEXT = context(110)
# ~6.5k tokens: spans at least one full 4224-token block
LONG_CONTEXT = context(360)


# ---------------------------------------------------------------- checks
def check_health():
    for n, b in REPLICAS.items():
        s, _, _ = http(b + "/health", timeout=5)
        report(f"health {n}", s == 200, f"GET /health -> {s}")
    s, _, body = http(ENVOY_ADMIN + "/ready", timeout=5)
    report("health envoy", s == 200 and "LIVE" in body, body.strip())
    _, _, clusters = http(ENVOY_ADMIN + "/clusters", timeout=5)
    flags = [l for l in clusters.splitlines() if l.startswith("ext_proc::") and "health_flags" in l]
    ok = bool(flags) and all(l.endswith("::healthy") for l in flags)
    report("envoy->EPP gRPC health check", ok, "; ".join(flags) or "no ext_proc host")
    _, _, m = http(EPP_METRICS, timeout=5)
    report("EPP /metrics (no auth in file mode)", "llm_d" in m or "inference" in m, f"{len(m.splitlines())} lines")


def check_basic():
    before = snapshot()
    t = time.time()
    s, h, body = chat("In one sentence, what is a DGX Spark?", max_tokens=200)
    dt = time.time() - t
    j = json.loads(body)
    msg = j["choices"][0]["message"]
    text = (msg.get("content") or "") + (msg.get("reasoning_content") or msg.get("reasoning") or "")
    d = delta(before, snapshot())
    report("chat completion via Envoy:8081", s == 200 and text.strip() != "",
           f"{s} in {dt:.2f}s, served by {[k for k, v in d.items() if v]}, usage={j.get('usage')}, text={text[:80]!r}")


def check_stream():
    body = {"model": MODEL, "messages": [{"role": "user", "content": "Count from 1 to 5."}],
            "max_tokens": 64, "stream": True, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(ENVOY + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t = time.time(); first = None; chunks = 0
    with urllib.request.urlopen(req, timeout=120) as r:
        for line in r:
            if line.startswith(b"data: ") and line.strip() != b"data: [DONE]":
                chunks += 1
                first = first or time.time() - t
    report("streaming (SSE) via Envoy", chunks > 1, f"{chunks} chunks, client TTFT {first*1000:.0f} ms")


def check_completions_api():
    s, _, body = http(ENVOY + "/v1/completions", {"model": MODEL, "prompt": "The capital of France is", "max_tokens": 8})
    report("/v1/completions via Envoy", s == 200, json.loads(body)["choices"][0]["text"][:60])


def _prefix_run(name, ctx, n):
    ctx = f"[{name}] " + ctx  # short and long must not share a prefix either
    before = snapshot()
    hb = snapshot("vllm:prefix_cache_hits_total")
    ptoks = None
    for i in range(n):
        _, _, body = chat(ctx + f"\n\nQuestion {i}: how long do trains hold at junction {i + 3}?", max_tokens=16)
        ptoks = json.loads(body)["usage"]["prompt_tokens"]
    d = delta(before, snapshot())
    hits = delta(hb, snapshot("vllm:prefix_cache_hits_total"))
    sticky = max(d.values()) >= n - 1
    hit = sum(hits.values()) > 0
    # Routing must agree with what the engine can actually reuse:
    #   sticky + hits        -> real cache-aware routing            (PASS)
    #   spread + no hits     -> nothing cacheable, load balanced     (PASS)
    #   sticky + no hits     -> affinity with no cache benefit       (WARN, see README §10.1)
    #   spread + hits        -> cacheable prefix not exploited       (WARN)
    verdict = "real cache-aware routing" if sticky and hit else \
        "nothing cacheable, load balanced" if not sticky and not hit else \
        "AFFINITY WITHOUT ANY CACHE BENEFIT" if sticky else "cacheable prefix NOT exploited"
    report(f"prefix-cache routing, {name} prefix (~{ptoks} prompt tokens)", sticky == hit,
           f"{verdict}: requests per replica {d}, vLLM prefix-cache hit tokens {hits}", warn=True)


def check_prefix_affinity(n=8):
    _prefix_run("short", SHORT_CONTEXT, n)
    _prefix_run("long", LONG_CONTEXT, n)


def check_spread(n=16):
    before = snapshot()
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda i: chat(f"Write a haiku about the number {i * 7919}.", max_tokens=48), range(n)))
    d = delta(before, snapshot())
    report("load spread (distinct prompts, 8 concurrent)", all(v > 0 for v in d.values()),
           f"requests per replica {d}")


def epp_metric_lines(pattern):
    _, _, m = http(EPP_METRICS, timeout=5)
    return [l for l in m.splitlines() if re.search(pattern, l) and not l.startswith("#")]


def check_kv_events():
    lines = epp_metric_lines(r"kv_cache_events|kvevents|kv_block_index")
    shown = [l for l in lines if not l.endswith(" 0")][:8]
    recv = sum(float(l.rsplit(" ", 1)[1]) for l in lines if "messages_received" in l)
    report("EPP receives vLLM KV events over ZMQ", recv > 0, "; ".join(shown) or "no kv-event metrics", warn=True)


def write_endpoints_atomic(text):
    tmp = ENDPOINTS + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, ENDPOINTS)


def check_hot_reload():
    orig = open(ENDPOINTS).read()
    only0 = orig.split("  - name: vllm-1")[0]
    try:
        write_endpoints_atomic(only0)
        time.sleep(4)
        before = snapshot()
        for i in range(6):
            chat(f"Name a color #{i}.", max_tokens=8)
        d = delta(before, snapshot())
        report("endpoints.yaml hot reload (remove vllm-1)", d["vllm-1"] == 0 and d["vllm-0"] == 6, f"requests per replica {d}")
    finally:
        write_endpoints_atomic(orig)
        time.sleep(4)
    before = snapshot()
    for i in range(12):
        chat(f"Name an animal #{i * 31}.", max_tokens=8)
    d = delta(before, snapshot())
    report("endpoints.yaml hot reload (restore vllm-1)", d["vllm-1"] > 0, f"requests per replica {d}")


def check_replica_down():
    """Stop vllm-1 WITHOUT editing endpoints.yaml: does the EPP stop routing to it?"""
    subprocess.run(["docker", "stop", "vllm-1"], check=True, capture_output=True)
    try:
        time.sleep(10)
        codes = []
        for i in range(10):
            try:
                s, _, _ = chat(f"Say hi #{i}.", max_tokens=4)
            except urllib.error.HTTPError as e:
                s = e.code
            except Exception as e:  # connection reset etc.
                s = type(e).__name__
            codes.append(s)
        bad = [c for c in codes if c != 200]
        report("replica down, endpoints file unchanged", not bad,
               f"status codes {codes} (non-200 = EPP still picks the dead endpoint)", warn=True)
    finally:
        subprocess.run(["docker", "start", "vllm-1"], check=True, capture_output=True)
        print("  restarting vllm-1 (waits for /health)...", flush=True)
        for _ in range(180):
            try:
                if http(REPLICAS["vllm-1"] + "/health", timeout=3)[0] == 200:
                    break
            except Exception:
                pass
            time.sleep(5)


def jaeger(path):
    return json.loads(http(JAEGER + path, timeout=10)[2])


def _trace(trace_id):
    data = (jaeger(f"/api/traces/{trace_id}").get("data") or [{}])[0]
    procs = {k: v["serviceName"] for k, v in data.get("processes", {}).items()}
    spans = data.get("spans", [])
    ids = {s["spanID"] for s in spans}
    roots = [s for s in spans if not any(r["refType"] == "CHILD_OF" and r["spanID"] in ids
                                         for r in s.get("references", []))]
    return spans, sorted({procs[s["processID"]] for s in spans}), [procs[r["processID"]] + ":" + r["operationName"] for r in roots]


def check_traces():
    # 1) no client trace context: Envoy roots the trace, EPP must hang under Envoy's ext_proc span
    chat("Trace me without a traceparent: what is 3+3?", max_tokens=8, headers={"x-e2e": "notp"})
    time.sleep(8)
    services = jaeger("/api/services")["data"] or []
    report("Jaeger services", {"llm-d-envoy", "llm-d-epp"} <= set(services), str(sorted(services)))
    latest = jaeger("/api/traces?service=llm-d-envoy&limit=1&lookback=5m")["data"][0]["traceID"]
    spans, svc, roots = _trace(latest)
    report("Envoy -> EPP -> vLLM in ONE trace (no client traceparent)",
           len(roots) == 1 and {"llm-d-envoy", "llm-d-epp"} <= set(svc) and any(s.startswith("vllm") for s in svc),
           f"trace {latest}: {len(spans)} spans, services {svc}, roots {roots}")
    print(subprocess.run([sys.executable, os.path.join(ROOT, "scripts/trace-tree.py"), latest],
                         capture_output=True, text=True).stdout, flush=True)
    # 2) client sends its own W3C traceparent
    tp_trace = "4bf92f3577b34da6a3ce929d0e0e%04x" % (int(time.time()) % 65536)
    chat("Trace me: what is 2+2?", max_tokens=8, headers={"traceparent": f"00-{tp_trace}-00f067aa0ba902b7-01"})
    time.sleep(8)
    spans, svc, roots = _trace(tp_trace)
    report("client traceparent: Envoy + EPP + vLLM under the client's trace id, single root",
           len(roots) == 1 and len(svc) >= 3,
           f"{len(spans)} spans, services {svc}, roots {roots} "
           "(2 roots = EPP prefers the client header over Envoy's ext_proc span context)", warn=True)


def check_prometheus():
    r = json.loads(http(PROM + "/api/v1/targets", timeout=10)[2])
    ups = {t["labels"]["job"] + "/" + t["labels"].get("pod", ""): t["health"] for t in r["data"]["activeTargets"]}
    report("Prometheus scrape targets up", all(v == "up" for v in ups.values()), str(ups))
    for q in ["sum by (pod) (vllm:request_success_total)",
              "histogram_quantile(0.5, sum by (le) (rate(vllm:time_to_first_token_seconds_bucket[5m])))",
              "count({job=\"llm-d-epp\", __name__=~\".+\"})",
              "sum by (service_name) (traces_spanmetrics_calls_total)"]:
        res = json.loads(http(PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": q}), timeout=10)[2])["data"]["result"]
        vals = [(x["metric"].get("pod") or x["metric"].get("service_name") or "", x["value"][1][:8]) for x in res]
        report(f"PromQL {q[:60]}", bool(res), str(vals))


def check_grafana():
    r = json.loads(http(GRAFANA + "/api/search?type=dash-db", timeout=10)[2])
    report("Grafana llm-d dashboards provisioned", len(r) >= 5, ", ".join(d["title"] for d in r))


CHECKS = [check_health, check_basic, check_stream, check_completions_api, check_prefix_affinity,
          check_kv_events, check_spread, check_hot_reload, check_replica_down, check_traces,
          check_prometheus, check_grafana]

if __name__ == "__main__":
    import urllib.parse  # noqa: F401  (used in check_prometheus)
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="", help="run only checks whose function name contains this")
    a = ap.parse_args()
    MODEL = env_model()
    print(f"model={MODEL}\n", flush=True)
    for c in CHECKS:
        if a.k in c.__name__:
            try:
                c()
            except Exception as e:
                report(c.__name__, False, f"exception {type(e).__name__}: {e}")
    print()
    for tag in ("PASS", "WARN", "FAIL"):
        print(f"{tag}: {sum(1 for t, _ in RESULTS if t == tag)}")
    sys.exit(1 if any(t == "FAIL" for t, _ in RESULTS) else 0)
