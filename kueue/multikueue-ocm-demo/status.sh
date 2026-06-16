#!/usr/bin/env bash
# Print MultiKueue/OCM health across both clusters.
set -euo pipefail

echo "================ OCM ================"
kubectl --context kind-hub get managedclusters
echo
echo "managed-serviceaccount addon on cluster1:"
kubectl --context kind-hub get managedclusteraddon -n cluster1 managed-serviceaccount 2>/dev/null || true
echo
echo "================ MultiKueue (hub) ================"
echo -n "MultiKueueCluster cluster1 : "
kubectl --context kind-hub get multikueuecluster cluster1 -o jsonpath='{.status.conditions[?(@.type=="Active")].reason} / {.status.conditions[?(@.type=="Active")].message}'; echo
echo -n "AdmissionCheck sample      : "
kubectl --context kind-hub get admissioncheck sample-multikueue -o jsonpath='{.status.conditions[?(@.type=="Active")].message}'; echo
echo
echo "================ Queues ================"
echo "-- HUB --";     kubectl --context kind-hub     get clusterqueue,localqueue
echo "-- MANAGED --"; kubectl --context kind-managed get clusterqueue,localqueue
echo
echo "================ Workloads ================"
echo "-- HUB --";     kubectl --context kind-hub     get workloads 2>/dev/null || echo "(none)"
echo "-- MANAGED --"; kubectl --context kind-managed get workloads 2>/dev/null || echo "(none)"
