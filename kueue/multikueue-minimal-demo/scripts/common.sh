#!/usr/bin/env bash
# Shared configuration for the MultiKueue demo.

set -o errexit
set -o nounset
set -o pipefail

DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFESTS_DIR="${DEMO_ROOT}/manifests"
EXAMPLES_DIR="${DEMO_ROOT}/examples"
GENERATED_DIR="${DEMO_ROOT}/.generated"

# --- component versions -------------------------------------------------------
# Kueue v0.19.1 pins jobset v0.12.0 and kuberay v1.6.2 in its go.mod, so these
# three versions are known to work together.
KUEUE_VERSION="${KUEUE_VERSION:-v0.19.1}"
KUEUE_MANIFEST="https://github.com/kubernetes-sigs/kueue/releases/download/${KUEUE_VERSION}/manifests.yaml"

JOBSET_VERSION="${JOBSET_VERSION:-v0.12.0}"
JOBSET_MANIFEST="https://github.com/kubernetes-sigs/jobset/releases/download/${JOBSET_VERSION}/manifests.yaml"

KUBERAY_VERSION="${KUBERAY_VERSION:-1.6.2}"
KUBERAY_NAMESPACE="${KUBERAY_NAMESPACE:-kuberay-system}"

# Slim Ray image maintained by the Kueue project for tests. The real
# rayproject/ray image is multiple GB, which is painful to pull into 3 clusters.
RAY_IMAGE="${RAY_IMAGE:-us-central1-docker.pkg.dev/k8s-staging-images/kueue/ray-project-mini:0.0.4}"

# kind v0.31.0 default node image. k8s >= 1.32 enables the JobManagedBy feature
# gate by default, which MultiKueue needs to delegate batch/Jobs.
NODE_IMAGE="${NODE_IMAGE:-kindest/node:v1.35.0@sha256:452d707d4862f52530247495d180205e029056831160e22870e37e3f6c1ac31f}"

# --- clusters -----------------------------------------------------------------
MANAGER="${MANAGER:-mk-manager}"
WORKERS=("${WORKER1:-mk-worker1}" "${WORKER2:-mk-worker2}")
ALL_CLUSTERS=("${MANAGER}" "${WORKERS[@]}")

# kubectl context name kind assigns to a cluster.
ctx() { echo "kind-$1"; }

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

# Wait until the Kueue webhook Service has ready endpoints. Applying a Kueue CR
# before this point fails with "connection refused" / "no endpoints available".
wait_for_kueue_webhook() {
  local context="$1"
  for _ in {1..60}; do
    if [[ -n "$(kubectl --context "${context}" -n kueue-system get endpointslice \
      -l kubernetes.io/service-name=kueue-webhook-service \
      -o jsonpath='{.items[*].endpoints[*].addresses[0]}' 2>/dev/null)" ]]; then
      return 0
    fi
    sleep 2
  done
  warn "kueue webhook endpoints never became ready on ${context}"
  return 1
}
