#!/usr/bin/env bash
# Drop the EPP's per-event KV-cache index traces in the in-cluster OTel
# Collector before they reach Jaeger (README §8, finding K2).
#
# With `kvEventsConfig.tracing: true` the EPP starts a new root trace for every
# KV-cache index event: ~87,000 single-span traces per minute on two Qwen2.5-1.5B
# replicas. Jaeger's in-memory store then evicts request traces within about a
# minute. This adds two conditions to the collector's existing filter processor:
#   - every `index_evict` span
#   - every `index_add` span. `IsRootSpan()` did not match the standalone
#     index_add traces in our test (their parent is not in the trace), so all
#     index_add spans are dropped; inside a request trace that loses one small
#     child span and nothing value attribution needs.
#   k8s/scripts/filter-kv-index-traces.sh
set -euo pipefail
NS=${NS:-llm-d}
kubectl -n "$NS" get cm otel-collector-config -o json | python3 -c '
import json, sys
cm = json.load(sys.stdin)
key = next(iter(cm["data"]))
s = cm["data"][key]
anchor = "        - name == \"GET\"\n"
rules = ("        # tokeneconomics: drop per-event KV-cache index traces (finding K2)\n"
         "        - name == \"index_evict\"\n"
         "        - name == \"index_add\"\n")
if "name == \"index_evict\"" not in s:
    if anchor not in s:
        sys.exit("filter/drop-metrics-scraping anchor not found")
    s = s.replace(anchor, anchor + rules, 1)
cm["data"][key] = s
for k in ("resourceVersion", "uid", "creationTimestamp", "managedFields"):
    cm["metadata"].pop(k, None)
cm["metadata"].get("annotations", {}).pop("kubectl.kubernetes.io/last-applied-configuration", None)
json.dump(cm, sys.stdout)
' | kubectl apply -f - >/dev/null
kubectl -n "$NS" rollout restart deploy/otel-collector >/dev/null
kubectl -n "$NS" rollout status deploy/otel-collector --timeout=120s
echo "OTel Collector now drops per-event KV index traces"
