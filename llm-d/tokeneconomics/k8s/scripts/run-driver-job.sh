#!/usr/bin/env bash
# Run one demo phase as a Kubernetes Job and wait for it.
#   k8s/scripts/run-driver-job.sh <phase> <note> [duration-s] [concurrency]
set -euo pipefail
cd "$(dirname "$0")/../.."           # the tokeneconomics folder
export PHASE=${1:?phase} NOTE=${2:?note} DURATION=${3:-300} CONCURRENCY=${4:-12}
export DRIVER_IMAGE=${DRIVER_IMAGE:-python:3.12-slim}
kubectl -n llm-d create configmap tokeneconomics-code \
  --from-file=tokeneconomics/__init__.py --from-file=tokeneconomics/otlp.py \
  --from-file=tokeneconomics/workloads.py --from-file=tokeneconomics/driver.py \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n llm-d delete job "te-driver-$PHASE" --ignore-not-found >/dev/null
envsubst '${PHASE} ${NOTE} ${DURATION} ${CONCURRENCY} ${DRIVER_IMAGE}' < k8s/manifests/driver-job.tmpl.yaml | kubectl apply -f -
kubectl -n llm-d wait --for=condition=complete "job/te-driver-$PHASE" --timeout=$((DURATION + 600))s
kubectl -n llm-d logs "job/te-driver-$PHASE" | tail -3
