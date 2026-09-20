#!/usr/bin/env bash
# Port-forward the UIs/APIs to localhost (run on the Kind host).
#   Jaeger      http://localhost:16686
#   Prometheus  http://localhost:9091
#   Grafana     http://localhost:3000  (admin / admin)
#   Gateway     http://localhost:8080  (OpenAI-compatible API)
# Use `--bind 0.0.0.0` to reach them from another machine on the LAN.
set -euo pipefail
BIND=${BIND:-127.0.0.1}
pkill -f "kubectl port-forward" 2>/dev/null || true
kubectl port-forward --address "$BIND" -n llm-d svc/jaeger-collector 16686:16686 >/dev/null 2>&1 &
kubectl port-forward --address "$BIND" -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9091:9090 >/dev/null 2>&1 &
kubectl port-forward --address "$BIND" -n llm-d-monitoring svc/llmd-grafana 3000:80 >/dev/null 2>&1 &
kubectl port-forward --address "$BIND" -n llm-d svc/llm-d-inference-gateway 8080:80 >/dev/null 2>&1 &
sleep 2
echo "Jaeger     http://$BIND:16686"
echo "Prometheus http://$BIND:9091"
echo "Grafana    http://$BIND:3000"
echo "Gateway    http://$BIND:8080"
