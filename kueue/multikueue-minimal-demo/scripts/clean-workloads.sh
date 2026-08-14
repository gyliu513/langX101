#!/usr/bin/env bash
# Remove every demo workload from the manager and both workers, so each example
# starts from an empty queue. Deleting on the manager normally cascades to the
# workers; the worker-side sweep is a safety net.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

mctx="$(ctx "${MANAGER}")"

log "deleting demo workloads on ${MANAGER}"
kubectl --context "${mctx}" -n default delete jobs,jobsets,rayjobs --all --ignore-not-found >/dev/null 2>&1 || true

for cluster in "${WORKERS[@]}"; do
  log "sweeping ${cluster}"
  kubectl --context "$(ctx "${cluster}")" -n default delete jobs,jobsets,rayjobs --all --ignore-not-found >/dev/null 2>&1 || true
done

# Give the controllers a moment to release the quota.
sleep 5
log "queues are empty:"
for cluster in "${WORKERS[@]}"; do
  kubectl --context "$(ctx "${cluster}")" get clusterqueue cluster-queue \
    -o custom-columns="CLUSTER:.metadata.name,PENDING:.status.pendingWorkloads,ADMITTED:.status.admittedWorkloads" --no-headers \
    | sed "s|^cluster-queue|${cluster}|"
done
