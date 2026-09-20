#!/usr/bin/env bash
# Send N identical long prompts (>= 1 KV block of 64 tokens) through the
# Gateway so the precise-prefix path produces KV-cache hits and a visible
# routing decision. Pass `pd` as $2 to target the P/D pool instead.
#   ./scripts/drive-traffic.sh [count] [pd]
set -euo pipefail
N=${1:-6}
POOL=${2:-}
GW=${GW:-http://localhost:8080}
MODEL=${MODEL:-Qwen/Qwen2.5-1.5B-Instruct}
PROMPT="Explain in detail how a distributed key-value cache works in a large language model inference system, covering block-based paging, prefix reuse across requests, eviction policy, event publication over ZeroMQ, and how a router can use those events to steer traffic to the replica that already holds the longest matching prefix. Please be thorough and specific."
HDR=()
[[ "$POOL" == "pd" ]] && HDR=(-H "x-llm-d-pool: pd")
for i in $(seq 1 "$N"); do
  curl -sS -o /dev/null -w "req$i http=%{http_code} time=%{time_total}s\n" \
    -X POST "$GW/v1/chat/completions" -H 'Content-Type: application/json' "${HDR[@]}" \
    -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}],\"max_tokens\":16}"
  sleep 2
done
