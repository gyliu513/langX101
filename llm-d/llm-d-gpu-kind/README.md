# llm-d on Kind — Running Kind Directly on the GPU Host (No Proxy)

This demo answers a follow-up question to
[`../llm-d-gpu-demo`](../llm-d-gpu-demo): *"what if Kind itself ran on the GPU
machine, instead of on a laptop that bridges to a remote GPU over a socat
tunnel?"*

**Answer: yes, and it removes an entire layer.** When Kind runs on the GPU
host, vLLM becomes an ordinary Kubernetes `Deployment` — scheduled,
health-checked, and restarted by kubelet, requesting `nvidia.com/gpu: 1`
exactly the way a Pod requests `cpu` or `memory`. There is no socat bridge
Pod, no external host to SSH into, no ZMQ tunnel — the EPP's KV-cache-event
subscriber connects **directly to the vLLM Pod's IP**, in-cluster.

This document is a from-scratch, command-by-command build log with real
captured output, run on **2026-08-27** against an NVIDIA DGX Spark
(GB10 Grace-Blackwell, aarch64, unified CPU/GPU memory). Every `console`
block below is copy-pasted from the actual terminal session, not
reconstructed after the fact — including the mistakes and crashes, because
they're the most instructive part.

中文版见 [`README-zh.md`](README-zh.md)。

---

## 1. What's different from `llm-d-gpu-demo`

| | `llm-d-gpu-demo` | `llm-d-gpu-kind` (this demo) |
|---|---|---|
| Where Kind runs | Mac (Docker Desktop) | **On the GPU host itself** (Linux, DGX Spark) |
| Where vLLM runs | `docker run` on the GPU host, **outside** Kind | A normal K8s `Deployment`, **inside** Kind |
| How the EPP reaches vLLM | Through a 2-container `socat` proxy Pod tunneling to the external host over LAN | Directly, via the vLLM Pod's own cluster IP |
| GPU as a K8s concept | Doesn't exist — GPU is invisible to the scheduler | `nvidia.com/gpu` is a real schedulable resource on the node |
| Failure recovery | Manual (`docker restart` on the remote host) | Automatic (kubelet restarts the container per its restart policy) |
| Extra moving parts | `gpu-vllm-proxy` Deployment + PodMonitor | None — one Deployment |

The trade-off: this setup only works if Kind's control-plane node and the
GPU are the same machine. If your GPU lives on a separate box from where you
run `kind create cluster`, you're back to needing the proxy-bridge pattern
from `llm-d-gpu-demo`.

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ DGX Spark (192.168.1.112) — Ubuntu 24.04 aarch64, NVIDIA GB10        │
│                                                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Docker daemon (default-runtime = nvidia)                       │  │
│  │                                                                 │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │ Kind node container "llm-d-gpu-kind-control-plane"       │  │  │
│  │  │ (has /dev/nvidia*, driver libs bind-mounted in;           │  │  │
│  │  │  runs its own nested containerd + kubelet)                │  │  │
│  │  │                                                            │  │  │
│  │  │  containerd (RuntimeClass "nvidia" registered)             │  │  │
│  │  │   │                                                        │  │  │
│  │  │   ├─ Pod: agentgateway (data-plane proxy)  :80             │  │  │
│  │  │   │      Gateway API + InferencePool aware                 │  │  │
│  │  │   │                                                        │  │  │
│  │  │   ├─ Pod: llm-d-epp (2 containers: epp + vllm-render)      │  │  │
│  │  │   │      :9002 ext_proc gRPC, :9090 metrics                │  │  │
│  │  │   │      subscribes ZMQ :5556 directly on vllm-qwen's IP   │  │  │
│  │  │   │                                                        │  │  │
│  │  │   ├─ Pod: vllm-qwen  (runtimeClassName: nvidia)             │  │  │
│  │  │   │      resources.limits: {nvidia.com/gpu: 1}              │  │  │
│  │  │   │      :8000 OpenAI HTTP API, :5556 ZMQ KV-cache events   │  │  │
│  │  │   │      ── really executes on the GB10 GPU ──              │  │  │
│  │  │   │                                                        │  │  │
│  │  │   └─ DaemonSet: nvidia-device-plugin-daemonset (kube-system)│  │  │
│  │  │          registers `nvidia.com/gpu` with kubelet            │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  (unrelated, pre-existing on this shared workstation:                │
│   vllm-gpu-0 container from llm-d-gpu-demo, ComfyUI, Grafana, ...)   │
└─────────────────────────────────────────────────────────────────────┘
```

Two levels of container nesting matter here, and the GPU has to be threaded
through both:

1. **Host Docker → Kind node container.** The node is "just" a Docker
   container. For it to see the GPU, Docker's `nvidia` runtime has to inject
   `/dev/nvidia*` and the driver libraries into it — same mechanism as
   `docker run --gpus all`.
2. **containerd (inside the node) → Pod container.** Kubernetes Pods aren't
   started by the host's Docker at all; they're started by the *nested*
   containerd running inside the node container. That nested containerd
   needs its **own** copy of `nvidia-container-toolkit` and its own runtime
   registration, or Pods inside Kind will never see the GPU even though the
   node container can.

Missing either layer is the single most common way this kind of setup fails
silently (node has GPU, Pods don't, or vice versa).

## 3. Prerequisites

| Requirement | Why | Check |
|---|---|---|
| Linux host with NVIDIA GPU + driver | Kind's node-container GPU trick doesn't exist on Docker Desktop for Mac/Windows — there's no GPU passthrough into their Linux VM | `nvidia-smi` |
| `nvidia-container-toolkit` installed on the host | Provides `nvidia-ctk` and the `nvidia-container-runtime` that Docker/containerd shell out to | `dpkg -l \| grep nvidia-container-toolkit` |
| Docker with the current user in the `docker` group | We install kind/kubectl/helm without `sudo`, and drive `docker`/`kind`/`kubectl` without `sudo` | `docker ps` (no `sudo` needed) |
| `sudo` access | Three **one-time** host-level config commands genuinely need root: editing `/etc/docker/daemon.json`, editing `/etc/nvidia-container-runtime/config.toml`, and `systemctl restart docker` | — |
| Internet egress from the host | Pulls `kindest/node`, `nvcr.io/nvidia/vllm:26.05-py3` (~9.5 GB), the device-plugin image, and downloads the model from Hugging Face | `curl -sS -o /dev/null -w '%{http_code}\n' https://github.com` |

