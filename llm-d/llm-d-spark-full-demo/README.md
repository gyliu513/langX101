# llm-d Full Stack on Kind — Running Natively on a DGX Spark GPU

This demo takes the complete llm-d stack from
[`../llm-d-full-demo`](../llm-d-full-demo) (agentgateway → IPP → EPP with
precise KV-cache-aware routing → model servers, plus a P/D-disaggregated
pool, OTel/Jaeger tracing and Prometheus/Grafana metrics) and runs **all of
it on one NVIDIA DGX Spark**, with **Kind running on the GPU host** and
**vLLM running as ordinary Kubernetes Pods on the real GB10 GPU** — no CPU
vLLM, no socat bridge to a remote box, no simulator on the main path.

Everything below was executed on **2026-09-20** against a fresh DGX Spark
(`spark-3bee`, Ubuntu 24.04.5, GB10 Grace-Blackwell, aarch64, 121 GiB
unified memory). Every `console` block is copied from the actual session,
including the failures — three of them cost real time and are the most
useful parts of this document.

中文版见 [`README-zh.md`](README-zh.md)。

---

## 0. What you get at the end

| Component | Where it runs | Real or simulated |
| --- | --- | --- |
| Kind cluster (`llm-d`, K8s v1.37.0) | On the DGX Spark, one node container | real |
| `nvidia.com/gpu` as a schedulable resource (×4 time-sliced) | NVIDIA device plugin inside Kind | real |
| 2 × vLLM 0.27.1 replicas, `Qwen2.5-1.5B-Instruct`, publishing KV-cache events | GPU Pods in Kind | **real GPU** |
| agentgateway (Gateway API + Inference Extension) | Kind | real |
| Inference Payload Processor (IPP), built from `main` | Kind | real, in the trace |
| EPP with `precise-prefix-cache-producer` (KV-event-driven routing) | Kind | real, **KV-cache hits reproduced** |
| P/D EPP + routing sidecar (2 scheduling profiles, prefill→decode legs) | Kind | real scheduling, **simulated KV transfer** (see §7) |
| OTel Collector → Jaeger; agentgateway, EPP, sidecar **and vLLM itself** emit spans | Kind | real |
| kube-prometheus-stack, 7 llm-d Grafana dashboards | Kind | real |

The request path and the trace it produces:

```text
                                       default route ──────────────▶ InferencePool llm-d (EPP: precise-prefix)
                                       │                                   ├──▶ vLLM replica 1 (GPU) ┐ KV events
 client ─HTTP─▶ agentgateway ─ext_proc─▶ IPP  ──▶ (route) ──┤                                  └──▶ vLLM replica 2 (GPU) ┘ ZMQ :5556 ─▶ EPP
               (trace ROOT)            (PreRouting)         │
                                                            └── x-llm-d-pool: pd ──▶ InferencePool llm-d-pd (EPP: P/D)
                                                                                           │
                                                                             routing-sidecar ──prefill──▶ pd-prefill (sim)
                                                                             (in pd-decode)  ──decode───▶ pd-decode  (sim)

 spans   ─── OTLP gRPC :4317 ──▶ otel-collector ──▶ Jaeger
 metrics ─── ServiceMonitor (EPPs) + PodMonitor (model servers) ──▶ Prometheus ──▶ Grafana
```

```console
$ python3 scripts/trace-tree.py        # one /v1/chat/completions, 18 spans, 4 services
[llm-d-inference-gateway] POST /*  (284.2 ms)
  [inference.llm-d.ai/inference-payload-processor] gateway.request
    [llm-d-router/epp] request
      [llm-d-router/epp] request_orchestration
        [llm-d-router/epp] tokenize
          [llm-d-router/epp] tokenize_render /v1/chat/completions/render
        [llm-d-router/epp] produce_precise_prefix_cache
          [llm-d-router/epp] match_block_keys
            [llm-d-router/epp] index_walk
        [llm-d-router/epp] run_scheduler_profile
          [llm-d-router/epp] filter_endpoints
          [llm-d-router/epp] scoring
            [llm-d-router/epp] scorer.kv-cache-utilization-scorer
            [llm-d-router/epp] scorer.queue-scorer
            [llm-d-router/epp] scorer.prefix-cache-scorer
          [llm-d-router/epp] pick_endpoints
        [llm-d-router/epp] index_add
      [vllm-precise-prefix] llm_request               # <- real vLLM's own span
```

## 1. How this differs from `llm-d-full-demo`

| | `llm-d-full-demo` (Mac) | this demo (DGX Spark) |
| --- | --- | --- |
| Kind host | Docker Desktop on Apple Silicon | Ubuntu + Docker on the GPU box |
| Model servers | `vllm/vllm-openai-cpu:v0.19.1`, `Qwen2.5-0.5B` | `nvcr.io/nvidia/vllm:26.08-py3` (vLLM 0.27.1) on the GB10, `Qwen2.5-1.5B` |
| GPU | none | `nvidia.com/gpu` via `RuntimeClass/nvidia` + NVIDIA device plugin (time-sliced ×4) |
| Tokenizer for the EPP | `vllm-render` sidecar in the EPP Pod (4 CPU / 8 Gi) | a Service fronting the model servers' own `/render` endpoint (current upstream shape) |
| KV-cache hit routing (`top_scores=[7,4]`) | reproduced | **reproduced on real vLLM KV events** (did not reproduce on the previous DGX Spark attempt) |
| vLLM in the trace | never (sim exports nothing) | **yes** — `vllm-precise-prefix` service, `llm_request` span |
| P/D pool | `llm-d-inference-sim` (CPU vLLM has no NIXL) | `llm-d-inference-sim` (NIXL cannot initialize on GB10 — §7) |
| Images built locally | 3 (EPP, sidecar, IPP for arm64) | **1** — the IPP from `main` (its `v0.1.0` release predates trace-context propagation); EPP and sidecar are published multi-arch |
| TTFT p50 | seconds (CPU) | **31 ms** |

## 2. Versions used

