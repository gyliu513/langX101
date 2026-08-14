#!/usr/bin/env bash
# Mirror the queue setup onto each worker cluster.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

for cluster in "${WORKERS[@]}"; do
  log "applying queues on ${cluster}"
  # The Kueue webhook may need a few seconds after the pod is Ready.
  for attempt in {1..12}; do
    if kubectl --context "$(ctx "${cluster}")" apply -f "${MANIFESTS_DIR}/worker-queues.yaml"; then
      break
    fi
    warn "webhook not ready yet on ${cluster}, retry ${attempt}/12"
    sleep 5
  done
done

log "worker queues:"
for cluster in "${WORKERS[@]}"; do
  echo "--- ${cluster}"
  kubectl --context "$(ctx "${cluster}")" get clusterqueue,localqueue -A
done
