#!/usr/bin/env bash
# Apply the queue setup + MultiKueue wiring on the manager cluster.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

context="$(ctx "${MANAGER}")"

log "applying MultiKueue setup on ${MANAGER}"
for attempt in {1..12}; do
  if kubectl --context "${context}" apply -f "${MANIFESTS_DIR}/manager-multikueue.yaml"; then
    break
  fi
  warn "webhook not ready yet on ${MANAGER}, retry ${attempt}/12"
  sleep 5
done

log "waiting for both MultiKueueClusters to report Active"
for _ in {1..30}; do
  ready="$(kubectl --context "${context}" get multikueuecluster \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Active")].status}{"\n"}{end}' \
    | grep -c True || true)"
  [[ "${ready}" == "${#WORKERS[@]}" ]] && break
  sleep 5
done

kubectl --context "${context}" get multikueuecluster \
  -o custom-columns='CLUSTER:.metadata.name,ACTIVE:.status.conditions[?(@.type=="Active")].status,REASON:.status.conditions[?(@.type=="Active")].reason,MESSAGE:.status.conditions[?(@.type=="Active")].message'
echo
kubectl --context "${context}" get admissioncheck multikueue-check \
  -o custom-columns='CHECK:.metadata.name,ACTIVE:.status.conditions[?(@.type=="Active")].status,MESSAGE:.status.conditions[?(@.type=="Active")].message'