Environment actually used below:

```console
$ uname -a
Linux spark 6.14.0-1015-nvidia #15-Ubuntu SMP PREEMPT_DYNAMIC Tue Nov 25 18:02:16 UTC 2025 aarch64 aarch64 aarch64 GNU/Linux
$ docker version --format '{{.Server.Version}}'
28.5.1
$ nvidia-smi --query-gpu=name,driver_version --format=csv
name, driver_version
NVIDIA GB10, 580.126.09
```

> **GB10 quirk you will hit later:** this chip has unified CPU/GPU memory, so
> `nvidia-smi --query-gpu=memory.total` reports `[N/A]` and NVML's
> `nvmlDeviceGetMemoryInfo()` call returns `Not Supported`. This breaks older
> versions of the NVIDIA k8s device plugin outright (see Step 7).

## 4. Step-by-step install

### Step 1 — Install kind, kubectl, helm (no sudo)

Installed to `~/bin` on the DGX Spark itself, since we don't have `sudo` for
writing to `/usr/local/bin`:

```console
$ curl -sSL -o ~/bin/kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-linux-arm64 && chmod +x ~/bin/kind
$ ~/bin/kind version
kind v0.31.0 go1.25.5 linux/arm64

$ curl -sSL -o ~/bin/kubectl "https://dl.k8s.io/release/$(curl -sSL https://dl.k8s.io/release/stable.txt)/bin/linux/arm64/kubectl" && chmod +x ~/bin/kubectl
$ ~/bin/kubectl version --client
Client Version: v1.37.0

$ HELM_INSTALL_DIR=~/bin bash <(curl -sSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3) --no-sudo
$ ~/bin/helm version
version.BuildInfo{Version:"v3.21.4", ...}
```

### Step 2 — Configure Docker for GPU passthrough

**This step needs real root**, so it can't be automated blindly over a
non-interactive SSH pipe (`sudo` needs a tty to prompt for a password). Run
it with `ssh -t` so `sudo` can actually ask:

```console
$ sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
$ sudo sed -i 's/#accept-nvidia-visible-devices-as-volume-mounts = false/accept-nvidia-visible-devices-as-volume-mounts = true/' /etc/nvidia-container-runtime/config.toml
$ sudo systemctl restart docker
```

What each line does:

- `nvidia-ctk runtime configure --runtime=docker --set-as-default` writes
  `/etc/docker/daemon.json` so Docker knows about an `nvidia` runtime *and*
  makes it the default for every new container on this host:
  ```json
  {
      "default-runtime": "nvidia",
      "runtimes": { "nvidia": { "path": "nvidia-container-runtime", "args": [] } }
  }
  ```
  `nvidia-container-runtime` is a thin wrapper around `runc`: for a container
  with no GPU request, it behaves exactly like plain `runc`. It only injects
  GPU devices/libraries when told to.
