#!/usr/bin/env bash
# Submit the PyTorch JobSet, show how Kueue admits it, then stream the
# training logs from the master pod (node_rank 0).
#
# Note: the master's DNS name is the fixed hostname "pytorch-workers-0-0"
# (used by torchrun --master_addr), but the actual Pod object name has a
# random suffix, so we look it up by label rather than hardcoding it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MASTER_SELECTOR="app=pytorch-jobset,batch.kubernetes.io/job-completion-index=0"

echo "==> Submitting the PyTorch JobSet"
kubectl apply -f "${SCRIPT_DIR}/01-pytorch-jobset.yaml"

echo
echo "==> Kueue Workload (ADMITTED=True means its quota was reserved as a gang)"
sleep 5
kubectl get workloads -o wide || true

echo
echo "==> Waiting for the master pod (job-completion-index=0) to be created..."
MASTER=""
for i in $(seq 1 60); do
  MASTER="$(kubectl get pods -l "${MASTER_SELECTOR}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  [ -n "${MASTER}" ] && break
  sleep 2
done
echo "    master pod: ${MASTER:-<not found>}"

echo
echo "==> Pod placement (the two pods should be on different nodes):"
kubectl get pods -l app=pytorch-jobset -o wide

echo
echo "==> Waiting for the trainer container to start (it pip-installs torch first)..."
kubectl wait --for=condition=Ready "pod/${MASTER}" --timeout=300s || true

echo
echo "==> Streaming logs from the master pod (Ctrl-C to stop):"
kubectl logs -f "${MASTER}"
