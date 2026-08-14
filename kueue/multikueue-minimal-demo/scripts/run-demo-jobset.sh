#!/usr/bin/env bash
# Example 2 — JobSet.
# One JobSet with 2 replicated Jobs. MultiKueue dispatches the whole JobSet to a
# single worker; the JobSet controller there creates the child Jobs and Pods.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

"${DEMO_ROOT}/scripts/clean-workloads.sh"

log "submitting a JobSet to ${MANAGER}"
kubectl --context "$(ctx "${MANAGER}")" apply -f "${EXAMPLES_DIR}/jobset.yaml"

log "spec.managedBy defaulted by the Kueue webhook on the manager:"
sleep 2
kubectl --context "$(ctx "${MANAGER}")" -n default get jobset demo-jobset \
  -o jsonpath='{.metadata.name}{"  managedBy="}{.spec.managedBy}{"  suspend="}{.spec.suspend}{"\n"}'

log "waiting for MultiKueue to dispatch..."
for _ in {1..40}; do
  target="$(kubectl --context "$(ctx "${MANAGER}")" -n default get workloads \
    -o jsonpath='{.items[0].status.clusterName}' 2>/dev/null || true)"
  [[ -n "${target}" ]] && break
  sleep 5
done
[[ -n "${target:-}" ]] && log "dispatched to ${target}"

exec "${DEMO_ROOT}/scripts/status.sh"
