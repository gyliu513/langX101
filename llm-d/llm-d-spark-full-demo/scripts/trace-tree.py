#!/usr/bin/env python3
"""Print the newest Jaeger trace for a service as an indented span tree.
usage: trace-tree.py [service] [jaeger_url]   (default: llm-d-inference-gateway)"""
import json, sys, urllib.request
svc = sys.argv[1] if len(sys.argv) > 1 else "llm-d-inference-gateway"
base = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:16686"
data = json.load(urllib.request.urlopen(f"{base}/api/traces?service={svc}&limit=1&lookback=2h"))["data"]
if not data:
    sys.exit("no traces")
t = data[0]
procs = t["processes"]
spans = {s["spanID"]: s for s in t["spans"]}
kids = {}
roots = []
for s in t["spans"]:
    refs = [r for r in (s.get("references") or []) if r.get("refType") == "CHILD_OF"]
    if refs and refs[0]["spanID"] in spans:
        kids.setdefault(refs[0]["spanID"], []).append(s)
    else:
        roots.append(s)
def walk(s, d):
    svc = procs[s["processID"]]["serviceName"]
    print(f'{"  "*d}[{svc}] {s["operationName"]}  ({s["duration"]/1000:.1f} ms)')
    for c in sorted(kids.get(s["spanID"], []), key=lambda x: x["startTime"]):
        walk(c, d + 1)
for r in sorted(roots, key=lambda x: x["startTime"]):
    walk(r, 0)
print(f'-- traceID={t["traceID"]} spans={len(t["spans"])} services={len(procs)}')
