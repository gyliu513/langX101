#!/usr/bin/env bash
# Jaeger (16686) and OpenCost (9003) on this host, for attribution.build.
set -euo pipefail
pkill -f "svc/jaeger-collector 16686" 2>/dev/null || true
pkill -f "svc/opencost 9003" 2>/dev/null || true
kubectl port-forward -n llm-d svc/jaeger-collector 16686:16686 >/dev/null 2>&1 &
kubectl port-forward -n opencost svc/opencost 9003:9003 >/dev/null 2>&1 &
sleep 2
curl -sf -o /dev/null http://127.0.0.1:16686/ && echo "Jaeger   http://127.0.0.1:16686"
curl -sf -o /dev/null "http://127.0.0.1:9003/allocation/compute?window=10m" && echo "OpenCost http://127.0.0.1:9003"
