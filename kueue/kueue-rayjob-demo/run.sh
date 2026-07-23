#!/usr/bin/env bash
# Submit the RayJob, show how Kueue admits it, stream the driver logs from
# the submitter pod, then show the teardown that releases the quota.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAYJOB="rayjob-pi"

echo "==> Submitting the RayJob"
kubectl apply -f "${SCRIPT_DIR}/01-ray-code-configmap.yaml"
kubectl apply -f "${SCRIPT_DIR}/02-rayjob.yaml"

echo
echo "==> Kueue Workload (ADMITTED=True means head+workers quota was reserved together)"
sleep 5
kubectl get workloads -o wide || true
kubectl get rayjob "${RAYJOB}"

echo
echo "==> Waiting for the Ray head pod to become Ready..."
for i in $(seq 1 60); do
  kubectl get pod -l ray.io/node-type=head -o name 2>/dev/null | grep -q . && break
  sleep 2
done
kubectl wait --for=condition=Ready pod -l ray.io/node-type=head --timeout=600s

echo
echo "==> Ray cluster pods (1 head + 2 workers, spread over the kind nodes):"
kubectl get pods -o wide -l "ray.io/is-ray-node=yes"

echo
echo "==> Waiting for the submitter pod (runs 'ray job submit' with our entrypoint)..."
SUBMITTER=""
for i in $(seq 1 90); do
  SUBMITTER="$(kubectl get pods -l "job-name=${RAYJOB}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  [ -n "${SUBMITTER}" ] && break
  sleep 2
done
echo "    submitter pod: ${SUBMITTER:-<not found>}"

echo
echo "==> Streaming driver logs (pi computation + task distribution):"
kubectl wait --for=condition=Ready "pod/${SUBMITTER}" --timeout=300s || true
kubectl logs -f "${SUBMITTER}" || true

echo
echo "==> Waiting for the RayJob to reach a terminal state..."
for i in $(seq 1 90); do
  STATUS="$(kubectl get rayjob "${RAYJOB}" -o jsonpath='{.status.jobDeploymentStatus}' 2>/dev/null || true)"
  case "${STATUS}" in Complete|Failed) break ;; esac
  sleep 2
done
kubectl get rayjob "${RAYJOB}"

echo
echo "==> shutdownAfterJobFinishes tears the RayCluster down (~30s TTL), releasing quota:"
sleep 40
kubectl get raycluster 2>/dev/null || true
kubectl get workloads -o wide || true

echo
echo "Done. Try the queueing experiment in the README (03-rayjob-second.yaml),"
echo "or ./cleanup.sh to tear everything down."