| Component | Version |
| --- | --- |
| DGX Spark | Ubuntu 24.04.5 LTS, kernel `6.17.0-1032-nvidia`, NVIDIA GB10, driver **580.173.02** (CUDA 13.0) |
| docker-ce / nvidia-container-toolkit (host) | 29.2.1 / 1.20.0 |
| kind / kubectl / helm / yq | v0.33.0 / v1.37.0 / v3.22.0 / v4.53.6 |
| Kind node image | `kindest/node:v1.37.0` (Debian 13, containerd 2.3.4), nvidia-container-toolkit **1.20.1** inside |
| NVIDIA k8s-device-plugin | `nvcr.io/nvidia/k8s-device-plugin:v0.20.0` |
| Gateway API / GAIE CRDs | v1.5.1 / v1.5.0 (llm-d `install-gateway-crds.sh` defaults) |
| agentgateway | v1.4.1 (the version llm-d's CI pins) |
| llm-d router chart | `oci://ghcr.io/llm-d/charts/llm-d-router-gateway` `v0`; EPP `ghcr.io/llm-d/llm-d-router-endpoint-picker:main` |
| IPP | chart `payload-processor-0.2.0`, image built from `main` @ `77418c1` (2026-09-17) as `…:main-local` — see Step 11 |
| routing sidecar / inference-sim | `llm-d-router-disagg-sidecar:v0.10.0` / `llm-d-inference-sim:v0.11.0` |
| vLLM | `nvcr.io/nvidia/vllm:26.08-py3` = vLLM `0.27.1+93523f72.dev`, torch `2.14.0a0+nv26.08`, CUDA 13.4 (digest `sha256:4b16878d…`) |
| kube-prometheus-stack | 91.4.1 (operator v0.94.0) |
| llm-d repo | `main` @ `7921182b` (2026-09-18) |

## 3. Prerequisites

| Requirement | Why | Check |
| --- | --- | --- |
| Linux host with an NVIDIA GPU + driver | Kind's node-container GPU trick does not exist on Docker Desktop (no GPU passthrough into its VM) | `nvidia-smi` |
| `nvidia-container-toolkit` on the host | provides `nvidia-ctk` and `nvidia-container-runtime` | `dpkg -l \| grep nvidia-container-toolkit` |
| user in the `docker` group | everything below runs without `sudo` | `docker ps` |
| `sudo` for **four one-time** commands | docker group, `/etc/docker/daemon.json`, `/etc/nvidia-container-runtime/config.toml`, `systemctl restart docker` | — |
| ~40 GB of disk for images + models | `nvcr.io/nvidia/vllm:26.08-py3` alone is 25.5 GB | `df -h /` |
| Enough **free unified memory** | see the ComfyUI note right below | `torch.cuda.mem_get_info()` |

Host as found:

```console
$ uname -a
Linux spark-3bee 6.17.0-1032-nvidia #32-Ubuntu SMP PREEMPT_DYNAMIC Wed Aug 19 17:40:46 UTC 2026 aarch64 GNU/Linux
$ nvidia-smi --query-gpu=name,driver_version --format=csv
name, driver_version
NVIDIA GB10, 580.173.02
$ dpkg -l | grep -E "nvidia-container-toolkit |docker-ce " | awk '{print $2, $3}'
docker-ce 5:29.2.1-1~ubuntu.24.04~noble
nvidia-container-toolkit 1.20.0-1
$ free -h
               total        used        free      shared  buff/cache   available
Mem:           121Gi        94Gi       6.7Gi       100Mi        22Gi        27Gi
```

> ### ⚠️ GB10 has unified memory: `free -h` is not your GPU budget
>
> This box was running ComfyUI, which held **42.5 GB** of GPU memory. What
> CUDA actually saw as free was much less than `free -h` suggested:
> ```console
> $ docker run --rm --gpus all --entrypoint python3 nvcr.io/nvidia/vllm:26.08-py3 -c \
>   'import torch; f,t=torch.cuda.mem_get_info(); print(round(f/1e9,1), round(t/1e9,1))'
> 1.9 130.7          # <- 1.9 GB free out of a 130.7 GB unified pool
> ```
> Not enough for even one vLLM. ComfyUI has a `/free` API that unloads its
> cached models without killing it:
> ```console
> $ curl -sS -X POST http://127.0.0.1:8188/free -H 'Content-Type: application/json' \
>   -d '{"unload_models":true,"free_memory":true}' -w 'http=%{http_code}\n'
> http=200
> $ nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
> 601168, /home/gyliu/ComfyUI/.venv/bin/python, 1927 MiB      # was 42503 MiB
> $ # mem_get_info() now: 86.0 130.7
> ```
> Always size GPU work on this machine from `mem_get_info()`, never from
> `free -h` or `nvidia-smi` (whose memory query returns `Not Supported` on GB10).

---

## 4. Install — step by step

All commands run **on the DGX Spark** in `~/llm-d-spark-full-demo` (this
folder, `rsync`ed over) with the llm-d repo cloned to `~/llm-d`:

```console
$ git clone https://github.com/llm-d/llm-d.git ~/llm-d       # main @ 7921182b
```

### Step 1 — kind, kubectl, helm, yq (no sudo)

```console
$ mkdir -p ~/bin && cd ~/bin
$ curl -sSL -o kind https://kind.sigs.k8s.io/dl/v0.33.0/kind-linux-arm64 && chmod +x kind
$ curl -sSL -o kubectl https://dl.k8s.io/release/v1.37.0/bin/linux/arm64/kubectl && chmod +x kubectl
$ curl -sSL https://get.helm.sh/helm-v3.22.0-linux-arm64.tar.gz | tar xz --strip-components=1 -C ~/bin linux-arm64/helm
$ curl -sSL -o yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_arm64 && chmod +x yq
$ echo 'export PATH=$HOME/bin:$PATH' >> ~/.bashrc && export PATH=$HOME/bin:$PATH
$ kind version; kubectl version --client | head -1; helm version --short
kind v0.33.0 go1.26.7 linux/arm64
Client Version: v1.37.0
v3.22.0+g144ca65
```

> Helm **4.x** is the current `latest`; this demo pins Helm 3 (`v3.22.0`),
> which is what llm-d's install scripts are tested with.

### Step 2 — Configure Docker for GPU passthrough (root, once)

```console
$ sudo usermod -aG docker $USER
$ sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
$ sudo sed -i 's/#accept-nvidia-visible-devices-as-volume-mounts = false/accept-nvidia-visible-devices-as-volume-mounts = true/' /etc/nvidia-container-runtime/config.toml
$ sudo systemctl restart docker
$ cat /etc/docker/daemon.json
{
    "default-runtime": "nvidia",
    "runtimes": { "nvidia": { "args": [], "path": "nvidia-container-runtime" } }
}
$ grep '^accept-nvidia-visible-devices-as-volume-mounts' /etc/nvidia-container-runtime/config.toml
accept-nvidia-visible-devices-as-volume-mounts = true
```

What each line does:

- `nvidia-ctk runtime configure --set-as-default` registers the `nvidia`
  runtime in Docker **and makes it the default**. `nvidia-container-runtime`
  is a thin `runc` wrapper: it injects `/dev/nvidia*` and driver libraries
  only when a container asks for GPUs; otherwise it behaves like `runc`.
- `accept-nvidia-visible-devices-as-volume-mounts = true` is the trick that
  makes Kind work at all. **Kind has no `--gpus` flag.** With this on, the
  runtime treats a bind mount whose *destination* is
  `/var/run/nvidia-container-devices/<id>` exactly like
  `NVIDIA_VISIBLE_DEVICES=<id>` — and Kind *does* support arbitrary
  `extraMounts`.
- `systemctl restart docker` stops every running container that has no
  restart policy. This host had none (`pgrep -c containerd-shim` → 0), so
  it was safe; check before you do it on a shared box.

### Step 3 — Create the Kind cluster with the GPU mount

[`kind/kind-config.yaml`](kind/kind-config.yaml):

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: llm-d
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: KubeletConfiguration
    maxPods: 250
    evictionHard:
      memory.available: "512Mi"
  extraMounts:
  - hostPath: /dev/null                                   # source is irrelevant
    containerPath: /var/run/nvidia-container-devices/all  # destination = "NVIDIA_VISIBLE_DEVICES=all"
  - hostPath: /home/gyliu/llm-d-cache                     # persistent HF model cache
    containerPath: /root/.cache
```

```console
$ mkdir -p ~/llm-d-cache/huggingface
$ kind create cluster --config kind/kind-config.yaml
Creating cluster "llm-d" ...
 ✓ Ensuring node image (kindest/node:v1.37.0) 🖼
 ✓ Preparing nodes 📦
 ✓ Writing configuration 📜
 ✓ Starting control-plane 🕹️
 ✓ Installing CNI 🔌
 ✓ Installing StorageClass 💾
Set kubectl context to "kind-llm-d"
real	1m27.206s
$ kubectl get nodes -o wide
NAME                  STATUS   ROLES           AGE   VERSION   OS-IMAGE                       KERNEL-VERSION               CONTAINER-RUNTIME
llm-d-control-plane   Ready    control-plane   35s   v1.37.0   Debian GNU/Linux 13 (trixie)   6.17.0-1032-nvidia (arm64)   containerd://2.3.4
```

Verify the GPU reached the **node container** (this is Docker's doing, not
Kubernetes' yet):

```console
$ docker exec llm-d-control-plane ls /dev | grep -i nvidia
nvidia-caps  nvidia-fs0 … nvidia-fs15  nvidia-modeset  nvidia-uvm  nvidia-uvm-tools  nvidia0  nvidiactl
$ docker exec llm-d-control-plane nvidia-smi --query-gpu=name,driver_version --format=csv
name, driver_version
NVIDIA GB10, 580.173.02
```

### Step 4 — Give the *nested* containerd GPU support

Pods are not started by the host's Docker. They are started by the
containerd **inside** the node container, and the stock `kindest/node`
image has no NVIDIA tooling. Install it there and register an `nvidia`
runtime handler (deliberately *not* as the default — only Pods that opt in
via `runtimeClassName: nvidia` get GPU injection):

```console
$ docker exec llm-d-control-plane bash -c '
  apt-get update -qq && apt-get install -y -qq curl gnupg
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -qq && apt-get install -y -qq nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=containerd --config=/etc/containerd/config.toml
  systemctl restart containerd'
Setting up nvidia-container-toolkit (1.20.1-1) ...
INFO Using CRI runtime plugin name "io.containerd.grpc.v1.cri"
INFO Wrote updated config to /etc/containerd/conf.d/99-nvidia.toml
$ docker exec llm-d-control-plane grep -A3 'runtimes.nvidia\]' /etc/containerd/conf.d/99-nvidia.toml
        [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia]
          base_runtime_spec = "/etc/containerd/cri-base.json"
          runtime_type = "io.containerd.runc.v2"
$ kubectl get nodes
NAME                  STATUS   ROLES           AGE   VERSION
llm-d-control-plane   Ready    control-plane   35s   v1.37.0      # stayed Ready through the containerd restart
```

> containerd 2.x reads drop-ins from `/etc/containerd/conf.d/*.toml`, so
> `nvidia-ctk` did not touch `config.toml` itself.

### Step 5 — RuntimeClass, device plugin (time-sliced ×4), smoke test

[`manifests/00-gpu-runtime.yaml`](manifests/00-gpu-runtime.yaml) has three
objects:

- `RuntimeClass/nvidia` → `handler: nvidia` (the containerd handler above).
- `ConfigMap/nvidia-device-plugin-config` with **time-slicing**:
  ```yaml
  sharing:
    timeSlicing:
      resources:
      - name: nvidia.com/gpu
        replicas: 4
  ```
  There is one physical GPU, but this demo runs several vLLM Pods on it (2
  precise-prefix replicas + P/D prefill + decode). With `replicas: 4` the
  plugin advertises `nvidia.com/gpu: 4`, so each Pod can request
  `nvidia.com/gpu: 1` and the scheduler does real accounting. There is no
  memory isolation between slices — each vLLM sizes its own KV budget.
- `DaemonSet/nvidia-device-plugin-daemonset` (`v0.20.0`, `--config-file`,
  runs under `runtimeClassName: nvidia` itself).

```console
$ kubectl apply -f manifests/00-gpu-runtime.yaml
$ kubectl -n kube-system logs -l name=nvidia-device-plugin-ds --tail 4
W0920 14:27:50 devices.go:77] Ignoring error getting device memory: Not Supported
I0920 14:27:50 server.go:198] Starting GRPC server for 'nvidia.com/gpu'
I0920 14:27:50 server.go:142] Starting to serve 'nvidia.com/gpu' on /var/lib/kubelet/device-plugins/nvidia-gpu.sock
I0920 14:27:50 server.go:149] Registered device plugin for 'nvidia.com/gpu' with Kubelet
$ kubectl get node llm-d-control-plane -o jsonpath='{.status.allocatable}' | tr ',' '\n' | grep gpu
"nvidia.com/gpu":"4"
```

> `Ignoring error getting device memory: Not Supported` is the GB10
> unified-memory quirk (NVML cannot report a VRAM total). Device-plugin
> versions **< v0.17.4** treat it as fatal
> ([NVIDIA/k8s-device-plugin#1482](https://github.com/NVIDIA/k8s-device-plugin/issues/1482)).

> First attempt at this step registered **`nvidia.com/gpu: 0`** with the log
> `open /config/config.yaml: no such file or directory` — the ConfigMap was
> mounted as a volume but the `volumeMounts` entry was missing. Worth a
> glance if you copy the DaemonSet by hand.

Prove the whole chain (host Docker → node → nested containerd → Pod) with a
Pod that asks for `nvidia.com/gpu: 1` and runs `nvidia-smi`:

```console
$ kubectl apply -f manifests/gpu-smoke-test.yaml
$ kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/gpu-smoke-test --timeout=180s
$ kubectl logs gpu-smoke-test | head -9
Sun Sep 20 14:27:02 2026
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.173.02             Driver Version: 580.173.02     CUDA Version: 13.0     |
|   0  NVIDIA GB10                    On  |   0000000F:01:00.0 Off |                  N/A |
| N/A   45C    P0             10W /  N/A  | Not Supported          |      0%      Default |
$ kubectl delete pod gpu-smoke-test
```

### Step 6 — Namespace, CRDs, agentgateway, Gateway

```console
$ kubectl apply -f manifests/01-namespace.yaml          # Namespace llm-d + ServiceAccount sa
$ kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml
$ kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.5.0/v1-manifests.yaml
$ kubectl apply -k "https://github.com/llm-d/llm-d-router/config/crd?ref=main"
customresourcedefinition.apiextensions.k8s.io/inferencemodelrewrites.llm-d.ai created
customresourcedefinition.apiextensions.k8s.io/inferenceobjectives.llm-d.ai created
customresourcedefinition.apiextensions.k8s.io/inferencepools.inference.networking.k8s.io configured
$ helm upgrade --install agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds \
    --namespace agentgateway-system --create-namespace --version v1.4.1
$ helm upgrade --install agentgateway oci://cr.agentgateway.dev/charts/agentgateway \
    --namespace agentgateway-system --create-namespace --version v1.4.1 \
    --set inferenceExtension.enabled=true
$ kubectl get gatewayclass agentgateway
NAME           CONTROLLER                      ACCEPTED   AGE
agentgateway   agentgateway.dev/agentgateway   True       1s
$ kubectl apply -k ~/llm-d/guides/recipes/gateway/agentgateway -n llm-d
gateway.gateway.networking.k8s.io/llm-d-inference-gateway created
$ kubectl get gateway -n llm-d
NAME                      CLASS          ADDRESS   PROGRAMMED   AGE
llm-d-inference-gateway   agentgateway             True         15s
```

The three CRD sets are: **Gateway API** (`GatewayClass`, `Gateway`,
`HTTPRoute`), **GAIE** (`InferencePool` — "a set of model-server replicas
for one model"), and **llm-d's own** (`InferenceObjective`,
`InferenceModelRewrite`). `--set inferenceExtension.enabled=true` is what
makes agentgateway treat an `InferencePool` backend as "ask this EPP which
Pod" instead of "load-balance a Service".

> llm-d's docs still show agentgateway `v1.1.0`; its CI script
> (`.github/scripts/install-agentgateway-crds.sh`) pins **v1.4.1**, which is
> what this demo uses. The chart's `latest` is 1.5.0.

### Step 7 — OTel Collector + Jaeger, Prometheus operator CRDs

```console
$ bash ~/llm-d/guides/recipes/observability/install-otel-collector-jaeger.sh -n llm-d
[OK]    OTel Collector + Jaeger deployed successfully.
[INFO]  Components should export OTLP traces to: http://otel-collector:4317
$ bash ~/llm-d/guides/recipes/observability/install-prometheus-grafana.sh --crds-only
✅ Monitoring CRDs installed.
```

The CRDs must exist before Step 8: the router chart renders a
`ServiceMonitor`.

### Step 8 — Router (EPP + InferencePool + HTTPRoute)

```console
$ kubectl create secret generic llm-d-hf-token -n llm-d --from-literal=HF_TOKEN="" \
    --dry-run=client -o yaml | kubectl apply -f -        # public model; the chart still references it
$ helm install llm-d oci://ghcr.io/llm-d/charts/llm-d-router-gateway --version v0 \
    -f helm-values/router-precise-prefix.values.yaml \
    -f helm-values/tracing.values.yaml \
    -f helm-values/router-spark.values.yaml \
    --set provider.name=none \
    --set httpRoute.create=true \
    --set httpRoute.inferenceGatewayName=llm-d-inference-gateway \
    -n llm-d
NAME: llm-d
STATUS: deployed
$ kubectl get httproute,inferencepool,servicemonitor -n llm-d
NAME                                        HOSTNAMES   AGE
httproute.gateway.networking.k8s.io/llm-d               5s
NAME                                              AGE
inferencepool.inference.networking.k8s.io/llm-d   5s
NAME                                                     AGE
servicemonitor.monitoring.coreos.com/llm-d-epp-monitor   5s
$ kubectl get pods -n llm-d
NAME                                       READY   STATUS    RESTARTS   AGE
jaeger-554cff9d46-b4m7x                    1/1     Running   0          6m42s
llm-d-epp-6bc4b9596-vz7ld                  1/1     Running   0          5s      # 1/1: no tokenizer sidecar
llm-d-inference-gateway-58b9564597-xgk6j   1/1     Running   0          7m3s
otel-collector-b6fd97bfb-gcsbj             1/1     Running   0          6m42s
```

The three values files:

- [`router-precise-prefix.values.yaml`](helm-values/router-precise-prefix.values.yaml)
  — the EPP plugin chain (§8.3 explains every plugin). Ported from llm-d
  `guides/precise-prefix-cache-routing/router/` as of 2026-09-18, which
  changed since the full demo: `blockSize` → **`blockSizeTokens`**, a new
  `replaySocketPort: 5559`, and the tokenizer is no longer a sidecar.
- [`router-spark.values.yaml`](helm-values/router-spark.values.yaml) — the
  published `llm-d-router-endpoint-picker:main` image (multi-arch, nothing
  to build), `tokenizer.enabled: false`, `modelServers.matchLabels`
  (`llm-d.ai/guide: precise-prefix-cache-routing` — **the only link between
  the EPP and the vLLM Pods**), and `monitoring.prometheus.enabled: true`.
- [`tracing.values.yaml`](helm-values/tracing.values.yaml) — EPP span export
  to `otel-collector:4317`, 100 % sampling.

### Step 9 — Two real vLLM GPU replicas

**(a) Get the image.** The upstream `docker.io/vllm/vllm-openai` image has no
GB10/aarch64 build; NVIDIA's DGX Spark playbook image is the one that works.
Kind's nested containerd has its **own image store**, so pull once on the
host and import into the node rather than letting kubelet pull 25 GB again:

```console
$ docker pull nvcr.io/nvidia/vllm:26.08-py3                 # 26.08 is the newest tag; 25.5 GB
$ docker save nvcr.io/nvidia/vllm:26.08-py3 | docker exec -i llm-d-control-plane ctr -n k8s.io images import -
Importing	elapsed: 238.7s
$ docker exec llm-d-control-plane ctr -n k8s.io images ls -q | grep vllm
nvcr.io/nvidia/vllm:26.08-py3
```

**(b) Pre-seed the model cache** into the host dir that `kind-config.yaml`
mounts at the node's `/root/.cache`, which the Pods mount as `HF_HOME`:

```console
$ docker run --rm -e HF_HOME=/hf -v ~/llm-d-cache/huggingface:/hf \
    --entrypoint hf nvcr.io/nvidia/vllm:26.08-py3 download Qwen/Qwen2.5-1.5B-Instruct
Fetching 10 files: 100%|██████████| 10/10 [00:41<00:00,  4.12s/it]
✓ Downloaded
$ du -sh ~/llm-d-cache/huggingface
2.9G	/home/gyliu/llm-d-cache/huggingface
```

**(c) Deploy** [`manifests/02-model-servers.yaml`](manifests/02-model-servers.yaml)
— a Deployment with 2 replicas plus the `precise-prefix-cache-routing-render`
Service. The parts that matter:

```yaml
spec:
  template:
    metadata:
      labels:
        llm-d.ai/role: decode
        llm-d.ai/guide: precise-prefix-cache-routing      # <- InferencePool selector
    spec:
      runtimeClassName: nvidia                            # <- GPU injection opt-in
      containers:
        - name: modelserver
          image: nvcr.io/nvidia/vllm:26.08-py3
          # NO `command:` -- keep the image ENTRYPOINT (see incident 3)
          args:
            - "vllm"
            - "serve"
            - "Qwen/Qwen2.5-1.5B-Instruct"
            - "--port=8000"
            - "--block-size=64"                           # == blockSizeTokens in the EPP config
            - "--max-model-len=8192"
            - "--enforce-eager"
            - "--kv-cache-memory-bytes=6442450944"        # incident 1
            - "--gpu-memory-utilization=0.10"             # incident 2
            - "--kv-events-config"
            - '{"enable_kv_cache_events":true,"publisher":"zmq","endpoint":"tcp://*:5556","replay_endpoint":"tcp://*:5559","topic":"kv@$(POD_IP):8000@Qwen/Qwen2.5-1.5B-Instruct"}'
            - "--otlp-traces-endpoint=http://otel-collector:4317"
            - "--collect-detailed-traces=all"
          env:
            - { name: OTEL_SERVICE_NAME, value: vllm-precise-prefix }
            - { name: HF_HOME, value: /root/.cache/huggingface }
            - { name: HF_HUB_OFFLINE, value: "1" }
          resources:
            limits: { cpu: "4", memory: 16Gi, nvidia.com/gpu: 1 }   # <- one of the 4 slices
```

```console
$ kubectl apply -f manifests/02-model-servers.yaml
$ kubectl -n llm-d rollout status deploy/precise-prefix-vllm --timeout=540s
deployment "precise-prefix-vllm" successfully rolled out
$ kubectl get pods -n llm-d -l llm-d.ai/guide=precise-prefix-cache-routing -o wide
NAME                                   READY   STATUS    RESTARTS   AGE   IP            NODE
precise-prefix-vllm-5858978586-56jrs   1/1     Running   0          81s   10.244.0.23   llm-d-control-plane
precise-prefix-vllm-5858978586-8lh29   1/1     Running   0          81s   10.244.0.24   llm-d-control-plane
$ kubectl -n llm-d logs deploy/precise-prefix-vllm | grep -E 'Forward Compat|Using CUDA|KV cache size|startup complete'
NOTE: CUDA Forward Compatibility mode ENABLED.
  Using CUDA 13.4 driver version 615.65.02 with kernel driver version 580.173.02.
(EngineCore pid=354) INFO [kv_cache_utils.py:2235] GPU KV cache size: 224,640 tokens
(APIServer pid=1) INFO:     Application startup complete.
$ nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
1527324, VLLM::EngineCore, 10468 MiB
1527352, VLLM::EngineCore, 10468 MiB
```

That clean rollout took **three attempts**. Each failure is a GB10/NGC
specific trap:

> ### ⚠️ Incident 1 — `Error in memory profiling` (unified memory)
>
> The first version used the usual `--gpu-memory-utilization=0.08` and both
> replicas crash-looped:
> ```text
> AssertionError: Error in memory profiling. Initial free memory 98.0 GiB, current free
> memory 100.59 GiB. This happens when other processes sharing the same container release
> GPU memory while vLLM is profiling during initialization.
> ```
> vLLM sizes the KV cache by running a profiling forward pass and asserting
> that free memory did not *grow* meanwhile. On GB10 "free GPU memory" is
> free *system* memory — page cache and a second Pod starting next door move
> it in both directions, so the assert fires. **Fix:**
> `--kv-cache-memory-bytes=6442450944` (6 GiB) sets the KV budget explicitly
> and, per `gpu_worker.py`, *skips memory profiling entirely*. 6 GiB =
> 224,640 tokens for this model (28 layers × 2 × 2 KV heads × 128 × bf16 =
> 28 KiB/token).

> ### ⚠️ Incident 2 — `Free memory on device ... is less than desired GPU memory utilization`
>
> With only `--kv-cache-memory-bytes`, the *other* startup check fired:
> ```text
> ValueError: Free memory on device cuda:0 (104.5/121.69 GiB) on startup is less than
> desired GPU memory utilization (0.92, 111.95 GiB).
> ```
> The default utilization of 0.92 is checked against free memory before
> anything else. **Fix:** keep a small `--gpu-memory-utilization=0.10` next
> to the explicit KV budget. The two flags play different roles here: 0.10 ×
> 121 GiB = 12 GiB satisfies the pre-check, the 6 GiB budget is what is
> actually allocated.

> ### ⚠️ Incident 3 — `the provided PTX was compiled with an unsupported toolchain`
>
> The next attempt died in `kernel_warmup → flashinfer_autotune → _dummy_run`:
> ```text
> torch.AcceleratorError: CUDA error: the provided PTX was compiled with an unsupported toolchain.
> Search for `cudaErrorUnsupportedPtxVersion' ...
> ```
> The image is built with CUDA **13.4**; the host driver 580 supports CUDA
> **13.0**. The same command worked on the host with plain `docker run`, and
> bisecting every flag and cgroup limit changed nothing — until
> `--entrypoint=""` reproduced it on the host too. The NGC ENTRYPOINT
> (`/opt/nvidia/nvidia_entrypoint.sh`) sources scripts that **prepend
> `/usr/local/cuda/compat/lib.real` to `LD_LIBRARY_PATH`**, enabling *CUDA
> Forward Compatibility* (user-mode driver 615.65 on kernel driver 580):
> ```console
> $ diff <(docker run --rm --gpus all --entrypoint env IMG | sort) <(docker run --rm --gpus all IMG env | sort)
> > _CUDA_COMPAT_STATUS=CUDA Driver OK
> > LD_LIBRARY_PATH=/usr/local/cuda/compat/lib.real:/opt/ffmpeg-safe/lib:...
> > NOTE: CUDA Forward Compatibility mode ENABLED.
> >   Using CUDA 13.4 driver version 615.65.02 with kernel driver version 580.173.02.
> ```
> My Pod spec had `command: ["vllm", "serve"]`, which **replaces the
> ENTRYPOINT** — so the Pod ran with the 580 user-mode driver and its CUDA
> 13.0 JIT could not compile FlashInfer's 13.4 PTX. **Fix:** no `command:`;
> put `vllm serve …` in `args:` (which only replaces `CMD`). This applies to
> every NGC image you run on a Spark whose driver is older than the image's
> CUDA.

### Step 10 — Gateway tracing, Prometheus + Grafana, model-server PodMonitors

```console
$ kubectl apply -f manifests/03-gateway-tracing-policy.yaml     # agentgateway -> otel-collector, root span
$ kubectl get agentgatewaypolicy -n llm-d
NAME              ACCEPTED   ATTACHED   AGE
gateway-tracing   True       True       20s
$ bash ~/llm-d/guides/recipes/observability/install-prometheus-grafana.sh
✅ 🎉 Prometheus and Grafana installation complete.
$ kubectl apply -k ~/llm-d/guides/recipes/modelserver/components/monitoring/ -n llm-d      # PodMonitor decode
$ kubectl get pods -n llm-d-monitoring
NAME                                                     READY   STATUS    RESTARTS   AGE
alertmanager-llmd-kube-prometheus-stack-alertmanager-0   2/2     Running   0          21m
llmd-grafana-65dd87fbc5-cr9fx                            3/3     Running   0          22m
llmd-kube-prometheus-stack-operator-d59cb896d-bjvrg      1/1     Running   0          22m
llmd-kube-state-metrics-687cbc6f8-kvxdb                  1/1     Running   0          22m
llmd-prometheus-node-exporter-gm5x9                      1/1     Running   0          22m
prometheus-llmd-kube-prometheus-stack-prometheus-0       2/2     Running   0          21m
```

### Step 11 — Inference Payload Processor (IPP)

Build it from `main` (native arm64 build, ~5 min) and import it into the
node — the reason is in the callout below:

```console
$ git clone https://github.com/llm-d/llm-d-inference-payload-processor.git ~/llm-d-inference-payload-processor
$ cd ~/llm-d-inference-payload-processor && git log -1 --format='%h %cd' --date=short
77418c1 2026-09-17
$ docker build -t ghcr.io/llm-d/llm-d-inference-payload-processor:main-local -f Dockerfile .
$ docker save ghcr.io/llm-d/llm-d-inference-payload-processor:main-local | docker exec -i llm-d-control-plane ctr -n k8s.io images import -
$ cd ~/llm-d-spark-full-demo
$ helm install ipp ~/llm-d-inference-payload-processor/config/charts/payload-processor \
    -n llm-d -f helm-values/ipp.values.yaml
$ kubectl apply -f manifests/04-ipp-extproc-policy.yaml         # PreRouting ext_proc on the Gateway
$ kubectl get agentgatewaypolicy -n llm-d
NAME              ACCEPTED   ATTACHED   AGE
gateway-tracing   True       True       56m
ipp-extproc       True       True       5s
```

[`ipp.values.yaml`](helm-values/ipp.values.yaml) sets the `main-local`
image, tracing to the collector, and **`flags.secure-serving: false`** —
mandatory with agentgateway (its ext_proc speaks plaintext h2; the IPP
defaults to self-signed TLS, and a broken ext_proc fails *all* traffic
closed).

> ### ⚠️ Why not the published `v0.1.0` image
>
> The first pass used the chart's default `…:v0.1.0` (multi-arch, pullable).
> The IPP worked — its log showed `parsed field from body: field=model` and
> `updated base model header` for every request — but its `gateway.request`
> span always landed in a **separate trace** with its own trace ID, and the
> EPP hung directly under the gateway. `phase: PostRouting` behaved the same.
> That looked like an agentgateway regression (the 2026-08-03 full-demo run
> on v1.1.0 stitched it) until checking the IPP history:
> ```console
> $ git log -1 --format='v0.1.0 = %h %cd' --date=short v0.1.0
> v0.1.0 = bce1a1d 2026-07-12
> $ git merge-base --is-ancestor c719723 v0.1.0 || echo 'v0.1.0 lacks #159'
> v0.1.0 lacks #159      # "extract upstream traceparent, re-parent server span, inject on egress"
> $ git merge-base --is-ancestor 161bfcd v0.1.0 || echo 'v0.1.0 lacks #312'
> v0.1.0 lacks #312      # "export root spans without client traceparent on ext_proc"
> ```
> `v0.1.0` is from **before** the IPP learned to read the `traceparent` at
> all; the August run only stitched because it used an image built from
> `main`. With `main-local` the very next request produced the 4-service
> trace in §5.2 — so agentgateway v1.4.1 does pass trace context to the
> `PreRouting` ext_proc, and the fix is simply a newer IPP build. Worth an
> upstream ask for a release that includes #159.

### Step 12 — The P/D-disaggregated pool

A second router release with its own EPP plugin config, plus a prefill and
a decode Deployment. The chart now renders the header-matched `HTTPRoute`
itself (`httpRoute.headerMatches`), so no hand-written route is needed:

```console
$ helm install llm-d-pd oci://ghcr.io/llm-d/charts/llm-d-router-gateway --version v0 \
    -f helm-values/router-pd.values.yaml \
    -f helm-values/tracing.values.yaml \
    -f helm-values/router-pd-spark.values.yaml \
    --set provider.name=none -n llm-d
$ kubectl apply -f manifests/05-model-servers-pd.yaml
$ kubectl apply -k ~/llm-d/guides/recipes/modelserver/components/monitoring-pd/ -n llm-d   # PodMonitor prefill
$ kubectl get httproute,inferencepool -n llm-d
NAME                                           HOSTNAMES   AGE
httproute.gateway.networking.k8s.io/llm-d                  58m
httproute.gateway.networking.k8s.io/llm-d-pd               11s
NAME                                                 AGE
inferencepool.inference.networking.k8s.io/llm-d      58m
inferencepool.inference.networking.k8s.io/llm-d-pd   11s
$ kubectl get httproute llm-d-pd -n llm-d -o jsonpath='{.spec.rules[0].matches}'
[{"headers":[{"name":"x-llm-d-pool","type":"Exact","value":"pd"}],"path":{"type":"PathPrefix","value":"/"}}]
```

> ### ⚠️ Upstream drift: `plugin type 'disagg-headers-handler' is not registered`
>
> The P/D plugin config from `llm-d-full-demo` (2026-08-28) crash-loops the
> EPP built from today's `main`:
> ```text
> "Failed to parse configuration" ... plugin type 'disagg-headers-handler' is not registered
> ```
> `disagg-headers-handler` is gone and `disagg-profile-handler` only takes
> `deciders:` now. [`router-pd.values.yaml`](helm-values/router-pd.values.yaml)
> follows `guides/pd-disaggregation/router/pd-disaggregation.values.yaml` on
> `main`. After a `helm upgrade` you still need
> `kubectl rollout restart deploy/llm-d-pd-epp` — the Pod has no
> config-checksum annotation.

The model servers behind the P/D pool are `llm-d-inference-sim`, not vLLM.
That was not the plan; §7 records what happened when it was vLLM.

### Final state

```console
$ kubectl get pods -A | grep -vE 'kube-system|local-path'
NAMESPACE             NAME                                                     READY   STATUS
agentgateway-system   agentgateway-7958c8487b-l4hbl                            1/1     Running
llm-d                 jaeger-554cff9d46-b4m7x                                  1/1     Running
llm-d                 llm-d-epp-6bc4b9596-vz7ld                                1/1     Running
llm-d                 llm-d-inference-gateway-58b9564597-xgk6j                 1/1     Running
llm-d                 llm-d-pd-epp-7cbdcb844d-96fbk                            1/1     Running
llm-d                 otel-collector-b6fd97bfb-gcsbj                           1/1     Running
llm-d                 payload-processor-6475bc45fd-7pjjj                       1/1     Running
llm-d                 pd-decode-5fbc985d56-vc5ns                               2/2     Running
llm-d                 pd-prefill-6d5db57479-p5nhd                              1/1     Running
llm-d                 precise-prefix-vllm-5cfc7bc57-httgq                      1/1     Running
llm-d                 precise-prefix-vllm-5cfc7bc57-tkgb5                      1/1     Running
llm-d-monitoring      alertmanager-llmd-kube-prometheus-stack-alertmanager-0   2/2     Running
llm-d-monitoring      llmd-grafana-db8946c97-jw8hz                             3/3     Running
llm-d-monitoring      llmd-kube-prometheus-stack-operator-d59cb896d-bjvrg      1/1     Running
llm-d-monitoring      llmd-kube-state-metrics-687cbc6f8-kvxdb                  1/1     Running
llm-d-monitoring      llmd-prometheus-node-exporter-gm5x9                      1/1     Running
llm-d-monitoring      prometheus-llmd-kube-prometheus-stack-prometheus-0       2/2     Running
$ kubectl -n kube-system get pods -l name=nvidia-device-plugin-ds
nvidia-device-plugin-daemonset-2j7dk   1/1     Running

$ helm list -A
NAME                NAMESPACE             CHART                          APP VERSION
agentgateway        agentgateway-system   agentgateway-v1.4.1            v1.4.1
agentgateway-crds   agentgateway-system   agentgateway-crds-v1.4.1       v1.4.1
ipp                 llm-d                 payload-processor-0.2.0        0.2.0
llm-d               llm-d                 llm-d-router-gateway-v0        v0
llm-d-pd            llm-d                 llm-d-router-gateway-v0        v0
llmd                llm-d-monitoring      kube-prometheus-stack-91.4.1   v0.94.0

$ kubectl describe node llm-d-control-plane | sed -n '/Allocated resources/,/Events/p' | grep -E 'cpu|memory|nvidia'
  cpu                7200m (36%)    18 (90%)
  memory             19306Mi (15%)  48724Mi (39%)
  nvidia.com/gpu     2              2                 # the two real vLLM Pods
```

---

## 5. Test — end to end

`scripts/port-forward.sh` exposes Jaeger (:16686), Prometheus (:9091),
Grafana (:3000) and the Gateway (:8080) on localhost.

### 5.1 One request through the Gateway

```console
$ ./scripts/port-forward.sh
$ curl -sS -X POST http://localhost:8080/v1/chat/completions -H 'Content-Type: application/json' \
    -d '{"model":"Qwen/Qwen2.5-1.5B-Instruct","messages":[{"role":"user","content":"Say hi in exactly three words."}],"max_tokens":20}'
{"id":"chatcmpl-16d7a6bc-1a18-4c2b-8720-d04883851fc0","object":"chat.completion","model":"Qwen/Qwen2.5-1.5B-Instruct",
 "choices":[{"index":0,"message":{"role":"assistant","content":"Hello there!"},"finish_reason":"stop"}],
 "system_fingerprint":"vllm-0.27.1+93523f72.dev-2f315c48",
 "usage":{"prompt_tokens":36,"total_tokens":40,"completion_tokens":4}}
```

The EPP is subscribed to both replicas' KV-event sockets **directly by Pod
IP** — there is no proxy in between:

```console
$ kubectl -n llm-d logs deploy/llm-d-epp | grep 'Connected subscriber'
{"logger":"zmq-subscriber","body":"Connected subscriber socket","endpoint":"tcp://10.244.0.24:5556"}
{"logger":"zmq-subscriber","body":"Connected subscriber socket","endpoint":"tcp://10.244.0.23:5556"}
```

### 5.2 The stitched trace (gateway → IPP → EPP → vLLM)

```console
$ curl -s http://localhost:16686/api/services | python3 -c "import sys,json;print(sorted(json.load(sys.stdin)['data']))"
['inference.llm-d.ai/inference-payload-processor', 'llm-d-inference-gateway', 'llm-d-router/epp', 'llm-d-routing-sidecar', 'vllm-precise-prefix']
$ python3 scripts/trace-tree.py
[llm-d-inference-gateway] POST /*  (284.2 ms)
  [inference.llm-d.ai/inference-payload-processor] gateway.request  (283.8 ms)
    [llm-d-router/epp] request  (282.3 ms)
      [llm-d-router/epp] request_orchestration  (2.6 ms)
        [llm-d-router/epp] tokenize  (2.3 ms)
          [llm-d-router/epp] tokenize_render /v1/chat/completions/render  (2.3 ms)
        [llm-d-router/epp] produce_precise_prefix_cache  (0.1 ms)
          [llm-d-router/epp] match_block_keys  (0.0 ms)
            [llm-d-router/epp] index_walk  (0.0 ms)
        [llm-d-router/epp] run_scheduler_profile  (0.1 ms)
          [llm-d-router/epp] filter_endpoints  (0.0 ms)
          [llm-d-router/epp] scoring  (0.0 ms)
            [llm-d-router/epp] scorer.kv-cache-utilization-scorer  (0.0 ms)
            [llm-d-router/epp] scorer.queue-scorer  (0.0 ms)
            [llm-d-router/epp] scorer.prefix-cache-scorer  (0.0 ms)
          [llm-d-router/epp] pick_endpoints  (0.0 ms)
        [llm-d-router/epp] index_add  (0.0 ms)
      [vllm-precise-prefix] llm_request  (277.1 ms)
-- traceID=09407c59fba819ce7280444822be185a spans=18 services=4
```

![Jaeger: gateway → IPP → EPP → vLLM](docs/screenshots/jaeger-precise-prefix-trace.png)

`Services 4 | Depth 7 | Total Spans 18`, one trace rooted at the gateway.
Because the IPP runs at `PreRouting` and re-injects the trace context into
the headers it forwards, **the EPP is a child of the IPP**, not of the
gateway. The `tokenize_render` hop is the EPP calling the model servers'
`/render` endpoint, `match_block_keys` → `index_walk` are the KV-block index
lookup, `index_add` records the blocks this request will create, and
`vllm-precise-prefix llm_request` is **vLLM's own span**, exported with
`--otlp-traces-endpoint` and parented under the EPP because agentgateway
forwards the `traceparent` header to the Pod.

> With the published IPP `v0.1.0` image this trace has 3 services and the
> IPP span is a separate root — see the callout in Step 11.

### 5.3 KV-cache-aware routing on real vLLM events

Send the same >64-token prompt six times and read the routing decision off
the spans:

```console
$ ./scripts/drive-traffic.sh 6
req1 http=200 time=0.313978s
req2 http=200 time=0.292445s
…
req6 http=200 time=0.286683s
$ python3 scripts/span-attrs.py 6
trace ac1287ccf65c2371
  produce_precise_prefix_cache   {'producer.candidate_endpoints': 2, 'producer.max_match_blocks': 0, 'producer.total_blocks': 1}
  pick_endpoints                 {'picker.candidate_endpoints': 2, 'picker.top_endpoints': '["…-httgq-rank-0","…-tkgb5-rank-0"]', 'picker.top_scores': '[4,4]'}
trace e2afe49fa5dea93f
  produce_precise_prefix_cache   {'producer.candidate_endpoints': 2, 'producer.max_match_blocks': 1, 'producer.total_blocks': 1}
  pick_endpoints                 {'picker.candidate_endpoints': 2, 'picker.top_endpoints': '["…-httgq-rank-0","…-tkgb5-rank-0"]', 'picker.top_scores': '[7,4]'}
trace b96b577bc15d4632
  produce_precise_prefix_cache   {… 'producer.max_match_blocks': 1 …}
  pick_endpoints                 {… 'picker.top_scores': '[7,4]'}
  (identical for traces a379ba…, 860026…, 15f437…)
```

Read it as: request 1 finds no indexed blocks (`max_match_blocks: 0`), both
replicas tie at **4** (`kv-cache-utilization` 2.0 + `queue` 2.0), and the
picker takes `httgq`. vLLM on `httgq` then publishes a `BlockStored` event
over ZMQ, the EPP indexes it, and from request 2 on the prefix scorer finds
the block (`max_match_blocks: 1`) and adds its weight of **3.0** → **7 vs
4**, sticky to `httgq`. vLLM's own counters agree:

```console
$ curl -s 'http://localhost:9091/api/v1/query' --data-urlencode 'query=sum by (pod) (vllm:prefix_cache_hits_total)'
320{pod=precise-prefix-vllm-5cfc7bc57-httgq}, 0{pod=precise-prefix-vllm-5cfc7bc57-tkgb5}
```

> On the previous DGX Spark attempt (2026-08-24, vLLM 0.20.1 through a
> socat bridge) the same test never hit: the router rejected the event with
> `stores_skipped_total{reason="unsupported_cache_kind"}`. With vLLM 0.27.1
> and today's router that counter has no data and the hit path closes.

### 5.4 The P/D trace

```console
$ curl -sS -X POST http://localhost:8080/v1/chat/completions -H 'Content-Type: application/json' \
    -H 'x-llm-d-pool: pd' \
    -d '{"model":"Qwen/Qwen2.5-1.5B-Instruct","messages":[{"role":"user","content":"hello pd"}],"max_tokens":16}'
{…"choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"Testing, testing "}}]}
$ python3 scripts/trace-tree.py
[llm-d-inference-gateway] POST /*  (5.2 ms)
  [inference.llm-d.ai/inference-payload-processor] gateway.request  (4.7 ms)
    [llm-d-router/epp] request  (2.6 ms)
      [llm-d-router/epp] request_orchestration
        [llm-d-router/epp] tokenize
        [llm-d-router/epp] pick_disagg_profile            # prefill profile
        [llm-d-router/epp] run_scheduler_profile
          [llm-d-router/epp] filter_endpoints
          [llm-d-router/epp] scoring
            [llm-d-router/epp] scorer.active-request-scorer
            [llm-d-router/epp] scorer.prefix-cache-scorer
          [llm-d-router/epp] pick_endpoints
        [llm-d-router/epp] pick_disagg_profile            # decode profile
        [llm-d-router/epp] run_scheduler_profile
          [llm-d-router/epp] filter_endpoints
          [llm-d-router/epp] scoring
            [llm-d-router/epp] scorer.prefix-cache-scorer
            [llm-d-router/epp] scorer.queue-scorer
            [llm-d-router/epp] scorer.kv-cache-utilization-scorer
          [llm-d-router/epp] pick_endpoints
        [llm-d-router/epp] pick_disagg_profile
        [llm-d-router/epp] prepare_disaggregation
      [llm-d-routing-sidecar] llm_d.pd_proxy.POST /v1/chat/completions
        [llm-d-routing-sidecar] forward_request
          [llm-d-routing-sidecar] prefill
            [llm-d-routing-sidecar] HTTP POST             # -> pd-prefill
            [llm-d-routing-sidecar] decode
              [llm-d-routing-sidecar] HTTP POST           # -> pd-decode (local)
-- traceID=c765418bfa80068caa9450d21239e026 spans=28 services=4
```

![Jaeger: P/D trace](docs/screenshots/jaeger-pd-trace.png)

`Services 4 | Depth 8 | Total Spans 28`.

### 5.5 Metrics: Prometheus targets and queries

```console
$ curl -s 'http://localhost:9091/api/v1/targets?state=active' | python3 -c "
import sys,json
for t in json.load(sys.stdin)['data']['activeTargets']:
    if 'llm-d/' in t['scrapePool']: print(t['scrapePool'], t['health'], t['labels'].get('pod',''))"
podMonitor/llm-d/decode/0                  up  pd-decode-5fbc985d56-vc5ns
podMonitor/llm-d/decode/0                  up  precise-prefix-vllm-5cfc7bc57-httgq
podMonitor/llm-d/decode/0                  up  precise-prefix-vllm-5cfc7bc57-tkgb5
podMonitor/llm-d/prefill/0                 up  pd-prefill-6d5db57479-p5nhd
serviceMonitor/llm-d/llm-d-epp-monitor/0   up  llm-d-epp-6bc4b9596-vz7ld
serviceMonitor/llm-d/llm-d-pd-epp-monitor/0 up  llm-d-pd-epp-7cbdcb844d-96fbk

$ q() { curl -s http://localhost:9091/api/v1/query --data-urlencode "query=$1" | jq -r '.data.result[] | "\(.metric.pod // "") \(.value[1])"'; }
$ q 'sum(llm_d_epp_request_total)'
 10
$ q 'llm_d_epp_kv_cache_events_messages_received_total'
llm-d-epp-6bc4b9596-vz7ld 1
$ q 'llm_d_epp_prefix_indexer_size'
llm-d-epp-6bc4b9596-vz7ld 3
llm-d-pd-epp-7cbdcb844d-96fbk 2
$ q 'sum by (pod) (vllm:request_success_total)'
precise-prefix-vllm-5cfc7bc57-httgq 6
precise-prefix-vllm-5cfc7bc57-tkgb5 1
pd-decode-5fbc985d56-vc5ns 1
$ q 'histogram_quantile(0.5, sum by (le) (rate(vllm:time_to_first_token_seconds_bucket[10m])))'
 0.031134077502856548                          # TTFT p50 = 31 ms on the GB10
$ curl -s http://localhost:9091/api/v1/label/__name__/values | jq '[.data[] | select(startswith("vllm:"))] | length, ([.data[] | select(startswith("llm_d_epp"))] | length)'
103          # vllm:* families
73           # llm_d_epp_* families
```

![Prometheus targets](docs/screenshots/prometheus-targets.png)

### 5.6 Grafana

```console
$ curl -s -u admin:admin 'http://localhost:3000/api/search?type=dash-db' | jq -r '.[].title' | grep -E 'llm-d|Inference|P/D'
Inference Gateway
llm-d Diagnostic Drill-Down
llm-d Failure & Saturation Indicators
llm-d Performance Dashboard
llm-d SGLang Overview
llm-d vLLM Overview
P/D Coordinator Metrics
```

**llm-d Performance Dashboard** after the traffic above — KV cache hit rate
61.1 %, TTFT p50 30 ms, inter-token latency p50 16.7 ms:

![Grafana llm-d Performance](docs/screenshots/grafana-performance.png)

**llm-d vLLM Overview**:

![Grafana vLLM Overview](docs/screenshots/grafana-vllm-overview.png)

---

## 6. How it works — one request, component by component

This section follows the `curl` from §5.1 through every hop, naming the
Kubernetes object and the log/span that proves each step.

### 6.1 The GPU plumbing underneath (before any llm-d component)

Three layers have to agree for a Pod to see the GPU, and this demo threads
it through all three:

1. **Host Docker → node container.** The `extraMounts` entry
   `/var/run/nvidia-container-devices/all` in `kind-config.yaml` is turned
   into `NVIDIA_VISIBLE_DEVICES=all` by the host's `nvidia-container-runtime`
   (Step 2's config flag), which injects `/dev/nvidia*` plus the matching
   driver libraries (`libcuda.so.580.173.02`, `libnvidia-ml.so`, …) into the
   node container. Proof: `docker exec llm-d-control-plane nvidia-smi`.
2. **Nested containerd → Pod.** The node's containerd knows an `nvidia`
   handler (`/etc/containerd/conf.d/99-nvidia.toml`, Step 4) that runs
   `/usr/bin/nvidia-container-runtime` *inside the node*. A Pod with
   `runtimeClassName: nvidia` is created through it and gets the same
   injection one level down. Proof: `gpu-smoke-test` Pod.
3. **Scheduler accounting.** The device plugin (Step 5) enumerates the GPU
   via NVML and registers `nvidia.com/gpu` with kubelet over
   `/var/lib/kubelet/device-plugins/nvidia-gpu.sock`; time-slicing makes it
   `4`. When a Pod requests `nvidia.com/gpu: 1`, kubelet asks the plugin to
   *allocate* a slice, and the plugin's answer includes the device
   env/annotations the runtime hook reads. Proof: `Allocated resources:
   nvidia.com/gpu 2` on the node while two vLLM Pods run.

None of the llm-d components know or care about any of this — the only
GPU-specific lines in the whole demo are `runtimeClassName: nvidia` and
`nvidia.com/gpu: 1` on the two vLLM Deployments.

### 6.2 Hop 1 — the client reaches agentgateway

`curl` hits `llm-d-inference-gateway` (`ClusterIP 10.96.169.222:80`). That
Service was created by the agentgateway **control plane**
(`agentgateway-system`) when it reconciled the `Gateway` object from Step 6:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata: { name: llm-d-inference-gateway, namespace: llm-d }
spec: { gatewayClassName: agentgateway, listeners: [{ name: http, port: 80, protocol: HTTP }] }
```

`PROGRAMMED=True` in `kubectl get gateway` means the control plane
generated the data-plane config and pushed it (xDS) to the proxy Pod
`llm-d-inference-gateway-…` in `llm-d`. Because
`manifests/03-gateway-tracing-policy.yaml` attached a
`frontend.tracing` policy with `randomSampling: "true"`, the proxy **starts
a trace** for this request (`POST /*`, the root span in §5.2) and creates
the W3C `traceparent` it will hand to every downstream hop.

### 6.3 Hop 2 — the IPP rewrites the body into headers

`manifests/04-ipp-extproc-policy.yaml` attaches `payload-processor:9004` as
a **`PreRouting` ext_proc**. The proxy streams the request headers and body
to the IPP over gRPC before it matches any route. The IPP's default plugin
chain (`body-field-to-header`, `base-model-to-header`) pulls
`"model": "Qwen/Qwen2.5-1.5B-Instruct"` out of the JSON body and adds
`X-Gateway-Model-Name` / base-model headers:

```console
$ kubectl -n llm-d logs deploy/payload-processor --tail 400 | grep -E 'parsed field|updated base'
{"caller":"bodyfieldtoheader/body_field_to_header.go:121","msg":"parsed field from body","field":"model","value":"Qwen/Qwen2.5-1.5B-Instruct"}
{"caller":"basemodelextractor/base_model_to_header.go:105","msg":"updated base model header based on the request target model", …}
```

Why it exists: Gateway API routing can match on headers but not on JSON
body fields. With the model name in a header, an `HTTPRoute` can route
per model (`httpRoute.baseModel` in the chart) — this demo only has one
model, so the headers are informational here. `secure-serving: false` is
what lets agentgateway's plaintext h2 ext_proc reach it.

### 6.4 Hop 3 — route matching picks an InferencePool, not a Service

Two `HTTPRoute`s are attached to the Gateway:

```yaml
# httproute/llm-d (from the precise-prefix release)
rules:
- matches: [{ path: { type: PathPrefix, value: / } }]
  backendRefs: [{ group: inference.networking.k8s.io, kind: InferencePool, name: llm-d, weight: 1 }]
  timeouts: { request: 300s }
# httproute/llm-d-pd (from the P/D release)
rules:
- matches: [{ path: { type: PathPrefix, value: / }, headers: [{ type: Exact, name: x-llm-d-pool, value: pd }] }]
  backendRefs: [{ kind: InferencePool, name: llm-d-pd, … }]
```

Gateway API precedence prefers the rule with a header match, so a request
carrying `x-llm-d-pool: pd` goes to `llm-d-pd` and everything else to
`llm-d`. The `backendRef` kind is **`InferencePool`** — that is the whole
extension point: because agentgateway was installed with
`inferenceExtension.enabled=true`, it knows that this backend kind means
"call the pool's endpoint picker before forwarding".

The `InferencePool` itself:

```yaml
spec:
  selector:
    matchLabels: { llm-d.ai/guide: precise-prefix-cache-routing }   # Pod labels, resolved via the Pod API
  targetPorts: [{ number: 8000 }]
  endpointPickerRef: { kind: Service, name: llm-d-epp, port: { number: 9002 }, failureMode: FailOpen }
status: Accepted=True, ResolvedRefs=True
```

The selector is a **Pod** label selector — the proxy and the EPP resolve
pool membership from live Pod IPs, never through a Service VIP. That is why
the EPP's ZMQ subscriber (§5.1) and the proxy's upstream both point at
`10.244.0.x` Pod addresses.

### 6.5 Hop 4 — the EPP decides which Pod (the plugin chain)

The proxy opens a second ext_proc stream to `llm-d-epp:9002`, carrying the
`traceparent` the IPP re-injected, so the EPP's `request` span becomes a
child of the IPP's `gateway.request` (itself a child of `POST /*`). Inside `request_orchestration` the EPP runs the chain from
`router-precise-prefix.values.yaml`, in this order:

| Plugin | What it does on this request | Span |
| --- | --- | --- |
| `token-producer` | POSTs the chat messages to `http://precise-prefix-cache-routing-render:8000/v1/chat/completions/render` — a Service whose endpoints are the two vLLM Pods — and gets back the exact token IDs vLLM will see (36 tokens here). No separate tokenizer process. | `tokenize` → `tokenize_render …` |
| `endpoint-notification-source` + `precise-prefix-cache-producer` | Splits the token IDs into 64-token blocks (`blockSizeTokens: 64` = vLLM's `--block-size=64`), hashes them the way vLLM does, and looks each block key up in its **KV-block index**: a map from block hash → set of Pods that currently hold that block. The index is fed by the ZMQ side channel (§6.8), not by this request. Result attributes: `producer.total_blocks`, `producer.max_match_blocks`. | `produce_precise_prefix_cache` → `match_block_keys` → `index_walk` |
| `filter_endpoints` | No filters in this profile — both Pods stay candidates (`candidate_endpoints: 2`). | `filter_endpoints` |
| `kv-cache-utilization-scorer` (weight 2.0) | Scores each Pod by free KV-cache fraction, from the `vllm:*` metrics the EPP scrapes from each Pod's `/metrics` every 50 ms (`metricsDataSource`). | `scorer.kv-cache-utilization-scorer` |
| `queue-scorer` (weight 2.0) | Scores by `vllm:num_requests_waiting` — shorter queue wins. | `scorer.queue-scorer` |
| `prefix-cache-scorer` (weight 3.0) | Uses the producer's match info: a Pod holding the longest matching prefix scores 1.0 × 3.0. | `scorer.prefix-cache-scorer` |
| `max-score-picker` (implicit) | Sums the weighted scores per Pod and picks the max; ties broken randomly. `top_scores=[7,4]` in §5.3 is exactly 3 + 2 + 2 vs 0 + 2 + 2. | `pick_endpoints` |
| index update | Records the block keys this request will create on the chosen Pod (`speculativeIndexing: true`), so the *next* identical request matches even before vLLM's event arrives. | `index_add` |

The EPP answers the ext_proc stream with the chosen Pod's `IP:8000` (as a
header the proxy honours) and the log line `EPP sent request body
response(s) to proxy` with the `x-request-id` that also appears in vLLM's
response `id`.

### 6.6 Hop 5 — the proxy forwards to the Pod; vLLM runs on the GPU

agentgateway sends the original request straight to `10.244.0.45:8000`
(the Pod IP the EPP returned) with the `traceparent` still attached. vLLM's
API server picks it up — `--otlp-traces-endpoint` plus
`--collect-detailed-traces=all` make it emit its own `llm_request` span as a
child of the EPP's, which is the `vllm-precise-prefix` leaf in §5.2 — and
the engine core runs prefill + decode on the GB10. The response retraces
the same path (the IPP also sees the response body, as its log shows).

### 6.7 The P/D variant of hops 4–5

For `x-llm-d-pool: pd` the `llm-d-pd-epp` runs
`router-pd.values.yaml` instead: `always-disagg-pd-decider` says "always
disaggregate", `disagg-profile-handler` therefore runs **two scheduling
profiles** — `prefill` (only Pods with `llm-d.ai/role: prefill` pass
`prefill-filter`) and `decode` (`decode-filter`) — each with its own
`run_scheduler_profile` subtree in the trace, then `prepare_disaggregation`
packs the prefill Pod's address into an `x-prefiller-host-port` header and
returns the **decode** Pod as the target. On the decode Pod the request
lands on port 8000, which is the `llm-d-router-disagg-sidecar` (a native
sidecar `initContainer` with `restartPolicy: Always`): it sends a
`max_tokens=1` prefill call with `kv_transfer_params` to the prefiller
(`prefill` → `HTTP POST`), then the real request to the local model server
on 8200 (`decode` → `HTTP POST`), which — with a real NIXL connector — would
pull the prefill's KV blocks instead of recomputing them. With
`llm-d-inference-sim` the handshake is acknowledged and the decode
generates locally.

### 6.8 The side channel: KV-cache events from vLLM to the EPP

Independently of any request, each vLLM Pod runs a ZMQ **publisher** on
`:5556` (`--kv-events-config … "publisher":"zmq","endpoint":"tcp://*:5556"`)
and a **replay** socket on `:5559`. Every time the engine allocates or
evicts a KV block it publishes `BlockStored` / `BlockRemoved` events under
the topic `kv@<podIP>:8000@<model>`. The EPP side is configured by
`kvEventsConfig` with `discoverPods: true`: it watches the pool's Pods and
dials **each Pod IP** on `socketPort: 5556` (the `Connected subscriber
socket` lines), decodes the msgpack payload, and updates the block index
that `precise-prefix-cache-producer` reads. If the EPP restarts it asks the
replay socket for the events it missed. The `llm_d_epp_kv_cache_events_*`
counters in Prometheus and the `llm-d Performance` dashboard's "KV Cache
Hit Rate" gauge are computed from this index.

### 6.9 Observability — who emits what, and how it is collected

**Traces.** Everything speaks OTLP gRPC to `otel-collector:4317` (Step 7's
standalone collector), which forwards to Jaeger. Producers:

| Producer | Turned on by | Span(s) | Parent |
| --- | --- | --- | --- |
| agentgateway proxy | `AgentgatewayPolicy/gateway-tracing` (`frontend.tracing`, `randomSampling: "true"`) | `POST /*` | root |
| IPP | chart `payloadProcessor.tracing.enabled` | `gateway.request` | gateway (needs a build with #159 — Step 11) |
| EPP (both releases) | `router.tracing.enabled` (`tracing.values.yaml`) | `request`, `request_orchestration`, `tokenize*`, `produce_precise_prefix_cache`, `match_block_keys`, `index_walk`, `index_add`, `run_scheduler_profile`, `filter_endpoints`, `scoring`, `scorer.*`, `pick_endpoints`, `pick_disagg_profile`, `prepare_disaggregation` | gateway |
| routing sidecar | `--tracing=true` + `OTEL_*` env | `llm_d.pd_proxy.*`, `forward_request`, `prefill`, `decode`, `HTTP POST` | P/D EPP |
| **vLLM** | `--otlp-traces-endpoint` + `--collect-detailed-traces=all`, `OTEL_SERVICE_NAME` | `llm_request` | EPP |
| inference-sim | `OTEL_*` env | *(exports nothing, any version)* | — |

Context propagation is plain W3C `traceparent`: the proxy creates it and
passes it on both ext_proc streams and on the upstream HTTP request to the
Pod; the IPP extracts it from the ext_proc request headers and re-injects it
into the headers it forwards (so the EPP hangs under the IPP); the sidecar
re-injects it into its two legs. `llm-d-kv-cache` never appears as a Jaeger service — it is a Go
library inside the EPP, so its spans (`match_block_keys`, `index_walk`,
`index_add`) carry the EPP's service name.

**Metrics.** The Prometheus operator turns two CR kinds into scrape jobs:

| CR | Created by | Scrapes | Notable series |
| --- | --- | --- | --- |
| `ServiceMonitor/llm-d-epp-monitor`, `…/llm-d-pd-epp-monitor` | router chart (`monitoring.prometheus.enabled`) | EPP `:9090/metrics` every 10 s | `llm_d_epp_request_total`, `llm_d_epp_request_duration_seconds`, `llm_d_epp_prefix_indexer_size`, `llm_d_epp_kv_cache_events_messages_received_total`, `llm_d_epp_pool_ready_pods` (73 families) |
| `PodMonitor/decode`, `PodMonitor/prefill` | `guides/recipes/modelserver/components/monitoring{,-pd}` | every Pod with `llm-d.ai/role: decode|prefill`, port `modelserver`, `/metrics` every 30 s | `vllm:num_requests_running`, `vllm:prefix_cache_hits_total`, `vllm:time_to_first_token_seconds`, `vllm:kv_cache_usage_perc` (103 families) |

`install-prometheus-grafana.sh` installs kube-prometheus-stack (Prometheus,
Alertmanager, Grafana, kube-state-metrics, node-exporter) into
`llm-d-monitoring`, provisions the Prometheus datasource, and loads the 7
llm-d dashboards from `guides/recipes/observability/grafana/` as
ConfigMaps. The `llm-d Performance` panels are PromQL over exactly these
series — e.g. the "KV Cache Hit Rate" gauge is
`sum(vllm:prefix_cache_hits_total{…}) / sum(vllm:prefix_cache_queries_total{…})`
(from `ConfigMap/llm-d-performance-kv-cache`).

Note the EPP scrapes the same `vllm:*` metrics itself (every 50 ms, for
scoring) — Prometheus is for humans and dashboards, the EPP's scrape is for
routing.

---

## 7. P/D on a real GPU: what blocked it

The intent was real vLLM prefill/decode with NIXL KV transfer, as in llm-d's
`guides/pd-disaggregation/modelserver/gpu/vllm`. Findings, in order:

1. **The NGC image has the connector but not the runtime.**
   `vllm/distributed/kv_transfer/kv_connector/v1/nixl/` exists and
   `factory.py` registers `NixlConnector`, but `import nixl` fails.
   `pip install nixl==1.4.1` inside the image works
   (`nixl agent OK, backends: [... 'UCX']`) →
   [`images/vllm-nixl/Dockerfile`](images/vllm-nixl/Dockerfile).
2. **`pip install nixl` breaks every Python process at exit.** The meta
   package pulls in *both* `nixl-cu12` and `nixl-cu13`; vLLM's model
   inspection subprocess then `died with <Signals.SIGSEGV: 11>` →
   `Model architectures ['Qwen2ForCausalLM'] failed to be inspected`.
   Installing only `nixl-cu13` did not help either — the crash is in
   `nixl_ep` (expert-parallel ops built against upstream torch 2.14, loaded
   eagerly by vLLM's MoE layers and ABI-incompatible with NGC's
   `torch 2.14.0a0+nv26.08`). Fix in the Dockerfile: `--no-deps` shim +
   `nixl-cu13` + delete `nixl_ep*`. After that `import
   vllm.model_executor.models.qwen2` exits 0 and the NIXL agent initializes.
3. **NIXL worker init eats all memory on GB10.** With the fixed image, both
   as a Kind Pod and as plain `docker run` on the host, the engine logs
   `Initializing NIXL worker <id>` and the process's *host* memory then grows
   without bound until OOMKill — 16 GiB, 48 GiB and a 60 GB `docker
   --memory` cap all hit within ~3 minutes:
   ```console
   nx-default t=150s mem=45.82GiB / 60GiB [Initializing NIXL worker]
   nx-default t=168s mem=59.61GiB / 60GiB [Initializing NIXL worker]
   nx-tcp     … DIED (OOM?) true                      # UCX_TLS=tcp
   nx-cpu     … DIED OOM=true                         # kv_buffer_device=cpu
   ```
   A plain vLLM Pod on the same GPU sits at 3.1 GiB of cgroup memory. The
   registration NIXL/UCX performs on the KV buffers appears to be charged
   to the process on unified memory and never converges. Not pursued further;
   the manifest is kept as
   [`manifests/optional-05-model-servers-pd-vllm-nixl.yaml`](manifests/optional-05-model-servers-pd-vllm-nixl.yaml)
   for whoever wants to retry with a newer NIXL/vLLM build.

So the P/D pool runs on `llm-d-inference-sim:v0.11.0`. Everything upstream
of the model server — the P/D EPP's two-profile scheduling, the
`x-prefiller-host-port` handoff, and the routing sidecar's prefill→decode
legs — is real and visible in the 27-span trace of §5.4.

## 8. Findings vs. the earlier demos (2026-09-20)

| Area | Finding |
| --- | --- |
| Kind on the GPU host | Works with three layers of NVIDIA tooling (host toolkit → node toolkit → device plugin). Time-slicing (`replicas: 4`) is what allows several vLLM Pods on one GPU with real scheduler accounting. |
| NGC image ENTRYPOINT | **Never set `command:` on `nvcr.io/nvidia/vllm` Pods** — it disables CUDA Forward Compatibility and FlashInfer JIT fails with `cudaErrorUnsupportedPtxVersion`. Use `args:` only. |
| vLLM memory sizing on GB10 | Use `--kv-cache-memory-bytes` (skips profiling) **and** a small `--gpu-memory-utilization` (passes the free-memory pre-check). |
| KV-cache hit routing | Reproduced on real vLLM events: `max_match_blocks 0→1`, `top_scores [4,4]→[7,4]`, `vllm:prefix_cache_hits_total` 320 on the sticky replica. |
| vLLM in Jaeger | New: real vLLM exports `llm_request` spans stitched under the EPP; set `OTEL_SERVICE_NAME` or it shows as `unknown_service`. |
| IPP trace | The published `v0.1.0` image (2026-07-12) predates trace-context extraction (#159), so its span is a separate root; a `main` build stitches gateway → IPP → EPP → vLLM. Not an agentgateway issue. |
| Upstream drift since 2026-08-28 | `disagg-headers-handler` removed; `blockSize` → `blockSizeTokens`; `replaySocketPort`; tokenizer via render Service; `httpRoute.headerMatches`; all llm-d images multi-arch; agentgateway CI pin v1.4.1; kube-prometheus-stack 91.4.1. |
| NIXL on GB10 | Blocked (§7). |

## 9. Cleanup

```console
$ kind delete cluster --name llm-d
```

Host config from Step 2 (`default-runtime: nvidia`, the volume-mounts flag)
is left in place; revert by hand and `systemctl restart docker` if you want
`runc` back as the default. `~/llm-d-cache` (model weights) and the host
Docker image cache are also kept, so a re-create skips the 25 GB pull and
the model download.

## 10. Known limitations

- **Single node.** One physical GPU, time-sliced; no memory isolation
  between the vLLM Pods.
- **Shared unified memory.** Anything else on the box (ComfyUI, browsers)
  competes with vLLM; size from `mem_get_info()` and expect
  `No available memory for the cache blocks` if the budget moves.
- **P/D KV transfer is simulated** (§7).
- **IPP must be built from `main`** until a release newer than `v0.1.0`
  exists (Step 11).
- **`--enforce-eager`** trades some decode throughput for a ~1 min cold
  start; drop it for benchmarks (and expect CUDA-graph capture time).

## Files

```text
kind/kind-config.yaml                         Kind cluster: GPU mount + HF cache mount
manifests/00-gpu-runtime.yaml                 RuntimeClass, device-plugin ConfigMap (time-slicing), DaemonSet
manifests/gpu-smoke-test.yaml                 nvidia-smi Pod
manifests/01-namespace.yaml                   Namespace llm-d, ServiceAccount sa
manifests/02-model-servers.yaml               2x vLLM GPU replicas + render Service
manifests/03-gateway-tracing-policy.yaml      agentgateway span export
manifests/04-ipp-extproc-policy.yaml          IPP as PreRouting ext_proc
manifests/05-model-servers-pd.yaml            P/D prefill/decode on inference-sim + routing sidecar
manifests/optional-05-model-servers-pd-vllm-nixl.yaml   the vLLM+NIXL attempt (does not start on GB10)
helm-values/router-precise-prefix.values.yaml EPP plugin chain (precise prefix cache)
helm-values/router-spark.values.yaml          EPP image/resources/selector/monitoring for this host
helm-values/router-pd.values.yaml             P/D EPP plugin chain
helm-values/router-pd-spark.values.yaml       P/D release overrides + header-matched HTTPRoute
helm-values/tracing.values.yaml               EPP -> otel-collector
helm-values/ipp.values.yaml                   IPP chart values (main-local image, secure-serving off)
images/vllm-nixl/Dockerfile                   NGC vLLM + nixl runtime (see §7)
scripts/port-forward.sh                       Jaeger/Prometheus/Grafana/Gateway on localhost
scripts/drive-traffic.sh                      N identical long prompts (optionally to the P/D pool)
scripts/trace-tree.py                         newest Jaeger trace as a span tree
scripts/span-attrs.py                         routing-decision attributes of the last N traces
docs/screenshots/                             captured from this run
```
