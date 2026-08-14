#!/usr/bin/env bash
# Install the job frameworks (JobSet + KubeRay) on ALL three clusters.
#
# Why on the manager too? Kueue only enables an integration if the corresponding
# CRD exists, and MultiKueue needs the manager to hold the "shadow" copy of the
# JobSet/RayJob. Both operators honour spec.managedBy=kueue.x-k8s.io/multikueue,
# so on the manager they see the object and deliberately do nothing — no Pods are
# created there. (This requires JobSet >= v0.6.0 and KubeRay >= v1.3.1.)
#
# Run this BEFORE installing Kueue: Kueue evaluates which integrations to enable
# at startup, so the CRDs must already exist.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

log "adding the kuberay helm repo"
helm repo add kuberay https://ray-project.github.io/kuberay-helm/ >/dev/null
helm repo update kuberay >/dev/null

for cluster in "${ALL_CLUSTERS[@]}"; do
  context="$(ctx "${cluster}")"

  log "installing JobSet ${JOBSET_VERSION} on ${cluster}"
  kubectl --context "${context}" apply --server-side -f "${JOBSET_MANIFEST}"

  log "installing KubeRay ${KUBERAY_VERSION} on ${cluster}"
  helm --kube-context "${context}" upgrade --install kuberay-operator kuberay/kuberay-operator \
    --version "${KUBERAY_VERSION}" \
    --namespace "${KUBERAY_NAMESPACE}" --create-namespace --wait --timeout 5m
done

for cluster in "${ALL_CLUSTERS[@]}"; do
  context="$(ctx "${cluster}")"
  log "waiting for the JobSet controller on ${cluster}"
  kubectl --context "${context}" -n jobset-system rollout status \
    deployment/jobset-controller-manager --timeout=300s
done

log "framework CRDs now available:"
for cluster in "${ALL_CLUSTERS[@]}"; do
  echo "--- ${cluster}"
  kubectl --context "$(ctx "${cluster}")" get crd \
    jobsets.jobset.x-k8s.io rayjobs.ray.io rayclusters.ray.io rayservices.ray.io \
    -o custom-columns='CRD:.metadata.name' --no-headers
done
