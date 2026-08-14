#!/usr/bin/env bash
# Delete all three kind clusters and the generated kubeconfigs.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

for cluster in "${ALL_CLUSTERS[@]}"; do
  if kind get clusters 2>/dev/null | grep -qx "${cluster}"; then
    log "deleting cluster ${cluster}"
    kind delete cluster --name "${cluster}"
  fi
done

rm -rf "${GENERATED_DIR}"
log "torn down"
