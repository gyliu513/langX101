#!/usr/bin/env bash
# Verify the DGX Spark vLLM GPU endpoint(s) are reachable from wherever this
# runs (Mac host or a pod inside the Kind cluster, if run via kubectl exec).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck disable=SC1091
[ -f "$DEMO_DIR/.env" ] && set -a && source "$DEMO_DIR/.env" && set +a

DGX_HOST="${DGX_HOST:-192.168.1.112}"
DGX_MODEL="${DGX_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"

for port in 8000 8001; do
  echo "== ${DGX_HOST}:${port} =="
  if curl -sS -m 5 -o /dev/null -w "  /health http=%{http_code}\n" "http://${DGX_HOST}:${port}/health" 2>&1; then
    curl -sS -m 5 "http://${DGX_HOST}:${port}/v1/models" | python3 -c "import sys,json;d=json.load(sys.stdin);print('  model:', d['data'][0]['id'])" 2>/dev/null || echo "  (not serving)"
  else
    echo "  unreachable"
  fi
done

echo "== sample completion (port 8000) =="
curl -sS -m 30 -X POST "http://${DGX_HOST}:8000/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${DGX_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}],\"max_tokens\":5}" \
  | python3 -m json.tool