- The `sed` line flips on
  `accept-nvidia-visible-devices-as-volume-mounts`. This is the load-bearing
  trick for the next step: **Kind has no `--gpus` flag**, so there's no
  normal way to tell the runtime "this container wants the GPU." With this
  setting on, the runtime treats a bind-mount whose *destination* matches
  `/var/run/nvidia-container-devices/<name>` as equivalent to setting the
  environment variable `NVIDIA_VISIBLE_DEVICES=<name>` — and Kind's cluster
  config format *does* let you add arbitrary bind mounts (`extraMounts`).
- `systemctl restart docker` applies the new default runtime.

> ### ⚠️ Real incident: this restart killed an unrelated running container
>
> This DGX Spark already had a container called `vllm-gpu-0` running (the
> real-GPU backend for `llm-d-gpu-demo`). `systemctl restart docker` is not
> "add config, keep running" — Docker's default behavior (no
> `--live-restore`) is to **stop every running container** during a clean
> daemon shutdown, and containers started with plain `docker run -d` (no
> `--restart` policy) do **not** come back on their own:
> ```console
> $ docker ps -a
> CONTAINER ID   IMAGE                           STATUS                      NAMES
> 5e4f32eba04a   nvcr.io/nvidia/vllm:26.05-py3   Exited (0) 22 seconds ago   vllm-gpu-0
> ```
> Fix: `docker start vllm-gpu-0` — but its old `--gpu-memory-utilization 0.03`
> then failed to allocate KV-cache blocks (see the next callout), so it had
> to be recreated with a slightly larger budget. **Lesson: `systemctl restart
> docker` is not safe on a host with other unmanaged GPU containers on it —
> either add `--restart=unless-stopped` to those containers ahead of time, or
> expect to manually restart them.**

### Step 3 — Create the Kind cluster with the GPU bind-mount trick

`kind/kind-config.yaml`:

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: llm-d-gpu-kind
nodes:
- role: control-plane
  extraMounts:
  - hostPath: /dev/null
    containerPath: /var/run/nvidia-container-devices/all
  kubeadmConfigPatches:
  - |
    kind: KubeletConfiguration
    maxPods: 250
    evictionHard:
      memory.available: "512Mi"
```

`hostPath: /dev/null` is arbitrary — the *destination* path is what the
runtime hook reads, the *source* just has to be something that always
exists. `all` as the mount's basename means "expose every GPU on this host."

```console
$ kind create cluster --config kind/kind-config.yaml
Creating cluster "llm-d-gpu-kind" ...
 ✓ Ensuring node image (kindest/node:v1.35.0) 🖼
 ✓ Preparing nodes 📦
 ✓ Writing configuration 📜
 ✓ Starting control-plane 🕹️
 ✓ Installing CNI 🔌
 ✓ Installing StorageClass 💾
Set kubectl context to "kind-llm-d-gpu-kind"
```

Verify the GPU actually made it into the node container — **this is Docker
seeing the GPU, not Kubernetes yet**:

```console
$ docker exec llm-d-gpu-kind-control-plane ls -la /dev/ | grep -i nvidia
crw-rw-rw-  1 root root  195, 254 nvidia-modeset
crw-rw-rw-  1 root root  499,   0 nvidia-uvm
crw-rw-rw-  1 root root  499,   1 nvidia-uvm-tools
crw-rw-rw-  1 root root  195,   0 nvidia0
crw-rw-rw-  1 root root  195, 255 nvidiactl

$ docker exec llm-d-gpu-kind-control-plane nvidia-smi
Thu Aug 27 11:23:06 2026
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.126.09    Driver Version: 580.126.09    CUDA Version: 13.0                |
|   0  NVIDIA GB10   On  | 0000000F:01:00.0 Off |  N/A   50C  12W  0%  Default             |
+-----------------------------------------------------------------------------------------+
```

If that worked, `nvidia-ctk`'s driver-library mounts also came along for
free (the runtime injects both the device nodes and the matching
`libcuda.so`/`libnvidia-ml.so` etc. together).

### Step 4 — Give the *nested* containerd GPU support too

The node container can see the GPU, but Kubernetes Pods are started by the
containerd running **inside** that node, which is a stock `kindest/node`
image with no NVIDIA tooling at all yet. Install it there, using the node's
own (working) internet access:

```console
$ docker exec llm-d-gpu-kind-control-plane bash -c '
  apt-get install -y -qq curl gnupg
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" | \
    tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -qq
  apt-get install -y -qq nvidia-container-toolkit
