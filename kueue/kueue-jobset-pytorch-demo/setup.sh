#!/usr/bin/env bash
# Stand up the whole environment:
#   1. a multi-node kind cluster
#   2. JobSet controller
#   3. Kueue controller (JobSet integration is on by default in v0.18+)
#   4. the Kueue quota objects (ClusterQueue / LocalQueue / ResourceFlavor)
#
# Idempotent-ish: re-running creates the cluster only if it is missing.
set -euo pipefail

CLUSTER_NAME="kueue-jobset-demo"
JOBSET_VERSION="v0.12.0"
KUEUE_VERSION="v0.18.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> [1/4] Creating kind cluster '${CLUSTER_NAME}' (1 control-plane + 3 workers)"
if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  echo "    cluster already exists, skipping create"
else
  kind create cluster --config "${SCRIPT_DIR}/kind-cluster.yaml"
fi
kubectl get nodes

echo "==> [2/4] Installing JobSet ${JOBSET_VERSION}"
kubectl apply --server-side -f "https://github.com/kubernetes-sigs/jobset/releases/download/${JOBSET_VERSION}/manifests.yaml"
echo "    waiting for the JobSet controller to be ready..."
kubectl wait --for=condition=Available --timeout=300s \
  -n jobset-system deploy/jobset-controller-manager

echo "==> [3/4] Installing Kueue ${KUEUE_VERSION} (JobSet integration enabled by default)"
kubectl apply --server-side -f "https://github.com/kubernetes-sigs/kueue/releases/download/${KUEUE_VERSION}/manifests.yaml"
echo "    waiting for the Kueue controller to be ready..."
kubectl wait --for=condition=Available --timeout=300s \
  -n kueue-system deploy/kueue-controller-manager
# Kueue's webhooks take a moment to start serving after the deploy is Available.
echo "    giving Kueue webhooks a few seconds to warm up..."
sleep 15

echo "==> [4/4] Creating Kueue quota objects (ResourceFlavor / ClusterQueue / LocalQueue)"
# Retry briefly in case the webhook is not quite ready yet.
for i in 1 2 3 4 5; do
  if kubectl apply -f "${SCRIPT_DIR}/00-kueue-resources.yaml"; then
    break
  fi
  echo "    apply failed (attempt $i), retrying in 5s..."
  sleep 5
done

echo
echo "Setup complete. Cluster state:"
kubectl get clusterqueue,localqueue -A

echo
echo "Next:  ./run.sh        # submit the PyTorch JobSet and stream logs"
echo "       ./cleanup.sh    # tear the cluster down"
