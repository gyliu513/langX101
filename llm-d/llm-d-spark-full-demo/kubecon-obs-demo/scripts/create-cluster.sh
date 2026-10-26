#!/usr/bin/env bash
# Steps 3-5 of ../../README.md for a second Kind cluster, llm-d-obs, next to
# (not replacing) the full demo's llm-d cluster. Host prerequisites (Steps 1-2:
# kind/kubectl/helm in ~/bin, nvidia runtime as Docker default,
# accept-nvidia-visible-devices-as-volume-mounts) must already be in place.
set -euxo pipefail
export PATH=$HOME/bin:$PATH
FULL=${FULL:-..}
mkdir -p ~/llm-d-cache/huggingface
kind create cluster --config kind-config.yaml
docker exec llm-d-obs-control-plane nvidia-smi --query-gpu=name,driver_version --format=csv
docker exec llm-d-obs-control-plane bash -c '
  apt-get update -qq && apt-get install -y -qq curl gnupg
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -qq && apt-get install -y -qq nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=containerd --config=/etc/containerd/config.toml
  systemctl restart containerd'
kubectl apply -f "$FULL/manifests/00-gpu-runtime.yaml"
# Kind's nested containerd has its own image store: import the 25 GB NGC vLLM
# image from the host instead of letting kubelet pull it again.
docker save nvcr.io/nvidia/vllm:26.08-py3 | docker exec -i llm-d-obs-control-plane ctr -n k8s.io images import -
kubectl get node llm-d-obs-control-plane -o jsonpath='{.status.allocatable}' | tr ',' '\n' | grep gpu