'
```

Then register an `nvidia` runtime handler in the **nested** containerd
(deliberately *not* as the default — only Pods that explicitly opt in via
`runtimeClassName: nvidia` should get GPU injection):

```console
$ docker exec llm-d-gpu-kind-control-plane nvidia-ctk runtime configure --runtime=containerd --config=/etc/containerd/config.toml
INFO[...] Wrote updated config to /etc/containerd/conf.d/99-nvidia.toml
INFO[...] It is recommended that containerd daemon be restarted.
```

> containerd 2.x supports drop-in config files under `/etc/containerd/conf.d/`
> (imported via `imports = ["/etc/containerd/conf.d/*.toml"]` in the main
> config) — `nvidia-ctk` wrote there instead of editing `config.toml`
> directly. Either is fine; the drop-in is arguably cleaner.

```console
$ docker exec llm-d-gpu-kind-control-plane systemctl restart containerd
$ docker exec llm-d-gpu-kind-control-plane systemctl is-active containerd
active
$ kubectl get nodes
NAME                           STATUS   ROLES           AGE   VERSION
llm-d-gpu-kind-control-plane   Ready    control-plane   20s   v1.35.0
```

Node stayed `Ready` through the containerd restart — kubelet reconnected on
its own.

Now tell Kubernetes about this runtime with a `RuntimeClass`:

```console
$ kubectl apply -f - <<'YAML'
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
YAML
runtimeclass.node.k8s.io/nvidia created
```

### Step 5 — Deploy the NVIDIA device plugin (and hit the GB10 bug)

The device plugin is what turns "a GPU containerd can start Pods on" into
"`nvidia.com/gpu` is a resource the scheduler knows about." First attempt,
with a fairly recent but not-quite-latest image tag:

```console
$ kubectl apply -f manifests/nvidia-device-plugin.yaml   # v0.17.1 at this point
$ kubectl -n kube-system logs -l name=nvidia-device-plugin-ds --tail 5
E... error visiting device: error building Device: error getting device memory: Not Supported
```

Exactly the GB10 unified-memory quirk flagged in §3: the plugin calls
`nvmlDeviceGetMemoryInfo()` to build its internal device map, GB10 returns
`Not Supported` (it has no discrete VRAM to report), and v0.17.1 treats that
as fatal. This is a
[known, fixed issue](https://github.com/NVIDIA/k8s-device-plugin/issues/1482) —
**v0.17.4+ tolerates the `Not Supported` response.** Bumping the tag:

```console
$ kubectl apply -f manifests/nvidia-device-plugin.yaml   # now v0.17.4
$ kubectl -n kube-system logs -l name=nvidia-device-plugin-ds --tail 5
W... devices.go:77] Ignoring error getting device memory: Not Supported
I... server.go:195] Starting GRPC server for 'nvidia.com/gpu'
I... server.go:146] Registered device plugin for 'nvidia.com/gpu' with Kubelet
```

Verify the node now advertises a real GPU resource:

```console
$ kubectl get node llm-d-gpu-kind-control-plane -o jsonpath='{.status.allocatable}' | tr ',' '\n' | grep gpu
"nvidia.com/gpu":"1"
```

Prove it end-to-end with a plain smoke-test Pod — no llm-d involved yet,
just "can a Pod that asks for `nvidia.com/gpu: 1` actually run `nvidia-smi`
on the real GPU":

```console
$ kubectl apply -f - <<'YAML'
apiVersion: v1
kind: Pod
metadata:
  name: gpu-smoke-test
spec:
  restartPolicy: Never
  runtimeClassName: nvidia
  containers:
  - name: cuda
    image: nvcr.io/nvidia/cuda:13.0.1-base-ubuntu24.04
    command: ["nvidia-smi"]
    resources:
      limits: { nvidia.com/gpu: 1 }
YAML
$ kubectl logs gpu-smoke-test
Thu Aug 27 11:27:56 2026
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.126.09    Driver Version: 580.126.09    CUDA Version: 13.0                |
|   0  NVIDIA GB10   On  | 0000000F:01:00.0 Off |  N/A   50C  12W  0%  Default             |
+-----------------------------------------------------------------------------------------+
```

**This is the milestone the whole demo is built around**: a normal
`kubectl apply` Pod, scheduled by the default scheduler because it asked for
`nvidia.com/gpu: 1`, running real code on the real GPU. No proxy, no
external host, no `docker run` needed.

### Step 6 — Namespace, CRDs, agentgateway, Gateway

```console
$ kubectl apply -f - <<'YAML'
apiVersion: v1
kind: Namespace
metadata:
  name: llm-d
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: sa
  namespace: llm-d
