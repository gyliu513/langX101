#!/usr/bin/env bash
# Steps 6-10 of ../../README.md on the llm-d-obs cluster, pinned to llm-d v1.0
# and llm-d-router v1.0.0, without the IPP and the P/D pool (the demo does not
# need them). Run from kubecon-obs-demo/ on the Spark, after
# scripts/create-cluster.sh, with the llm-d repo checked out at v1.0 in
# $LLMD (default ~/llm-d-v1.0).
set -euxo pipefail
export PATH=$HOME/bin:$PATH
LLMD=${LLMD:-$HOME/llm-d-v1.0}
FULL=${FULL:-..}          # the parent llm-d-spark-full-demo folder
kubectl config use-context kind-llm-d-obs

# Step 6: namespace, CRDs, agentgateway, Gateway
kubectl apply -f "$FULL/manifests/01-namespace.yaml"
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.5.0/v1-manifests.yaml
kubectl apply -k "https://github.com/llm-d/llm-d-router/config/crd?ref=v1.0.0"
helm upgrade --install agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds \
  --namespace agentgateway-system --create-namespace --version v1.4.1
helm upgrade --install agentgateway oci://cr.agentgateway.dev/charts/agentgateway \
  --namespace agentgateway-system --create-namespace --version v1.4.1 \
  --set inferenceExtension.enabled=true
kubectl apply -k "$LLMD/guides/recipes/gateway/agentgateway" -n llm-d

# Step 7: tracing first, so the Grafana install below finds Jaeger and wires
# exemplar -> trace links; then the monitoring CRDs for the router chart.
bash "$LLMD/guides/recipes/observability/install-otel-collector-jaeger.sh" -n llm-d
bash "$LLMD/guides/recipes/observability/install-prometheus-grafana.sh" --crds-only

# Step 8: router v1.0.0 with the "before" EPP config (prefix weight 3.0)
kubectl create secret generic llm-d-hf-token -n llm-d --from-literal=HF_TOKEN="" \
  --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install llm-d oci://ghcr.io/llm-d/charts/llm-d-router-gateway --version v1.0.0 \
  -f helm-values/epp-config-before.values.yaml \
  -f helm-values/tracing.values.yaml \
  -f helm-values/router-obs.values.yaml \
  --set provider.name=none \
  --set httpRoute.create=true \
  --set httpRoute.inferenceGatewayName=llm-d-inference-gateway \
  -n llm-d

# Step 9: two real vLLM replicas on the GB10 (3 GiB KV each)
kubectl apply -f manifests/02-model-servers-obs.yaml
kubectl -n llm-d rollout status deploy/precise-prefix-vllm --timeout=900s

# Step 10: gateway root span, Prometheus + Grafana (with exemplar wiring),
# model-server PodMonitor, the TTFT SLO rule
kubectl apply -f "$FULL/manifests/03-gateway-tracing-policy.yaml"
bash "$LLMD/guides/recipes/observability/install-prometheus-grafana.sh"
kubectl apply -k "$LLMD/guides/recipes/modelserver/components/monitoring/" -n llm-d
kubectl apply -f "$LLMD/guides/recipes/observability/alerts/epp-alerting-rules.yaml" -n llm-d
kubectl apply -f manifests/ttft-slo-rule.yaml
kubectl get pods -A | grep -v kube-system
echo STACK_DONE
