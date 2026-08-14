#!/usr/bin/env bash
# Build a kubeconfig for each worker and store it as a Secret on the manager.
#
# THE kind GOTCHA: `kind get kubeconfig` points at https://127.0.0.1:<random-port>,
# which is only reachable from the host. The Kueue pod on the manager needs an
# address reachable from *inside* the docker network. All kind clusters share the
# `kind` bridge network, so we use the worker control-plane container's IP on that
# network. kubeadm puts that IP in the API server serving cert, so TLS still verifies.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

mkdir -p "${GENERATED_DIR}"
chmod 0700 "${GENERATED_DIR}"

for cluster in "${WORKERS[@]}"; do
  context="$(ctx "${cluster}")"

  log "creating MultiKueue ServiceAccount on ${cluster}"
  kubectl --context "${context}" apply -f "${MANIFESTS_DIR}/worker-multikueue-rbac.yaml"

  log "waiting for the ServiceAccount token to be populated on ${cluster}"
  for _ in {1..30}; do
    token="$(kubectl --context "${context}" -n kueue-system get secret multikueue-sa \
      -o jsonpath='{.data.token}' 2>/dev/null || true)"
    [[ -n "${token}" ]] && break
    sleep 2
  done
  if [[ -z "${token}" ]]; then
    warn "token for ${cluster} was never populated"; exit 1
  fi
  token="$(echo "${token}" | base64 -d)"
  ca="$(kubectl --context "${context}" -n kueue-system get secret multikueue-sa \
    -o jsonpath='{.data.ca\.crt}')"

  api_ip="$(docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' "${cluster}-control-plane")"
  if [[ -z "${api_ip}" ]]; then
    warn "could not resolve the docker IP of ${cluster}-control-plane"; exit 1
  fi
  log "${cluster} API server reachable in-network at https://${api_ip}:6443"

  kubeconfig="${GENERATED_DIR}/${cluster}.kubeconfig"
  touch "${kubeconfig}"
  chmod 0600 "${kubeconfig}"
  cat > "${kubeconfig}" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: ${cluster}
    cluster:
      certificate-authority-data: ${ca}
      server: https://${api_ip}:6443
users:
  - name: multikueue-sa
    user:
      token: ${token}
contexts:
  - name: ${cluster}
    context:
      cluster: ${cluster}
      user: multikueue-sa
current-context: ${cluster}
EOF

  log "storing ${cluster} kubeconfig as a Secret on ${MANAGER}"
  kubectl --context "$(ctx "${MANAGER}")" -n kueue-system create secret generic \
    "${cluster}-secret" --from-file=kubeconfig="${kubeconfig}" \
    --dry-run=client -o yaml | kubectl --context "$(ctx "${MANAGER}")" apply -f -
done

log "connection secrets on the manager:"
kubectl --context "$(ctx "${MANAGER}")" -n kueue-system get secret | grep -- '-secret' || true