automountServiceAccountToken: false
YAML

$ kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml
$ kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.5.0/v1-manifests.yaml
$ kubectl apply -k "https://github.com/llm-d/llm-d-router/config/crd?ref=main"
```

These three commands install, respectively: **Gateway API** (`GatewayClass`,
`Gateway`, `HTTPRoute` — Kubernetes' "next-gen Ingress"), **Gateway API
Inference Extension / GAIE** (`InferencePool` — a resource type specifically
for "a group of model-server replicas," which is what the EPP watches), and
**llm-d's own CRDs** (`InferenceObjective`, `InferenceModelRewrite`).

```console
$ helm upgrade --install agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds \
  --namespace agentgateway-system --create-namespace --version v1.1.0

$ helm upgrade --install agentgateway oci://cr.agentgateway.dev/charts/agentgateway \
  --namespace agentgateway-system --create-namespace --version v1.1.0 \
  --set inferenceExtension.enabled=true

$ kubectl apply -k "https://github.com/llm-d/llm-d/guides/recipes/gateway/agentgateway?ref=main" -n llm-d
gateway.gateway.networking.k8s.io/llm-d-inference-gateway created

$ kubectl get gatewayclass agentgateway
NAME           CONTROLLER                      ACCEPTED   AGE
agentgateway   agentgateway.dev/agentgateway   True       2s

$ kubectl get gateway -n llm-d
NAME                      CLASS          ADDRESS   PROGRAMMED   AGE
llm-d-inference-gateway   agentgateway             True         6s
```

`--set inferenceExtension.enabled=true` is the switch that makes agentgateway
watch `InferencePool` resources natively and know how to call an EPP's
`ext_proc` endpoint — without it you'd have to wire that up by hand with an
`AgentgatewayPolicy`.

### Step 7 — Deploy vLLM as a native GPU Deployment

This replaces the entire `gpu-vllm-proxy` Deployment from `llm-d-gpu-demo`.
Full manifest: [`manifests/vllm-gpu-native.yaml`](manifests/vllm-gpu-native.yaml).
The parts that matter:

```yaml
spec:
  template:
    metadata:
      labels:
        llm-d.ai/role: decode
        llm-d.ai/guide: gpu-kind-native   # <- EPP's selector matches this
        llm-d.ai/model: Qwen2.5-1.5B-Instruct
    spec:
      serviceAccountName: sa
      runtimeClassName: nvidia            # <- opt in to GPU injection
      containers:
        - name: vllm
          image: nvcr.io/nvidia/vllm:26.05-py3
          command: ["vllm", "serve", "Qwen/Qwen2.5-1.5B-Instruct"]
          args:
            - "--port=8000"
            - "--block-size=64"
            - "--gpu-memory-utilization=0.05"
            - "--max-model-len=4096"
            - "--enforce-eager"
            - "--kv-events-config={...,\"endpoint\":\"tcp://*:5556\",...}"
          resources:
            limits: { nvidia.com/gpu: 1 }   # <- this is the whole trick
