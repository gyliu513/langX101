#!/usr/bin/env bash
# Stand up the whole environment:
#   1. a multi-node kind cluster
#   2. pre-pull the Ray image and load it into every kind node
#   3. KubeRay operator (via Helm)
#   4. Kueue controller (ray.io integrations are on by default in v0.18+)
#   5. the Kueue quota objects (ClusterQueue / LocalQueue / ResourceFlavor)
#
# Idempotent-ish: re-running creates the cluster only if it is missing.
set -euo pipefail

CLUSTER_NAME="kueue-rayjob-demo"
KUBERAY_CHART_VERSION="1.6.2"
KUEUE_VERSION="v0.18.0"
RAY_IMAGE="rayproject/ray:2.46.0"   # multi-arch (amd64 + arm64)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v helm >/dev/null || { echo "ERROR: helm is required (brew install helm)"; exit 1; }

echo "==> [1/5] Creating kind cluster '${CLUSTER_NAME}' (1 control-plane + 2 workers)"
if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  echo "    cluster already exists, skipping create"
else
  kind create cluster --config "${SCRIPT_DIR}/kind-cluster.yaml"
fi
kubectl get nodes

echo "==> [2/5] Pre-pulling ${RAY_IMAGE} and loading it into the kind worker nodes"
echo "    (the Ray image is big — this one-time step avoids each node pulling it separately)"
docker pull "${RAY_IMAGE}"
# NOTE: we import via ctr manually instead of `kind load docker-image`.
# When Docker uses the containerd image store, `kind load` fails with
# "ctr: content digest ... not found" because its hardcoded --all-platforms
# flag trips over multi-arch attestation manifests. Importing without that
# flag works fine. Control-plane is skipped (tainted, no Ray pods land there).
IMAGE_TAR="$(mktemp -t ray-image).tar"
docker save "${RAY_IMAGE}" -o "${IMAGE_TAR}"
for node in $(kind get nodes --name "${CLUSTER_NAME}" | grep -v control-plane); do
  if docker exec "${node}" crictl inspecti "${RAY_IMAGE}" >/dev/null 2>&1; then
    echo "    ${node}: image already present, skipping"
  else
    echo "    ${node}: importing image..."
    docker exec --privileged -i "${node}" \
      ctr --namespace=k8s.io images import --digests --snapshotter=overlayfs - < "${IMAGE_TAR}"
  fi
done
rm -f "${IMAGE_TAR}"

echo "==> [3/5] Installing the KubeRay operator (chart ${KUBERAY_CHART_VERSION})"
helm repo add kuberay https://ray-project.github.io/kuberay-helm/ >/dev/null 2>&1 || true
helm repo update kuberay >/dev/null
helm upgrade --install kuberay-operator kuberay/kuberay-operator \
  --version "${KUBERAY_CHART_VERSION}" \
  --namespace kuberay-system --create-namespace
echo "    waiting for the KubeRay operator to be ready..."
kubectl wait --for=condition=Available --timeout=300s \
  -n kuberay-system deploy/kuberay-operator

echo "==> [4/5] Installing Kueue ${KUEUE_VERSION} (ray.io/rayjob integration enabled by default)"
kubectl apply --server-side -f "https://github.com/kubernetes-sigs/kueue/releases/download/${KUEUE_VERSION}/manifests.yaml"
echo "    waiting for the Kueue controller to be ready..."
kubectl wait --for=condition=Available --timeout=300s \
  -n kueue-system deploy/kueue-controller-manager
# Kueue's webhooks take a moment to start serving after the deploy is Available.
echo "    giving Kueue webhooks a few seconds to warm up..."
sleep 15

echo "==> [5/5] Creating Kueue quota objects (ResourceFlavor / ClusterQueue / LocalQueue)"
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
echo "Next:  ./run.sh        # submit the RayJob and stream its logs"
echo "       ./cleanup.sh    # tear the cluster down"
