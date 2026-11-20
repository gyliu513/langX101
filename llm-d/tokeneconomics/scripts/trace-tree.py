#!/usr/bin/env python3
"""Print one demo trace as a tree, with the attributes value attribution uses.

    python3 scripts/trace-tree.py                 # latest agent-driver trace
    python3 scripts/trace-tree.py <trace-id>
"""
import json
import sys
import urllib.request

JAEGER = "http://127.0.0.1:16686"
SHOW = ("focus.", "gen_ai.usage.", "gen_ai.latency.time_in_model", "demo.step", "llm_d.epp.picker",
        "llm_d.kv_cache.prefix_match")


def get(path):
    with urllib.request.urlopen(JAEGER + path, timeout=10) as r:
        return json.load(r)


if len(sys.argv) > 1:
    trace = get(f"/api/traces/{sys.argv[1]}")["data"][0]
else:
    trace = get("/api/traces?service=agent-driver&limit=1&lookback=1h")["data"][0]

procs = {}
for k, v in trace["processes"].items():
    pod = next((t["value"] for t in v.get("tags", []) if t["key"] == "k8s.pod.name"), None)
    procs[k] = f"{v['serviceName']}@{pod}" if pod else v["serviceName"]
spans = {s["spanID"]: s for s in trace["spans"]}
children, roots = {}, []
for s in trace["spans"]:
    parents = [r["spanID"] for r in s.get("references", []) if r["refType"] == "CHILD_OF" and r["spanID"] in spans]
    (children.setdefault(parents[0], []) if parents else roots).append(s)


def show(s, depth):
    print(f"{'  ' * depth}[{procs[s['processID']]}] {s['operationName']}  ({s['duration'] / 1000:.1f} ms)")
    for t in s.get("tags", []):
        if t["key"].startswith(SHOW):
            v = t["value"]
            v = f"{v:.4f}" if isinstance(v, float) else v
            print(f"{'  ' * depth}    {t['key']} = {v}")
    for c in sorted(children.get(s["spanID"], []), key=lambda x: x["startTime"]):
        show(c, depth + 1)


print(f"trace {trace['traceID']}: {len(spans)} spans, services {sorted(set(procs.values()))}, roots={len(roots)}")
for r in sorted(roots, key=lambda x: x["startTime"]):
    show(r, 0)
