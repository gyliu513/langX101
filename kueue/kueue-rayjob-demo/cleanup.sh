#!/usr/bin/env bash
# Delete the whole kind cluster (the fastest way to clean everything up).
# To only remove the RayJob run instead, use:
#   kubectl delete -f 02-rayjob.yaml -f 01-ray-code-configmap.yaml
set -euo pipefail

CLUSTER_NAME="kueue-rayjob-demo"

echo "==> Deleting kind cluster '${CLUSTER_NAME}'"
kind delete cluster --name "${CLUSTER_NAME}"
echo "Done."
