#!/usr/bin/env bash
# Bring the whole non-Kubernetes llm-d stack up on the Spark.
#   scripts/up.sh [model-env-file] [precise|nospec|approx]
#   nospec = precise with speculativeIndexing: false (use for hybrid Mamba models, README §10.1)
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE=${1:-nemotron3-nano-30b.env}
MODE=${2:-precise}
cp "$ENV_FILE" .env                      # compose reads .env automatically
set -a; . ./.env; set +a
export MODEL
envsubst '${MODEL}' < configs/epp/config-precise.tmpl.yaml > configs/epp/config-precise.yaml
sed 's/speculativeIndexing: true/speculativeIndexing: false/' configs/epp/config-precise.yaml > configs/epp/config-precise-nospec.yaml
case "$MODE" in
  precise) export EPP_CONFIG=config-precise.yaml ;;
  nospec)  export EPP_CONFIG=config-precise-nospec.yaml ;;
  approx)  export EPP_CONFIG=config-approx.yaml ;;
  *) echo "mode must be precise|nospec|approx" >&2; exit 1 ;;
esac
echo "EPP_CONFIG=$EPP_CONFIG" >> .env
mkdir -p "$HOME/llm-d-cache/vllm-compile"

docker compose --profile obs up -d
docker compose --profile model up -d          # vllm-1 waits for vllm-0 healthy
echo "waiting for both vLLM replicas (first start compiles; ~5-15 min)..."
for p in 8000 8001; do
  until curl -sf "http://127.0.0.1:$p/v1/models" >/dev/null; do sleep 10; done
  echo "  vLLM :$p ready"
done
docker compose --profile router up -d
until curl -sf http://127.0.0.1:19000/ready >/dev/null; do sleep 2; done
echo "Envoy ready on :8081 (EPP config: $EPP_CONFIG, model: $MODEL)"
