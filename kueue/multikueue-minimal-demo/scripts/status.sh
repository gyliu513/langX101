#!/usr/bin/env bash
# Show where workloads were submitted vs. where they are actually running.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

mctx="$(ctx "${MANAGER}")"

echo
log "MANAGER (${MANAGER}) — submitted here, but nothing executes here"
kubectl --context "${mctx}" -n default get jobs,jobsets,rayjobs 2>/dev/null | grep -v '^$' || true
echo "  pods on the manager (expected: none):"
kubectl --context "${mctx}" -n default get pods --no-headers 2>/dev/null | sed 's/^/  /' || true
[[ -z "$(kubectl --context "${mctx}" -n default get pods --no-headers 2>/dev/null)" ]] && echo "  <none>"

echo
log "MANAGER — Workloads: which worker cluster each one was dispatched to"
kubectl --context "${mctx}" -n default get workloads \
  -o custom-columns='WORKLOAD:.metadata.name,ADMITTED:.status.conditions[?(@.type=="Admitted")].status,DISPATCHED-TO:.status.clusterName,MESSAGE:.status.admissionChecks[0].message' 2>/dev/null || true

for cluster in "${WORKERS[@]}"; do
  echo
  log "WORKER (${cluster}) — the Pods actually run here"
  kubectl --context "$(ctx "${cluster}")" -n default get jobs,jobsets,rayjobs 2>/dev/null | grep -v '^$' || true
  kubectl --context "$(ctx "${cluster}")" -n default get pods 2>/dev/null || true
  kubectl --context "$(ctx "${cluster}")" get clusterqueue cluster-queue \
    -o custom-columns='CLUSTERQUEUE:.metadata.name,PENDING:.status.pendingWorkloads,ADMITTED:.status.admittedWorkloads' 2>/dev/null || true
done
echo
