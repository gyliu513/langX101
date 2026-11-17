#!/usr/bin/env python3
"""Print a Jaeger trace as an indented tree.

    python3 scripts/trace-tree.py <trace-id>     # a specific trace
    python3 scripts/trace-tree.py                # latest trace rooted at llm-d-envoy
"""
import json
import sys
import urllib.request

JAEGER = "http://127.0.0.1:16686"


def get(path):
    with urllib.request.urlopen(JAEGER + path, timeout=10) as r:
        return json.load(r)


if len(sys.argv) > 1:
    trace = get(f"/api/traces/{sys.argv[1]}")["data"][0]
else:
    trace = get("/api/traces?service=llm-d-envoy&limit=1&lookback=1h")["data"][0]

procs = {k: v["serviceName"] for k, v in trace["processes"].items()}
spans = {s["spanID"]: s for s in trace["spans"]}
children, roots = {}, []
for s in trace["spans"]:
    parents = [r["spanID"] for r in s.get("references", []) if r["refType"] == "CHILD_OF" and r["spanID"] in spans]
    (children.setdefault(parents[0], []) if parents else roots).append(s)


def show(s, depth):
    print(f"{'  ' * depth}[{procs[s['processID']]}] {s['operationName']}  ({s['duration'] / 1000:.1f} ms)")
    for c in sorted(children.get(s["spanID"], []), key=lambda x: x["startTime"]):
        show(c, depth + 1)


print(f"trace {trace['traceID']}: {len(spans)} spans, services {sorted(set(procs.values()))}, roots={len(roots)}")
for r in sorted(roots, key=lambda x: x["startTime"]):
    show(r, 0)
