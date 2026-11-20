#!/usr/bin/env bash
# Kubernetes variant: baseline (weight 3) vs incident (weight 0) as Jobs, then
# build the five datasets with Cost and Usage from OpenCost, and the report.
#   k8s/scripts/run-demo.sh [phase-seconds] [concurrency]
# Needs: kubectl context = the llm-d Kind cluster, and on this host
#   Jaeger on 127.0.0.1:16686 and OpenCost on 127.0.0.1:9003 (scripts/port-forward.sh).
set -euo pipefail
cd "$(dirname "$0")/../.."           # the tokeneconomics folder
DUR=${1:-300}
CONC=${2:-12}
OUT=${OUT:-k8s/data}
HOSTDATA=${HOSTDATA:-$HOME/llm-d-cache/tokeneconomics-k8s}   # = /root/.cache/tokeneconomics-k8s on the Kind node
SETTLE=$(awk -F= '/^window_seconds/ {gsub(/ /,"",$2); print $2}' k8s/demo-k8s.toml)
docker exec llm-d-control-plane rm -rf /root/.cache/tokeneconomics-k8s   # fresh run (files are root-owned)
rm -rf "$OUT"; mkdir -p "$OUT"

# Harvest vLLM leaf spans every 60 s while the phases run: the in-cluster
# Jaeger keeps traces in memory, and the EPP's KV-event tracing (~87k
# single-span traces per minute) evicts request traces within minutes
# (README §8, finding K2). Overlapping windows are de-duplicated by build.
harvester() {
  local since=$(( $(date +%s) - 5 ))
  while true; do
    sleep 60
    local now=$(date +%s)
    python3 -m tokeneconomics.build --data "$OUT" --config k8s/demo-k8s.toml --harvest --window "$((since - 10)),$now" \
      | sed 's/^/[harvester] /'
    since=$now
  done
}
harvester & HARVESTER=$!
trap 'kill $HARVESTER 2>/dev/null' EXIT

k8s/scripts/set-prefix-weight.sh 3
k8s/scripts/run-driver-job.sh baseline "prefix-cache-scorer weight 3" "$DUR" "$CONC"
k8s/scripts/set-prefix-weight.sh 0
k8s/scripts/run-driver-job.sh incident "prefix-cache-scorer weight 0" "$DUR" "$CONC"
sleep 70                     # one more harvest after the last request
kill $HARVESTER 2>/dev/null || true
k8s/scripts/set-prefix-weight.sh 3

echo "waiting ${SETTLE}s for settlement + 120s for OpenCost/Prometheus to cover the last minute..."
sleep $((SETTLE + 120))
cp "$HOSTDATA"/*.jsonl "$OUT"/
python3 -m tokeneconomics.build --data "$OUT" --config k8s/demo-k8s.toml
python3 -m tokeneconomics.report --data "$OUT"
