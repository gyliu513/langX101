# NVIDIA's DGX Spark vLLM image (the only vLLM build that runs on GB10 /
# aarch64) ships the NixlConnector code but NOT the `nixl` runtime package, so
# `--kv-transfer-config '{"kv_connector":"NixlConnector"}'` fails at startup.
# This adds the runtime so the P/D-disaggregated pool can do REAL KV transfer
# between the prefill and decode Pods.
#
# Two traps found while building this (both show up as vLLM's model-registry
# subprocess "died with <Signals.SIGSEGV>" -> "Model architectures
# ['Qwen2ForCausalLM'] failed to be inspected"):
#
# 1. `pip install nixl` (the meta package) depends on BOTH nixl-cu12 and
#    nixl-cu13, each bundling its own UCX. Install the `nixl` import shim with
#    --no-deps and only the CUDA-13 wheel.
# 2. The nixl-cu13 wheel also ships `nixl_ep` (expert-parallel comm ops built
#    against upstream torch 2.14). vLLM's MoE layers import it eagerly, and it
#    is ABI-incompatible with NGC's torch 2.14.0a0+nv26.08, so every Python
#    process segfaults at exit. KV transfer only needs `nixl._api`, so delete
#    the nixl_ep packages.
FROM nvcr.io/nvidia/vllm:26.08-py3
RUN pip install --no-cache-dir --no-deps nixl==1.4.1 \
 && pip install --no-cache-dir nixl-cu13==1.4.1 \
 && rm -rf /usr/local/lib/python3.12/dist-packages/nixl_ep \
           /usr/local/lib/python3.12/dist-packages/nixl_ep_cu13 \
 && python3 -c "import vllm.model_executor.models.qwen2" \
 && python3 -c "from nixl._api import nixl_agent, nixl_agent_config; nixl_agent('t', nixl_agent_config(backends=['UCX']))"
