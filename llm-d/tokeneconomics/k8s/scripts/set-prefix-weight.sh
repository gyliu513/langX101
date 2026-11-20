#!/usr/bin/env bash
# Change the EPP prefix-cache-scorer weight in the llm-d-epp ConfigMap and
# roll the EPP, the Kubernetes equivalent of the KubeCon incident's Helm change.
#   k8s/scripts/set-prefix-weight.sh 0
set -euo pipefail
W=${1:?usage: set-prefix-weight.sh <weight>}
NS=${NS:-llm-d}
KEY=${EPP_CONFIG_KEY:-precise-prefix-cache-routing-plugins.yaml}
kubectl -n "$NS" get cm llm-d-epp -o json | python3 -c '
import json, re, sys
w, key = sys.argv[1], sys.argv[2]
cm = json.load(sys.stdin)
cfg = cm["data"][key]
new, n = re.subn(r"(pluginRef: prefix-cache-scorer\s*\n\s*weight:\s*)[0-9.]+", r"\g<1>" + w, cfg)
if n != 1:
    sys.exit("prefix-cache-scorer weight not found exactly once in " + key)
cm["data"][key] = new
for k in ("resourceVersion", "uid", "creationTimestamp", "managedFields"):
    cm["metadata"].pop(k, None)
json.dump(cm, sys.stdout)
' "$W" "$KEY" | kubectl apply -f - >/dev/null
kubectl -n "$NS" get cm llm-d-epp -o jsonpath="{.data.${KEY//./\\.}}" | grep -A1 "pluginRef: prefix-cache-scorer" | tail -1
kubectl -n "$NS" rollout restart deploy/llm-d-epp >/dev/null
kubectl -n "$NS" rollout status deploy/llm-d-epp --timeout=180s
sleep 10   # KV-event subscribers re-attach before traffic
echo "EPP rolled with prefix-cache-scorer weight $W"
