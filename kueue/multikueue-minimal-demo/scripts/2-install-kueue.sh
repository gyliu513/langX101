#!/usr/bin/env bash
# Install Kueue on all three clusters and pin its enabled integrations.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

for cluster in "${ALL_CLUSTERS[@]}"; do
  context="$(ctx "${cluster}")"

  log "installing Kueue ${KUEUE_VERSION} on ${cluster}"
  kubectl --context "${context}" apply --server-side -f "${KUEUE_MANIFEST}"

  # Must match the operators installed in step 1 — see manifests/kueue-config.yaml.
  log "pinning enabled integrations on ${cluster}"
  kubectl --context "${context}" apply -f "${MANIFESTS_DIR}/kueue-config.yaml"
  kubectl --context "${context}" -n kueue-system rollout restart deployment/kueue-controller-manager
done

for cluster in "${ALL_CLUSTERS[@]}"; do
  context="$(ctx "${cluster}")"
  log "waiting for kueue-controller-manager on ${cluster}"
  kubectl --context "${context}" -n kueue-system rollout status \
    deployment/kueue-controller-manager --timeout=300s
  wait_for_kueue_webhook "${context}"
done

log "enabled integrations (should list batch/job, jobset and the ray kinds):"
kubectl --context "$(ctx "${MANAGER}")" -n kueue-system get cm kueue-manager-config \
  -o jsonpath='{.data.controller_manager_config\.yaml}' | sed -n '/integrations:/,$p'
