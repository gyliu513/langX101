#!/usr/bin/env bash
# End-to-end setup + demo run with retries for flaky steps (OCM accept, status sync).
set -euo pipefail

cd "$(dirname "$0")"
DEMO_NS=default

log() { echo "==> $*"; }

wait_accept() {
  local i
  for i in $(seq 1 30); do
    if clusteradm accept --clusters cluster1 --context kind-hub 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  echo "clusteradm accept failed after retries" >&2
  return 1
}

wait_msa_secret() {
  local i token
  for i in $(seq 1 60); do
    token=$(kubectl --context kind-hub get secret -n cluster1 kueue-multikueue \
      -o jsonpath='{.data.token}' 2>/dev/null || true)
    if [[ -n "$token" ]]; then
      return 0
    fi
    sleep 2
  done
  echo "ManagedServiceAccount secret not ready" >&2
  return 1
}

wait_multikueue_connected() {
  local i connected
  for i in $(seq 1 60); do
    connected=$(kubectl --context kind-hub get multikueuecluster cluster1 \
      -o jsonpath='{.status.conditions[?(@.type=="Active")].status}' 2>/dev/null || true)
    if [[ "$connected" == "True" ]]; then
      return 0
    fi
    sleep 2
  done
  echo "MultiKueueCluster not connected" >&2
  kubectl --context kind-hub get multikueuecluster cluster1 -o yaml
  return 1
}

wait_queues_active() {
  local ctx=$1
  local i msg
  for i in $(seq 1 60); do
    msg=$(kubectl --context "$ctx" get clusterqueue cluster-queue \
      -o jsonpath='{.status.conditions[?(@.type=="Active")].message}' 2>/dev/null || true)
    if [[ "$msg" == "Can admit new workloads" ]]; then
      return 0
    fi
    sleep 2
  done
  echo "ClusterQueue not active on $ctx" >&2
  return 1
}

wait_hub_finished() {
  local i finished state
  for i in $(seq 1 60); do
    finished=$(kubectl --context kind-hub get workloads \
      -o jsonpath='{.items[0].status.conditions[?(@.type=="Finished")].status}' 2>/dev/null || true)
    state=$(kubectl --context kind-hub get jobset multikueue-demo \
      -o jsonpath='{.status.terminalState}' 2>/dev/null || true)
    if [[ "$finished" == "True" && "$state" == "Completed" ]]; then
      return 0
    fi
    sleep 2
  done
  echo "Hub workload did not finish" >&2
  kubectl --context kind-hub get workloads
  kubectl --context kind-hub get jobset multikueue-demo -o yaml | grep -A3 terminalState || true
  return 1
}

log "Create kind clusters"
kind create cluster --name hub
kind create cluster --name managed
kubectl --context kind-hub wait --for=condition=Ready nodes --all --timeout=120s
kubectl --context kind-managed wait --for=condition=Ready nodes --all --timeout=120s

log "Init OCM hub"
clusteradm init --context kind-hub --wait

log "Join managed cluster"
kubectl --context kind-hub config view --raw --minify \
  -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > hub-ca.crt
HUB_PORT=$(kubectl --context kind-hub config view --minify \
  -o jsonpath='{.clusters[0].cluster.server}' | sed 's#.*:##')
TOKEN=$(clusteradm get token --context kind-hub | grep -o 'token=[^ ]*' | head -1 | cut -d= -f2)
clusteradm join \
  --hub-token "$TOKEN" \
  --hub-apiserver "https://127.0.0.1:${HUB_PORT}" \
  --ca-file hub-ca.crt \
  --force-internal-endpoint-lookup \
  --cluster-name cluster1 \
  --context kind-managed

log "Accept registration (with retry)"
wait_accept
kubectl --context kind-managed get secret -n open-cluster-management-agent bootstrap-hub-kubeconfig \
  -o jsonpath='{.data.kubeconfig}' | base64 -d | grep 'server: https://hub-control-plane:6443'

log "Install JobSet v0.8.1"
mkdir -p manifests
curl -fsSL -o manifests/jobset-v0.8.1.yaml \
  https://github.com/kubernetes-sigs/jobset/releases/download/v0.8.1/manifests.yaml
for ctx in kind-hub kind-managed; do
  kubectl --context "$ctx" apply --server-side -f manifests/jobset-v0.8.1.yaml
