# Optional / advanced layers

These layers extend the baseline demo with the remaining llm-d "key components."
They are **opt-in** and kept separate from the always-on baseline because they are
designed around real (CPU/GPU) vLLM and accelerator interconnects. On a no-GPU
Kind cluster with `llm-d-inference-sim` they let you deploy the **topology and the
control/observability plane**, but the data-plane KV mechanics are illustrative,
not functional.

> [!IMPORTANT]
> No-GPU caveat. Real KV-cache transfer (P/D) needs vLLM + NIXL over RDMA/TCP, and
> precise prefix-cache routing needs vLLM KV-cache events plus a tokenizer render
> endpoint. The simulator does not perform real KV transfer or tokenization. Use
> these to exercise routing/scheduling/tracing wiring; for a functional run, swap
> in the CPU-vLLM model servers from the referenced llm-d guides.

## 1. Prefill/Decode (P/D) disaggregation — `pd/`

Adds a `prefill` pool and a `decode` pool fronted by the
`llm-d-routing-sidecar` (an initContainer in each decode pod). The EPP runs the
P/D scheduling pipeline (`prefill-filter` / `decode-filter` + two scheduling
profiles), so the router orchestrates a two-phase request across the pools.

- `pd/model-servers-pd.yaml` — sim `prefill` + sim `decode` (with routing-sidecar) + services.
- `pd/pd-router.values.yaml` — EPP P/D plugin config and `modelServers.matchLabels: llm-d.ai/guide=pd-disaggregation`.

This is an **alternative** model-server + router configuration (different
`matchLabels` than the baseline). Run it as a separate router release/namespace,
or replace the baseline model servers. Canonical reference (GPU, fully functional):
`llm-d/guides/pd-disaggregation/` and the routing-sidecar image
`ghcr.io/llm-d/llm-d-routing-sidecar:v0.8.0`.

> Verification status on sim: the sidecar performs a `do_remote_prefill` handshake
> with the prefiller. Whether `llm-d-inference-sim:v0.9.0` completes that handshake
> end-to-end is environment-dependent; if requests stall, use the CPU-vLLM model
> servers from the guide instead.

## 2. Precise prefix-cache routing (KV-cache-aware) — `precise-prefix/`

This is how the llm-d **KV-cache indexer** is exercised: vLLM pods publish
KV-cache events over ZMQ, and the EPP's `precise-prefix-cache-producer` builds a
per-pod block index used by the `prefix-cache-scorer`. (The KV-cache indexer is a
library embedded in the EPP, not a separate Deployment.)

- `precise-prefix/precise-prefix-router.values.yaml` — EPP plugins: `token-producer`,
  `endpoint-notification-source`, `precise-prefix-cache-producer`
  (`kvEventsConfig.discoverPods`, `socketPort: 5556`), plus the scorers.

Functional requirements not satisfiable by the simulator:
- A tokenizer render endpoint (`/v1/completions/render`) for `token-producer`
  (real vLLM `vllm launch render` sidecar) and an `HF_TOKEN` for a gated model.
- vLLM `--kv-events-config '{...,"publisher":"zmq",...}'` publishing real events on `:5556`.

Canonical reference (CPU vLLM, fully functional, needs `HF_TOKEN`):
`llm-d/guides/precise-prefix-cache-routing/` (`modelserver/cpu/vllm`).
