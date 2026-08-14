#!/usr/bin/env bash
# Example 3 — RayJob.
# MultiKueue dispatches the RayJob to one worker; the KubeRay operator there
# creates the RayCluster (head + 1 worker pod) and runs the entrypoint.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

"${DEMO_ROOT}/scripts/clean-workloads.sh"

# The Ray image is ~1GB; pre-loading it avoids the Pods sitting in
# ContainerCreating for minutes on each worker.
if [[ "${SKIP_IMAGE_PRELOAD:-false}" != "true" ]]; then
  log "pre-pulling ${RAY_IMAGE} on the host"
  docker pull --platform "linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')" "${RAY_IMAGE}" >/dev/null

  # `kind load docker-image` re-imports with --all-platforms, which fails for a
  # multi-arch manifest whose other platforms are not in the local store:
  #   ctr: content digest sha256:...: not found
  # `docker save --platform` writes a single-platform archive, which imports cleanly.
  mkdir -p "${GENERATED_DIR}"
  archive="${GENERATED_DIR}/ray-mini.tar"
  [[ -f "${archive}" ]] || docker save --platform "linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')" \
    "${RAY_IMAGE}" -o "${archive}"
  for cluster in "${WORKERS[@]}"; do
    log "loading the Ray image into ${cluster}"
    kind load image-archive "${archive}" --name "${cluster}"
  done
fi

log "submitting a RayJob to ${MANAGER}"
kubectl --context "$(ctx "${MANAGER}")" apply -f "${EXAMPLES_DIR}/rayjob.yaml"

log "spec.managedBy defaulted by the Kueue webhook on the manager:"
sleep 2
kubectl --context "$(ctx "${MANAGER}")" -n default get rayjob demo-rayjob \
  -o jsonpath='{.metadata.name}{"  managedBy="}{.spec.managedBy}{"  suspend="}{.spec.suspend}{"\n"}'

log "waiting for MultiKueue to dispatch..."
for _ in {1..40}; do
  target="$(kubectl --context "$(ctx "${MANAGER}")" -n default get workloads \
    -o jsonpath='{.items[0].status.clusterName}' 2>/dev/null || true)"
  [[ -n "${target}" ]] && break
  sleep 5
done
[[ -n "${target:-}" ]] && log "dispatched to ${target}"

log "watching the RayCluster come up on the worker (Ctrl-C is safe)..."
for _ in {1..12}; do
  pods="$(kubectl --context "$(ctx "${target:-${WORKERS[0]}}")" -n default get pods --no-headers 2>/dev/null || true)"
  [[ -n "${pods}" ]] && { echo "${pods}" | sed 's/^/  /'; break; }
  sleep 5
done

"${DEMO_ROOT}/scripts/status.sh"

log "waiting for the RayJob to finish..."
for _ in {1..60}; do
  jobstatus="$(kubectl --context "$(ctx "${MANAGER}")" -n default get rayjob demo-rayjob \
    -o jsonpath='{.status.jobStatus}' 2>/dev/null || true)"
  [[ "${jobstatus}" == "SUCCEEDED" || "${jobstatus}" == "FAILED" ]] && break
  sleep 5
done

log "final state on the manager (status synced back from the worker):"
kubectl --context "$(ctx "${MANAGER}")" -n default get rayjob demo-rayjob \
  -o custom-columns='NAME:.metadata.name,JOB-STATUS:.status.jobStatus,DEPLOYMENT:.status.jobDeploymentStatus,MANAGED-BY:.spec.managedBy'
kubectl --context "$(ctx "${MANAGER}")" -n default get workloads \
  -o custom-columns='WORKLOAD:.metadata.name,FINISHED:.status.conditions[?(@.type=="Finished")].status,RAN-ON:.status.clusterName'
echo "  pods on the manager (expected: none):"
kubectl --context "$(ctx "${MANAGER}")" -n default get pods 2>&1 | sed 's/^/  /'
