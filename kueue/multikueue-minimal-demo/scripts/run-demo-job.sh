#!/usr/bin/env bash
# Example 1 — batch/v1 Job.
# Submits 3 Jobs of 2 CPU each against workers that hold 2 CPU of quota, so two
# get dispatched (one per worker) and the third stays pending.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

"${DEMO_ROOT}/scripts/clean-workloads.sh"

log "submitting 3 batch/Jobs to ${MANAGER}"
kubectl --context "$(ctx "${MANAGER}")" apply -f "${EXAMPLES_DIR}/jobs.yaml"

log "waiting for MultiKueue to dispatch..."
for _ in {1..40}; do
  admitted="$(kubectl --context "$(ctx "${MANAGER}")" -n default get workloads \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Admitted")].status}{"\n"}{end}' \
    | grep -c True || true)"
  [[ "${admitted}" -ge 2 ]] && break
  sleep 5
done

exec "${DEMO_ROOT}/scripts/status.sh"
