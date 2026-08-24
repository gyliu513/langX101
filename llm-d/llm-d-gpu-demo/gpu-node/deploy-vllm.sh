#!/usr/bin/env bash
# Deploy a real vLLM GPU model server on the DGX Spark node (192.168.1.112).
#
# Idempotent: safe to re-run. Removes any existing container of the same
# name before recreating it.
#
# GPU memory reality check (2026-08-24, live on this node): the GB10's
# unified memory is shared with whatever else is running on the box (in our
# case the user's ComfyUI session, ~34GB). `torch.cuda.mem_get_info()` free
# fluctuates and drops sharply once vLLM reserves its allocator arena -- on
# this node a single small vLLM replica (--gpu-memory-utilization 0.04, i.e.
# ~5.2GB of the 130.667GB total unified pool) took free from ~5.3GB down to
# ~1.1GB. There is currently NOT enough headroom for a second real-GPU
# replica alongside ComfyUI. This script therefore deploys ONE real replica
# (vllm-gpu-0) by default; a second (vllm-gpu-1) can be attempted with
# REPLICA_1=true but is expected to fail to schedule/OOM unless ComfyUI is
# stopped or more memory frees up -- see docs/TEST_PLAN.md TC-GPU-* and the
# README "Known limitations" section.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck disable=SC1091
[ -f "$DEMO_DIR/.env" ] && set -a && source "$DEMO_DIR/.env" && set +a

DGX_HOST="${DGX_HOST:-192.168.1.112}"
DGX_USER="${DGX_USER:-lgy}"
DGX_MODEL="${DGX_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
VLLM_IMAGE="${VLLM_IMAGE:-nvcr.io/nvidia/vllm:26.05-py3}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.04}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-4096}"
REPLICA_1="${REPLICA_1:-false}"

deploy_replica() {
  local name="$1" http_port="$2" zmq_port="$3" gpu_util="$4"
  echo "==> Deploying $name (http:$http_port zmq:$zmq_port util:$gpu_util) on $DGX_HOST"
  # shellcheck disable=SC2087
  ssh "${DGX_USER}@${DGX_HOST}" bash -s <<EOF
set -euo pipefail
docker rm -f ${name} >/dev/null 2>&1 || true
docker run -d --gpus all --ipc=host --name ${name} \\
  -p ${http_port}:${http_port} -p ${zmq_port}:${zmq_port} \\
  -e VLLM_LOGGING_LEVEL=INFO \\
  ${VLLM_IMAGE} \\
  vllm serve ${DGX_MODEL} \\
    --port ${http_port} \\
    --block-size 64 \\
    --gpu-memory-utilization ${gpu_util} \\
    --max-model-len ${MAX_MODEL_LEN} \\
    --enforce-eager \\
    --kv-events-config "{\\"enable_kv_cache_events\\":true,\\"publisher\\":\\"zmq\\",\\"endpoint\\":\\"tcp://*:${zmq_port}\\",\\"topic\\":\\"kv@${name}:${http_port}@${DGX_MODEL}\\"}"
EOF
}

wait_ready() {
  local name="$1"
  echo "==> Waiting for $name to report 'Application startup complete' (or fail)..."
  ssh "${DGX_USER}@${DGX_HOST}" bash -s <<EOF
set -euo pipefail
i=0
until docker logs ${name} 2>&1 | grep -qE "Application startup complete|Traceback|CUDA out of memory|OutOfMemoryError"; do
  i=\$((i+1))
  if [ \$i -ge 60 ]; then echo "TIMEOUT waiting for ${name}"; exit 1; fi
  sleep 5
done
if docker logs ${name} 2>&1 | grep -qE "Traceback|CUDA out of memory|OutOfMemoryError"; then
  echo "FAILED: ${name} did not start cleanly"
  docker logs ${name} 2>&1 | tail -60
  exit 1
fi
echo "${name} is up."
EOF
}

deploy_replica vllm-gpu-0 8000 5556 "$GPU_MEM_UTIL"
wait_ready vllm-gpu-0

if [ "$REPLICA_1" = "true" ]; then
  deploy_replica vllm-gpu-1 8001 5557 "$GPU_MEM_UTIL" || true
  wait_ready vllm-gpu-1 || echo "vllm-gpu-1 did not come up -- expected if VRAM is tight (see header comment). Continuing with 1 replica."
fi

echo "==> Smoke test"
curl -sS -m 10 "http://${DGX_HOST}:8000/v1/models" | python3 -m json.tool
echo "==> Done. vLLM GPU endpoint(s):"
echo "  http://${DGX_HOST}:8000/v1/chat/completions  (model: ${DGX_MODEL})"
[ "$REPLICA_1" = "true" ] && echo "  http://${DGX_HOST}:8001/v1/chat/completions  (if vllm-gpu-1 came up)"
