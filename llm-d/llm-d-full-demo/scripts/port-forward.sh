#!/usr/bin/env bash
# Keep the demo's port-forwards alive (kubectl port-forward exits on the first
# broken connection, e.g. a Grafana websocket). Run in a terminal and leave it.
#   gateway    http://localhost:8080   (POST /v1/chat/completions)
#   EPP        http://localhost:9090/metrics
#   Prometheus http://localhost:9091
#   Grafana    http://localhost:3000   (admin / admin)
#   Jaeger     http://localhost:16686
set -u
fwd() { while true; do kubectl port-forward "$@" >/dev/null 2>&1; sleep 1; done }
fwd -n llm-d            svc/llm-d-inference-gateway                8080:80     &
fwd -n llm-d            deploy/llm-d-epp                           9090:9090   &
fwd -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus  9091:9090   &
fwd -n llm-d-monitoring svc/llmd-grafana                           3000:80     &
fwd -n llm-d            svc/jaeger-collector                       16686:16686 &
echo "port-forwards running (pid $$). Ctrl-C to stop."
wait
