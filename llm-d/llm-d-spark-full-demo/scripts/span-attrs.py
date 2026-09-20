#!/usr/bin/env python3
"""For the last N gateway traces, print the routing-decision attributes:
pick_endpoints top_endpoints/top_scores, produce_precise_prefix_cache match
counts, llm_d.kv_cache.* lookup results.   usage: span-attrs.py [N]"""
import json, sys, urllib.request
n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
base = "http://localhost:16686"
data = json.load(urllib.request.urlopen(f"{base}/api/traces?service=llm-d-inference-gateway&limit={n}&lookback=2h"))["data"]
want = ("pick_endpoints", "produce_precise_prefix_cache", "llm_d.kv_cache.index", "llm_d.kv_cache.index.add", "llm_d.kv_cache.index.evict")
for t in sorted(data, key=lambda t: min(s["startTime"] for s in t["spans"])):
    print(f"trace {t['traceID'][:16]}")
    for s in sorted(t["spans"], key=lambda s: s["startTime"]):
        if s["operationName"] in want:
            tags = {tg["key"]: tg["value"] for tg in s.get("tags", []) if tg["key"].startswith("llm_d.")}
            short = {k.replace("llm_d.epp.", "").replace("llm_d.kv_cache.", "kv."): v for k, v in tags.items()}
            print(f"  {s['operationName']:30s} {short}")
