#!/usr/bin/env python3
"""Tiny streaming benchmark through Envoy (:8081). Standard library only.

    python3 scripts/bench.py [concurrency ...]     # default: 1 4 8

Per request: client-side TTFT and decode tokens/s from the SSE stream.
Reports p50/p95 TTFT, mean per-request decode tok/s, aggregate output tok/s
and how the requests were split across the two replicas.
"""
import concurrent.futures as cf
import json
import os
import statistics
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = open(os.path.join(ROOT, ".env")).read().split("MODEL=")[1].split()[0]
REPLICAS = {"vllm-0": "http://127.0.0.1:8000", "vllm-1": "http://127.0.0.1:8001"}


def served():
    out = {}
    for n, b in REPLICAS.items():
        text = urllib.request.urlopen(b + "/metrics", timeout=10).read().decode()
        out[n] = sum(float(l.rsplit(" ", 1)[1]) for l in text.splitlines()
                     if l.startswith("vllm:request_success_total{"))
    return out


def one(i, max_tokens=256):
    body = {"model": MODEL, "max_tokens": max_tokens, "temperature": 0.7, "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": f"Write a short story #{i} about a lighthouse keeper."}]}
    req = urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.time(); first = None; toks = 0
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r:
            if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]":
                continue
            j = json.loads(line[6:])
            if j.get("choices") and first is None:
                first = time.time()
            if j.get("usage"):
                toks = j["usage"]["completion_tokens"]
    end = time.time()
    return first - t0, toks / max(end - first, 1e-6), toks


for c in [int(x) for x in sys.argv[1:]] or [1, 4, 8]:
    n = max(c * 2, 4)
    before = served(); t = time.time()
    with cf.ThreadPoolExecutor(c) as ex:
        res = list(ex.map(one, range(n)))
    wall = time.time() - t
    after = served()
    ttft = sorted(r[0] for r in res)
    print(f"concurrency={c:<2} n={n:<3} TTFT p50={statistics.median(ttft)*1000:6.0f} ms "
          f"p95={ttft[int(0.95*(len(ttft)-1))]*1000:6.0f} ms  decode/req={statistics.mean(r[1] for r in res):5.1f} tok/s  "
          f"aggregate={sum(r[2] for r in res)/wall:6.1f} tok/s  split={ {k: round(after[k]-before[k]) for k in after} }",
          flush=True)
