#!/usr/bin/env bash
# Create the three single-node kind clusters: one manager, two workers.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

for cluster in "${ALL_CLUSTERS[@]}"; do
  if kind get clusters 2>/dev/null | grep -qx "${cluster}"; then
    log "cluster ${cluster} already exists, reusing"
  else
    log "creating cluster ${cluster}"
    kind create cluster --name "${cluster}" --image "${NODE_IMAGE}" --wait 120s
  fi
done

log "clusters ready:"
kind get clusters