done

log "Install Kueue v0.16.4"
curl -fsSL -o manifests/kueue-v0.16.4.yaml \
  https://github.com/kubernetes-sigs/kueue/releases/download/v0.16.4/manifests.yaml
for ctx in kind-hub kind-managed; do
  kubectl --context "$ctx" apply --server-side -f manifests/kueue-v0.16.4.yaml
  kubectl --context "$ctx" -n kueue-system rollout status deploy/kueue-controller-manager --timeout=180s
done

log "Trim Kueue integrations"
for ctx in kind-hub kind-managed; do
  kubectl --context "$ctx" -n kueue-system create configmap kueue-manager-config \
    --from-file=controller_manager_config.yaml=manifests/kueue-config.yaml \
    --dry-run=client -o yaml | kubectl --context "$ctx" apply -f -
  kubectl --context "$ctx" -n kueue-system rollout restart deploy/kueue-controller-manager
  kubectl --context "$ctx" -n kueue-system rollout status deploy/kueue-controller-manager --timeout=120s
done

log "Install managed-serviceaccount addon"
helm repo add ocm https://open-cluster-management.io/helm-charts 2>/dev/null || true
helm repo update ocm
helm upgrade --install managed-serviceaccount ocm/managed-serviceaccount \
  --version 0.10.0 -n open-cluster-management-addon --create-namespace --kube-context kind-hub
kubectl --context kind-hub wait --for=condition=Available \
  managedclusteraddon/managed-serviceaccount -n cluster1 --timeout=120s

log "Create ManagedServiceAccount + RBAC"
kubectl --context kind-hub apply -f manifests/msa.yaml
wait_msa_secret
kubectl --context kind-managed apply -f manifests/managed-rbac.yaml
kubectl --context kind-managed apply -f manifests/crb.yaml
kubectl --context kind-managed auth can-i create jobsets.jobset.x-k8s.io \
  --as=system:serviceaccount:open-cluster-management-agent-addon:kueue-multikueue
kubectl --context kind-managed auth can-i create workloads.kueue.x-k8s.io \
  --as=system:serviceaccount:open-cluster-management-agent-addon:kueue-multikueue

log "Build MultiKueue kubeconfig secret"
TOKEN=$(kubectl --context kind-hub get secret -n cluster1 kueue-multikueue -o jsonpath='{.data.token}' | base64 -d)
CA=$(kubectl --context kind-hub get secret -n cluster1 kueue-multikueue -o jsonpath='{.data.ca\.crt}')
cat > worker1.kubeconfig <<EOF
apiVersion: v1
kind: Config
clusters:
- name: cluster1
  cluster:
    server: https://managed-control-plane:6443
    certificate-authority-data: ${CA}
contexts:
- name: cluster1
  context: {cluster: cluster1, user: kueue-multikueue}
current-context: cluster1
users:
- name: kueue-multikueue
  user:
    token: ${TOKEN}
EOF
kubectl --context kind-hub create secret generic multikueue1 -n kueue-system \
  --from-file=kubeconfig=worker1.kubeconfig --dry-run=client -o yaml \
  | kubectl --context kind-hub apply -f -

log "Create MultiKueue resources and queues"
kubectl --context kind-hub apply -f manifests/hub-multikueue.yaml
wait_multikueue_connected
kubectl --context kind-managed apply -f manifests/worker-queues.yaml
kubectl --context kind-hub apply -f manifests/hub-queues.yaml
wait_queues_active kind-hub
wait_queues_active kind-managed

log "Submit demo JobSet"
kubectl --context kind-hub delete jobset multikueue-demo --ignore-not-found
kubectl --context kind-hub apply -f manifests/jobset-demo.yaml
sleep 3
[[ "$(kubectl --context kind-hub get pods -n "$DEMO_NS" --no-headers 2>/dev/null | wc -l | tr -d ' ')" == "0" ]]
[[ "$(kubectl --context kind-managed get jobset multikueue-demo --no-headers 2>/dev/null | wc -l | tr -d ' ')" == "1" ]]
kubectl --context kind-managed wait --for=condition=Completed jobset/multikueue-demo --timeout=120s
wait_hub_finished

log "SUCCESS"
./status.sh
