#!/usr/bin/env bash
# Submit the sample JobSet on the hub and watch MultiKueue dispatch it to the worker.
set -euo pipefail
cd "$(dirname "$0")"

NAME=multikueue-demo
echo ">> (re)submitting JobSet '$NAME' to user-queue on the HUB"
kubectl --context kind-hub delete jobset $NAME --ignore-not-found >/dev/null 2>&1 || true
kubectl --context kind-hub apply -f manifests/jobset-demo.yaml
sleep 5

echo
echo ">> HUB: workload admitted, but NO pods run here"
kubectl --context kind-hub get workloads
kubectl --context kind-hub get pods 2>/dev/null || true

echo
echo ">> MANAGED: JobSet mirrored here and pods actually run"
sleep 5
kubectl --context kind-managed get jobset $NAME
kubectl --context kind-managed get pods -o wide -l jobset.sigs.k8s.io/jobset-name=$NAME

echo
echo ">> waiting for completion on the worker..."
kubectl --context kind-managed wait --for=condition=Completed jobset/$NAME --timeout=180s

echo
echo ">> status propagated back to the HUB:"
sleep 8
kubectl --context kind-hub get jobset $NAME -o jsonpath='hub jobset terminalState={.status.terminalState}{"\n"}'
kubectl --context kind-hub get workloads