```

```console
$ kubectl apply -f manifests/vllm-gpu-native.yaml
deployment.apps/vllm-qwen created
$ kubectl -n llm-d get pods -l llm-d.ai/guide=gpu-kind-native
NAME                        READY   STATUS              RESTARTS   AGE
vllm-qwen-66c85c6f4-hfbgd   0/1     ContainerCreating   0          0s
```

> ### ⚠️ Real incident #1: cold image pull takes minutes
>
> Kind's nested containerd has its **own image store**, completely separate
> from the host Docker's cache — even though `vllm-gpu-0` had already pulled
> this exact image outside Kind, the in-cluster Pod had to pull all
> 9.5 GB again from scratch:
> ```console
> Normal  Pulling  kubelet  spec.containers{vllm}: Pulling image "nvcr.io/nvidia/vllm:26.05-py3"
> Normal  Pulled   kubelet  Successfully pulled image ... in 2m58.136s. Image size: 9486739495 bytes.
> ```
>
> ### ⚠️ Real incident #2: the Pod crashed once, then healed itself
> ```console
> $ kubectl -n llm-d get pods -l llm-d.ai/guide=gpu-kind-native
> NAME                        READY   STATUS    RESTARTS      AGE
> vllm-qwen-66c85c6f4-hfbgd   0/1     Running   1 (42s ago)   4m
> ```
> The first attempt hit the same KV-cache-memory error as the `vllm-gpu-0`
> incident above (`ValueError: No available memory for the cache blocks`) —
> unsurprising, since this GPU is momentarily shared with a second vLLM
> engine *and* the host's ComfyUI sessions. **kubelet just restarted the
> container per its default restart policy, and the second attempt
> succeeded** — no `docker start` needed by a human this time. This is the
> concrete, hands-on version of "Kubernetes manages the container's
> lifecycle" from the original conceptual discussion this demo grew out of.

```console
$ kubectl -n llm-d wait --for=condition=Ready pod -l llm-d.ai/guide=gpu-kind-native --timeout=900s
pod/vllm-qwen-66c85c6f4-hfbgd condition met
$ kubectl -n llm-d get pods -l llm-d.ai/guide=gpu-kind-native
NAME                        READY   STATUS    RESTARTS      AGE
vllm-qwen-66c85c6f4-hfbgd   1/1     Running   1 (93s ago)   4m51s
```

### Step 8 — Install the router (EPP + InferencePool)

```console
$ kubectl create secret generic llm-d-hf-token -n llm-d \
  --from-literal=HF_TOKEN="" --dry-run=client -o yaml | kubectl apply -f -

$ helm install llm-d oci://ghcr.io/llm-d/charts/llm-d-router-gateway --version v0 \
  -f helm-values/precise-prefix-router.values.yaml \
  -f helm-values/gw-kind-gpu.values.yaml \
  --set provider.name=none \
  --set httpRoute.create=true \
  --set httpRoute.inferenceGatewayName=llm-d-inference-gateway \
  -n llm-d
NAME: llm-d
STATUS: deployed
```

`helm-values/gw-kind-gpu.values.yaml` sets
`router.modelServers.matchLabels: {llm-d.ai/guide: gpu-kind-native}` — this
one line is the entire connection between the EPP and the real vLLM Pod;
everything else about routing (scoring, prefix-cache awareness) is generic
and doesn't know or care that the backend happens to be a real GPU this
time.

```console
$ kubectl -n llm-d get pods
NAME                                       READY   STATUS    RESTARTS      AGE
llm-d-epp-7c8c9f5b8d-tf7sm                 2/2     Running   0             5m17s
llm-d-inference-gateway-86b846c879-4dcjb   1/1     Running   0             6m20s
vllm-qwen-66c85c6f4-hfbgd                  1/1     Running   1 (2m ago)    5m57s
```

**The single most important log line in this whole demo** — proof the proxy
layer is truly gone:

```console
$ kubectl -n llm-d logs deploy/llm-d-epp -c epp | grep zmq
{"logger":"zmq-subscriber","msg":"Connected subscriber socket","endpoint":"tcp://10.244.0.10:5556"}
```

`10.244.0.10` is `vllm-qwen`'s own Pod IP. Compare to `llm-d-gpu-demo`,
where this same log line pointed at the `gpu-vllm-proxy` Pod's IP, which
then forwarded over LAN to a completely different machine.

### Step 9 — End-to-end test through the Gateway

```console
$ GWIP=$(kubectl get svc llm-d-inference-gateway -n llm-d -o jsonpath='{.spec.clusterIP}')
$ kubectl run trig --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d -- \
  curl -sS -X POST http://$GWIP:80/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen2.5-1.5B-Instruct","messages":[{"role":"user","content":"Say hi in exactly three words."}],"max_tokens":20}'

{"id":"chatcmpl-e343c7b9-7fc3-428c-a36f-7145163e22b7","object":"chat.completion",
 "model":"Qwen/Qwen2.5-1.5B-Instruct",
 "choices":[{"index":0,"message":{"role":"assistant","content":"Hello there!"},"finish_reason":"stop"}],
 "usage":{"prompt_tokens":36,"completion_tokens":4,"total_tokens":40}}
```

A real completion, from a real GPU, through the full Gateway → EPP →
InferencePool → Pod chain, on a cluster whose only non-standard ingredient
is `runtimeClassName: nvidia` on one Deployment.

Corresponding EPP-side log entry — same request, `x-request-id` matches the
`chatcmpl-...` id above:

```console
$ kubectl -n llm-d logs deploy/llm-d-epp -c epp --tail 30 | grep prefix
{"logger":"prefix","msg":"PrefixCacheMatchInfo not found for endpoints, assigning score 0",
 "x-request-id":"e343c7b9-7fc3-428c-a36f-7145163e22b7","incomingModelName":"Qwen/Qwen2.5-1.5B-Instruct"}
