#!/usr/bin/env bash
# Delete the whole kind cluster (the fastest way to clean everything up).
# To only remove the training run instead, use:
#   kubectl delete -f 01-pytorch-jobset.yaml
set -euo pipefail

CLUSTER_NAME="kueue-jobset-demo"

echo "==> Deleting kind cluster '${CLUSTER_NAME}'"
kind delete cluster --name "${CLUSTER_NAME}"
echo "Done."
