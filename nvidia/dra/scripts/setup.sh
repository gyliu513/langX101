#!/usr/bin/env bash
# One-shot setup: kind cluster + NVIDIA DRA driver + Kueue (with DRA mapping).
# Run on the GPU host (DGX Spark) from the repo's nvidia/dra directory.
set -euo pipefail
cd "$(dirname "$0")/.."

DRA_DRIVER_VERSION=${DRA_DRIVER_VERSION:-0.5.1}
KUEUE_VERSION=${KUEUE_VERSION:-v0.20.6}

echo "==> kind cluster"
kind get clusters | grep -qx dra || kind create cluster --config kind/kind-config.yaml

echo "==> NVIDIA DRA driver ${DRA_DRIVER_VERSION}"
helm upgrade --install dra-driver-nvidia-gpu \
  oci://registry.k8s.io/dra-driver-nvidia/charts/dra-driver-nvidia-gpu \
  --version "${DRA_DRIVER_VERSION}" \
  --namespace dra-driver-nvidia-gpu --create-namespace \
  -f kind/dra-driver-values.yaml
# The DaemonSet reports "rolled out" before its Pod even exists; wait for real.
until kubectl -n dra-driver-nvidia-gpu get pod --no-headers 2>/dev/null | grep -q kubelet-plugin; do sleep 2; done
kubectl -n dra-driver-nvidia-gpu wait --for=condition=Ready pod -l app.kubernetes.io/name=dra-driver-nvidia-gpu --timeout=300s
until kubectl get resourceslice --no-headers 2>/dev/null | grep -q gpu.nvidia.com; do sleep 2; done
kubectl get resourceslice -o wide

echo "==> Kueue ${KUEUE_VERSION}"
curl -sSL -o kueue/manifests.yaml \
  "https://github.com/kubernetes-sigs/kueue/releases/download/${KUEUE_VERSION}/manifests.yaml"
kubectl apply --server-side -f kueue/manifests.yaml >/dev/null
kubectl -n kueue-system rollout status deploy/kueue-controller-manager --timeout=300s
kubectl -n kueue-system create configmap kueue-manager-config \
  --from-file=controller_manager_config.yaml=kueue/controller_manager_config.yaml \
  --dry-run=client -o yaml | kubectl apply --server-side --force-conflicts -f -
kubectl -n kueue-system rollout restart deploy/kueue-controller-manager
kubectl -n kueue-system rollout status deploy/kueue-controller-manager --timeout=300s
# Right after the restart the webhook may not serve yet ("failed calling
# webhook mresourceflavor.kb.io ... context deadline exceeded"): retry.
until kubectl apply -f kueue/10-queues.yaml; do echo "webhook not ready, retrying in 5s"; sleep 5; done
echo "==> done"