```

(Score 0 because this was the very first request — nothing in the KV-cache
index yet. A second request with an overlapping prompt prefix would score
above 0 and get routed with that in mind; with only one backend Pod in this
demo the scorer can't actually change *which* Pod gets picked, but the same
mechanism is what drives real routing decisions once you scale to N
replicas.)

Confirms both vLLM engines are alive on the GPU simultaneously (this
demo's `vllm-qwen` + the older `llm-d-gpu-demo`'s `vllm-gpu-0`, still
running, undisturbed):

```console
$ nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
pid, process_name, used_gpu_memory [MiB]
3858903, VLLM::EngineCore, 6265 MiB
3880364, VLLM::EngineCore, 5530 MiB
```

And the node's resource accounting now treats the GPU exactly like any other
resource:

```console
$ kubectl describe node llm-d-gpu-kind-control-plane | sed -n '/Allocated resources/,/Events/p'
Allocated resources:
  Resource           Requests     Limits
  --------           --------     ------
  cpu                2950m (14%)  4100m (20%)
  memory             8994Mi (7%)  6534Mi (5%)
  nvidia.com/gpu     1            1
```

---

## 5. What each component/CR actually is

| Resource | Kind | Namespace | What it means here |
|---|---|---|---|
| `RuntimeClass/nvidia` | built-in K8s type | cluster-scoped | A named pointer to a containerd runtime handler. Any Pod that sets `spec.runtimeClassName: nvidia` gets its container created via `nvidia-container-runtime` instead of plain `runc`, which is what actually injects `/dev/nvidia*` + driver libs into that specific container. Everything else on the node is unaffected (`default_runtime_name` is still `runc`). |
| `DaemonSet/nvidia-device-plugin-daemonset` | `apps/v1` | `kube-system` | One Pod per node; talks to NVML to enumerate physical GPUs and registers the `nvidia.com/gpu` resource with kubelet over a Unix socket (`/var/lib/kubelet/device-plugins/`). Without this, `nvidia.com/gpu` in a Pod spec is meaningless to the scheduler — it just fails to schedule ("Insufficient nvidia.com/gpu"). |
| `GatewayClass/agentgateway` | Gateway API | cluster-scoped | Declares that a controller named `agentgateway.dev/agentgateway` exists and can fulfill `Gateway` resources that reference this class. Analogous to `StorageClass` for storage. |
| `Gateway/llm-d-inference-gateway` | Gateway API | `llm-d` | The actual listener (port 80 here) that agentgateway programs into its data-plane proxy. `status.conditions[Programmed]=True` means the proxy config was actually generated and is live, not just that the object was accepted by the API server. |
| `HTTPRoute/llm-d` | Gateway API | `llm-d` | Binds a path prefix (`/`) on the `Gateway` above to a `backendRef` — and that backend isn't a `Service`, it's an `InferencePool` (see next row). This is the extension point where "generic HTTP gateway" turns into "inference-aware gateway." |
| `InferencePool/llm-d` | Gateway API Inference Extension | `llm-d` | The core llm-d abstraction: "a set of interchangeable model-server replicas for one model," identified by `spec.selector.matchLabels` (here: `llm-d.ai/guide: gpu-kind-native`) — **a Pod label selector, evaluated live against the Kubernetes Pod API, never a Service VIP.** `spec.endpointPickerRef` points at the EPP's Service:port that decides *which* matching Pod handles each request. |
| `Deployment/llm-d-epp` | `apps/v1` | `llm-d` | The Endpoint Picker (EPP) — a 2-container Pod (`epp` + `vllm-render` tokenizer sidecar). Implements the `ext_proc` gRPC contract agentgateway calls into on every request; runs the configured plugin chain (see §6) to pick a target Pod IP from the `InferencePool`'s current member set. |
| `Deployment/vllm-qwen` | `apps/v1` | `llm-d` | The model server itself. The only GPU-specific fields are `spec.template.spec.runtimeClassName: nvidia` and `resources.limits.{nvidia.com/gpu: 1}` — everything else is a completely ordinary Deployment. |
| `Secret/llm-d-hf-token` | core `v1` | `llm-d` | An (empty, for a public model) Hugging Face token. The EPP's `vllm-render` sidecar container references this env var unconditionally in the chart template; omitting the Secret makes the Pod fail with `CreateContainerConfigError` even though the token itself is never used for a public model. |
| `ServiceAccount/sa` | core `v1` | `llm-d` | Identity the workload Pods run as; `automountServiceAccountToken: false` because nothing in this demo calls the Kubernetes API from inside a Pod. |

## 6. Request-flow walkthrough

Numbered against the `curl` test in Step 9:

1. **Client → Gateway Service.** `curl` hits `llm-d-inference-gateway`'s
   `ClusterIP:80`. This Service is a plain L4 `LoadBalancer`-type Service
   (pending an external IP in Kind, which is fine — we hit the ClusterIP
   directly) whose Endpoints point at the `agentgateway` data-plane Pod.
2. **agentgateway matches the `HTTPRoute`.** Path `/` on this `Gateway`
   resolves to the `HTTPRoute/llm-d` rule, whose `backendRef` is
   `InferencePool/llm-d`, not a normal Service.
3. **agentgateway calls the EPP over `ext_proc` (gRPC), before forwarding
   anywhere.** Because `inferenceExtension.enabled=true` was set at install
   time, agentgateway knows that an `InferencePool` backend means "ask this
   EPP which Pod to use" rather than "load-balance across a Service's
   Endpoints."
4. **EPP resolves pool membership.** It watches the Kubernetes Pod API for
   Pods matching `InferencePool.spec.selector` (`llm-d.ai/guide:
   gpu-kind-native`) — right now, that's exactly one Pod, `vllm-qwen`'s.
5. **EPP runs its scoring plugin chain** (configured in
   `helm-values/precise-prefix-router.values.yaml`):
   - `token-producer` — tokenizes the incoming prompt (via the `vllm-render`
     sidecar) so downstream plugins reason in real token counts, not
     characters.
   - `precise-prefix-cache-producer` — maintains a per-Pod index of which
     64-token KV-cache blocks that Pod's vLLM engine currently holds,
     **built from real ZMQ events vLLM publishes on port 5556** (this is
     the subscription connected directly to `vllm-qwen`'s Pod IP, no proxy —
     see Step 8).
   - `prefix-cache-scorer` (weight 3.0), `kv-cache-utilization-scorer`
     (weight 2.0), `queue-scorer` (weight 2.0) — score every candidate Pod;
     `max-score-picker` picks the winner.
6. **EPP returns the winning Pod's IP\:port to agentgateway** over the same
   `ext_proc` call.
7. **agentgateway proxies the original HTTP request to `vllm-qwen`'s Pod IP
   directly** (`10.244.0.10:8000` in this run) — a plain in-cluster L3/L4
   hop, no further indirection.
8. **vLLM executes the request on the real GB10 GPU** and streams back an
   OpenAI-compatible response, which retraces the same path to the client.
9. **Side channel, continuously:** vLLM publishes a KV-cache-block-added/
   removed event over ZMQ on port 5556 every time it allocates or evicts a
   cache block; the EPP's `precise-prefix-cache-producer` consumes this
   independently of any particular request, keeping its index current for
   the *next* request's `prefix-cache-scorer` decision.

## 7. Cleanup

```console
$ kind delete cluster --name llm-d-gpu-kind
```

This removes the entire cluster (all Pods, the node container, its
containerd/kubelet, everything) in one step. It does **not** touch
`/etc/docker/daemon.json` or `/etc/nvidia-container-runtime/config.toml` on
the host — if you want Docker's default runtime back to `runc`, edit those
by hand and `sudo systemctl restart docker` again (and remember the restart
will stop unmanaged containers, same as in Step 2).

## 8. Known limitations

- **Single node only.** Multi-node Kind-on-GPU setups need this same GPU
  passthrough repeated per node, and only make sense if each node has its
  own physical GPU.
- **GPU memory is a shared, moving target.** This DGX Spark's unified memory
  is shared with the host's other GPU workloads (this session ran alongside
  two ComfyUI processes and the older `llm-d-gpu-demo`'s `vllm-gpu-0`); the
  `--gpu-memory-utilization` value that works today may not tomorrow. Watch
  for `ValueError: No available memory for the cache blocks` and raise it.
- **Two levels of container nesting to keep in sync.** If you ever
  re-provision the node (e.g. `kind delete && kind create` after a Docker
  upgrade), Steps 4–5 (installing `nvidia-container-toolkit` *inside* the
  node and registering the `RuntimeClass`) have to be redone — they're not
  part of the stock `kindest/node` image.
- **No autoscaling, tracing, or P/D disaggregation in this demo** — those
  are orthogonal to the "is Kind on the GPU host" question this demo
  answers, and are already covered by `llm-d-gpu-demo`'s WVA/HPA, Jaeger, and
  P/D sections respectively.
