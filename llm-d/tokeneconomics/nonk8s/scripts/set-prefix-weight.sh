#!/usr/bin/env bash
# Re-render the EPP precise-prefix config with a given prefix-cache-scorer
# weight and restart the EPP on it. weight 3 = upstream default (healthy);
# weight 0 = the KubeCon NA 2026 demo's bad config change.
#   nonk8s/scripts/set-prefix-weight.sh 0
set -euo pipefail
W=${1:?usage: set-prefix-weight.sh <weight>}
NONK8S_DIR=${NONK8S_DIR:-$(cd "$(dirname "$0")/../../../llm-d-spark-nonk8s-demo" && pwd)}
cd "$NONK8S_DIR"
set -a; . ./.env; set +a
CFG=config-precise-w$W.yaml
# the weight line directly follows `pluginRef: prefix-cache-scorer`
awk -v w="$W" '{print} /pluginRef: prefix-cache-scorer/ {getline; sub(/weight: [0-9.]+/, "weight: " w); print}' \
  configs/epp/config-precise.yaml > configs/epp/$CFG
grep -A1 "pluginRef: prefix-cache-scorer" configs/epp/$CFG | tail -1
EPP_CONFIG=$CFG docker compose --profile router up -d --force-recreate epp
until curl -sf http://127.0.0.1:9090/metrics >/dev/null; do sleep 1; done
sleep 5   # let the KV-event subscribers re-attach (and replay) before traffic
echo "EPP running with $CFG"
