# llm-d on Kind —— 把 Kind 直接跑在 GPU 主机上（不需要代理）

这个 demo 回答的是 [`../llm-d-gpu-demo`](../llm-d-gpu-demo) 引出的一个后续问题：
**"如果 Kind 本身就跑在 GPU 那台机器上，而不是跑在一台通过 socat 隧道桥接远程
GPU 的笔记本上，会怎样？"**

**答案：可以，而且能直接砍掉一整层。** 当 Kind 跑在 GPU 主机上时，vLLM 就变成
了一个普普通通的 Kubernetes `Deployment`——由 kubelet 调度、健康检查、失败重
启，像申请 `cpu`/`memory` 一样申请 `nvidia.com/gpu: 1`。不再需要 socat 桥接
Pod，不再需要 SSH 到外部主机，也不再需要 ZMQ 隧道——EPP 订阅 KV-cache 事件时
**直接连到 vLLM Pod 自己的 IP**，全程在集群内部。

本文档是从零开始、逐条命令的搭建记录，所有输出都是 **2026-08-27** 在一台真实
的 NVIDIA DGX Spark（GB10 Grace-Blackwell 芯片,aarch64 架构,CPU/GPU 统一内
存架构）上跑出来的真实终端输出，不是事后补写的——包括中间踩的坑和崩溃现场，
因为那部分往往最有参考价值。

English version: [`README.md`](README.md).

---

## 1. 和 `llm-d-gpu-demo` 的区别

| | `llm-d-gpu-demo` | `llm-d-gpu-kind`(本 demo) |
|---|---|---|
| Kind 跑在哪 | Mac(Docker Desktop) | **直接跑在 GPU 主机上**(Linux, DGX Spark) |
| vLLM 跑在哪 | GPU 主机上用 `docker run` 起,**在 Kind 集群外面** | 一个普通的 K8s `Deployment`,**在 Kind 集群里面** |
| EPP 怎么连到 vLLM | 经过一个 2 容器的 `socat` 代理 Pod,通过局域网隧道到外部主机 | 直接连,走 vLLM Pod 自己的集群内 IP |
| GPU 作为 K8s 概念 | 不存在——调度器根本看不到 GPU | `nvidia.com/gpu` 是节点上一个真实的、可调度的资源 |
| 故障恢复 | 手动(要 SSH 到远程主机 `docker restart`) | 自动(kubelet 按重启策略自动拉起) |
| 额外的组件 | `gpu-vllm-proxy` Deployment + PodMonitor | 没有——就一个 Deployment |

代价是:这套方案只在 **Kind 的控制面节点和 GPU 是同一台机器** 时才成立。如果你
的 GPU 和跑 `kind create cluster` 的机器是分开的两台,那还是得退回
`llm-d-gpu-demo` 里那种代理桥接的写法。

## 2. 架构

```
┌─────────────────────────────────────────────────────────────────────┐
│ DGX Spark (192.168.1.112) — Ubuntu 24.04 aarch64, NVIDIA GB10        │
│                                                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Docker daemon (default-runtime = nvidia)                       │  │
│  │                                                                 │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │ Kind 节点容器 "llm-d-gpu-kind-control-plane"              │  │  │
│  │  │ (/dev/nvidia*、驱动库都以 bind-mount 挂进来;               │  │  │
│  │  │  容器里嵌套跑着自己的 containerd + kubelet)                 │  │  │
│  │  │                                                            │  │  │
│  │  │  containerd(注册了 RuntimeClass "nvidia")                  │  │  │
│  │  │   │                                                        │  │  │
│  │  │   ├─ Pod: agentgateway(数据面代理) :80                     │  │  │
│  │  │   │      认识 Gateway API + InferencePool                  │  │  │
│  │  │   │                                                        │  │  │
│  │  │   ├─ Pod: llm-d-epp(2 个容器: epp + vllm-render)           │  │  │
│  │  │   │      :9002 ext_proc gRPC, :9090 metrics                │  │  │
│  │  │   │      直接订阅 vllm-qwen 那个 Pod IP 的 :5556 ZMQ        │  │  │
│  │  │   │                                                        │  │  │
│  │  │   ├─ Pod: vllm-qwen  (runtimeClassName: nvidia)             │  │  │
│  │  │   │      resources.limits: {nvidia.com/gpu: 1}              │  │  │
│  │  │   │      :8000 OpenAI HTTP API, :5556 ZMQ KV-cache 事件      │  │  │
│  │  │   │      ── 真正在 GB10 GPU 上执行推理 ──                    │  │  │
│  │  │   │                                                        │  │  │
│  │  │   └─ DaemonSet: nvidia-device-plugin-daemonset (kube-system)│  │  │
│  │  │          向 kubelet 注册 `nvidia.com/gpu` 这个资源           │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  (这台共享工作机上原本就在跑、与本 demo 无关的东西:                    │
│   llm-d-gpu-demo 的 vllm-gpu-0 容器、ComfyUI、Grafana...)             │
└─────────────────────────────────────────────────────────────────────┘
```

这里有两层容器嵌套,GPU 必须穿透这两层才能真正被 Pod 用到:

1. **宿主机 Docker → Kind 节点容器。** Kind 的"节点"本质上"只是"一个 Docker
   容器。要让它看到 GPU,得靠 Docker 的 `nvidia` runtime 把 `/dev/nvidia*`
   和驱动库注入进去——机制跟 `docker run --gpus all` 完全一样。
2. **containerd(节点容器内部)→ Pod 容器。** Kubernetes 的 Pod 根本不是由宿
   主机的 Docker 起的,而是由节点容器**内部那个嵌套的 containerd** 起的。这
   个嵌套 containerd 需要**它自己单独的一份** `nvidia-container-toolkit`,
   并且自己单独注册 runtime——不做这一步,即使节点容器能看到 GPU,Kind 里
   的 Pod 也永远看不到。

漏掉任意一层,是这类搭建"悄无声息失败"最常见的原因(节点能看到 GPU,Pod 看
不到,或者反过来)。

## 3. 前置条件

| 要求 | 为什么 | 怎么检查 |
|---|---|---|
| Linux 主机 + NVIDIA GPU + 驱动 | Kind 的"节点容器拿到 GPU"这套技巧在 Docker Desktop for Mac/Windows 上不存在——它们的 Linux 虚拟机压根没有 GPU 穿透能力 | `nvidia-smi` |
| 主机上装了 `nvidia-container-toolkit` | 提供 `nvidia-ctk` 命令,以及 Docker/containerd 实际会调用的 `nvidia-container-runtime` | `dpkg -l \| grep nvidia-container-toolkit` |
| 当前用户在 `docker` 组里 | 我们不用 `sudo` 装 kind/kubectl/helm,也不用 `sudo` 跑 `docker`/`kind`/`kubectl` | `docker ps`(不需要 `sudo`) |
| 有 `sudo` 权限 | 有三条**一次性**的主机级配置命令是真的需要 root 权限:改 `/etc/docker/daemon.json`、改 `/etc/nvidia-container-runtime/config.toml`、`systemctl restart docker` | — |
| 主机能访问外网 | 要拉 `kindest/node`、`nvcr.io/nvidia/vllm:26.05-py3`(约 9.5GB)、device-plugin 镜像,还要从 Hugging Face 下模型 | `curl -sS -o /dev/null -w '%{http_code}\n' https://github.com` |

本次实际使用的环境:

```console
$ uname -a
Linux spark 6.14.0-1015-nvidia #15-Ubuntu SMP PREEMPT_DYNAMIC Tue Nov 25 18:02:16 UTC 2025 aarch64 aarch64 aarch64 GNU/Linux
$ docker version --format '{{.Server.Version}}'
28.5.1
$ nvidia-smi --query-gpu=name,driver_version --format=csv
name, driver_version
NVIDIA GB10, 580.126.09
```

> **后面会踩到的 GB10 特殊之处:** 这颗芯片是 CPU/GPU 统一内存架构,所以
> `nvidia-smi --query-gpu=memory.total` 会显示 `[N/A]`,NVML 的
> `nvmlDeviceGetMemoryInfo()` 调用会返回 `Not Supported`。这会让旧版本的
> NVIDIA k8s device plugin 直接崩溃(见步骤 7)。

## 4. 逐步搭建

### 步骤 1 —— 装 kind、kubectl、helm(不用 sudo)

直接装到 DGX Spark 上的 `~/bin`,因为没有 `sudo` 权限写 `/usr/local/bin`:

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

### 步骤 2 —— 给 Docker 配置 GPU 穿透

**这一步真的需要 root**,所以没法直接通过非交互式的 SSH 管道自动跑(`sudo`
要弹密码提示需要一个真实的 tty)。要用 `ssh -t` 强制分配终端来跑:

```console
$ sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
$ sudo sed -i 's/#accept-nvidia-visible-devices-as-volume-mounts = false/accept-nvidia-visible-devices-as-volume-mounts = true/' /etc/nvidia-container-runtime/config.toml
$ sudo systemctl restart docker
```

每一行做了什么:

- `nvidia-ctk runtime configure --runtime=docker --set-as-default` 会写
  `/etc/docker/daemon.json`,让 Docker 知道有个叫 `nvidia` 的 runtime,**并
  且把它设成这台主机上所有新容器的默认 runtime**:
  ```json
  {
      "default-runtime": "nvidia",
      "runtimes": { "nvidia": { "path": "nvidia-container-runtime", "args": [] } }
  }
  ```
  `nvidia-container-runtime` 只是 `runc` 外面薄薄一层包装:对于没有申请 GPU
  的容器,它的行为和纯 `runc` 完全一样,只有在被明确要求时才会注入 GPU 设备
  和驱动库。
- `sed` 那一行打开了 `accept-nvidia-visible-devices-as-volume-mounts`。这是
  下一步能成立的关键机关:**Kind 根本没有 `--gpus` 这个参数**,所以没有常规
  办法告诉 runtime"这个容器要用 GPU"。打开这个开关后,runtime 会把"目标路
  径匹配 `/var/run/nvidia-container-devices/<name>` 的一个 bind-mount",等
  效地当成设置了环境变量 `NVIDIA_VISIBLE_DEVICES=<name>`——而 Kind 的集群
  配置格式**恰好**支持加任意 bind mount(`extraMounts`)。
- `systemctl restart docker` 让新的默认 runtime 生效。

> ### ⚠️ 真实踩坑:这次重启干掉了一个无关的正在运行的容器
>
> 这台 DGX Spark 上本来就有个叫 `vllm-gpu-0` 的容器在跑(`llm-d-gpu-demo`
> 用的那个真实 GPU 后端)。`systemctl restart docker` 并不是"加个配置、容
> 器照常跑着"——Docker 的默认行为(没开 `--live-restore`)是在 daemon 干净
> 关闭时**停掉所有正在运行的容器**,而用纯 `docker run -d`(没加 `--restart`
> 策略)启动的容器,**不会自己重新拉起来**:
> ```console
> $ docker ps -a
> CONTAINER ID   IMAGE                           STATUS                      NAMES
> 5e4f32eba04a   nvcr.io/nvidia/vllm:26.05-py3   Exited (0) 22 seconds ago   vllm-gpu-0
> ```
> 修复方法:`docker start vllm-gpu-0`——但它原来的 `--gpu-memory-utilization
> 0.03` 这次没能成功分配 KV-cache 显存(见下一条踩坑),所以最后还是得用稍
> 大一点的比例重新建了这个容器。**教训:在一台还跑着其他"裸" GPU 容器的主
> 机上执行 `systemctl restart docker` 并不安全——要么提前给那些容器加上
> `--restart=unless-stopped`,要么就做好手动重启它们的准备。**

### 步骤 3 —— 用 GPU bind-mount 这个机关创建 Kind 集群

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

`hostPath: /dev/null` 只是随便找一个保证一定存在的文件,runtime 那个钩子读
的是**目标路径**,源路径内容根本不重要。挂载点的 basename 是 `all`,意思是
"把这台主机上所有 GPU 都暴露出来"。

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

验证 GPU 真的穿透进了节点容器——**注意这时候是 Docker 看到了 GPU,Kubernetes
还完全不知道**:

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

这一步成功的话,`nvidia-ctk` 也会顺带把匹配的驱动库(`libcuda.so`、
`libnvidia-ml.so` 等)和设备节点一起挂进去,不需要额外操作。

### 步骤 4 —— 让"嵌套的" containerd 也支持 GPU

节点容器本身能看到 GPU 了,但 Kubernetes 的 Pod 是由节点容器**内部**那个
containerd 起的——而它就是一个原封不动的 `kindest/node` 镜像,压根没装任何
NVIDIA 相关工具。用节点自己的(可用的)外网,在里面装一遍:

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

然后在**嵌套的** containerd 里注册一个 `nvidia` runtime handler(故意**不**
设为默认——只有明确声明 `runtimeClassName: nvidia` 的 Pod 才应该拿到 GPU 注
入):

```console
$ docker exec llm-d-gpu-kind-control-plane nvidia-ctk runtime configure --runtime=containerd --config=/etc/containerd/config.toml
INFO[...] Wrote updated config to /etc/containerd/conf.d/99-nvidia.toml
INFO[...] It is recommended that containerd daemon be restarted.
```

> containerd 2.x 支持在 `/etc/containerd/conf.d/` 下放"drop-in"配置文件
> (主配置里的 `imports = ["/etc/containerd/conf.d/*.toml"]` 会自动导入它
> 们)——`nvidia-ctk` 选择写到这里,而不是直接改 `config.toml`。两种方式效
> 果一样,drop-in 这种写法反而更干净。

```console
$ docker exec llm-d-gpu-kind-control-plane systemctl restart containerd
$ docker exec llm-d-gpu-kind-control-plane systemctl is-active containerd
active
$ kubectl get nodes
NAME                           STATUS   ROLES           AGE   VERSION
llm-d-gpu-kind-control-plane   Ready    control-plane   20s   v1.35.0
```

节点在 containerd 重启前后一直保持 `Ready`——kubelet 自己重新连上了。

现在用一个 `RuntimeClass` 告诉 Kubernetes 这个 runtime 的存在:

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

### 步骤 5 —— 部署 NVIDIA device plugin(顺带踩到 GB10 的 bug)

device plugin 的作用是把"containerd 能在这块 GPU 上起 Pod"变成"调度器认识
`nvidia.com/gpu` 这个资源"。第一次尝试,用了一个相对新但不是最新的镜像 tag:

```console
$ kubectl apply -f manifests/nvidia-device-plugin.yaml   # 这时候用的是 v0.17.1
$ kubectl -n kube-system logs -l name=nvidia-device-plugin-ds --tail 5
E... error visiting device: error building Device: error getting device memory: Not Supported
```

正是 §3 提到的 GB10 统一内存的坑:插件调用 `nvmlDeviceGetMemoryInfo()` 来
构建内部的设备映射表,GB10 因为没有独立显存可报告而返回 `Not Supported`,
v0.17.1 把这个当成致命错误处理。这是一个
[已知且已修复的问题](https://github.com/NVIDIA/k8s-device-plugin/issues/1482)——
**v0.17.4 及以后的版本会容忍这个 `Not Supported` 响应。** 把镜像 tag 升级:

```console
$ kubectl apply -f manifests/nvidia-device-plugin.yaml   # 现在是 v0.17.4
$ kubectl -n kube-system logs -l name=nvidia-device-plugin-ds --tail 5
W... devices.go:77] Ignoring error getting device memory: Not Supported
I... server.go:195] Starting GRPC server for 'nvidia.com/gpu'
I... server.go:146] Registered device plugin for 'nvidia.com/gpu' with Kubelet
```

验证节点现在真的对外声明了一个 GPU 资源:

```console
$ kubectl get node llm-d-gpu-kind-control-plane -o jsonpath='{.status.allocatable}' | tr ',' '\n' | grep gpu
"nvidia.com/gpu":"1"
```

用一个最简单的冒烟测试 Pod 端到端验证一遍——还完全没涉及 llm-d,只是验证
"一个申请了 `nvidia.com/gpu: 1` 的 Pod,是不是真的能在真实 GPU 上跑
`nvidia-smi`":

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

**这是整个 demo 的核心里程碑**:一个普通的 `kubectl apply` 出来的 Pod,因为
申请了 `nvidia.com/gpu: 1` 而被默认调度器排上了这块真实的 GPU,在上面跑了真
代码。不需要代理,不需要外部主机,也不需要手动 `docker run`。

### 步骤 6 —— 命名空间、CRD、agentgateway、Gateway

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

这三条命令依次安装的是:**Gateway API**(`GatewayClass`、`Gateway`、
`HTTPRoute`——Kubernetes 的"下一代 Ingress");**Gateway API Inference
Extension / GAIE**(`InferencePool`——专门表示"一组模型服务副本"的资源类
型,是 EPP 要监听的对象);**llm-d 自己的 CRD**(`InferenceObjective`、
`InferenceModelRewrite`)。

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

`--set inferenceExtension.enabled=true` 是那个开关——打开后 agentgateway 才
会原生监听 `InferencePool` 资源,并知道怎么去调用一个 EPP 的 `ext_proc` 接
口;不打开的话就得自己手写一条 `AgentgatewayPolicy` 来接线。

### 步骤 7 —— 把 vLLM 部署成原生的 GPU Deployment

这一步完全替代了 `llm-d-gpu-demo` 里那整个 `gpu-vllm-proxy` Deployment。完
整清单见 [`manifests/vllm-gpu-native.yaml`](manifests/vllm-gpu-native.yaml),
关键部分:

```yaml
spec:
  template:
    metadata:
      labels:
        llm-d.ai/role: decode
        llm-d.ai/guide: gpu-kind-native   # <- EPP 的 selector 靠这个匹配
        llm-d.ai/model: Qwen2.5-1.5B-Instruct
    spec:
      serviceAccountName: sa
      runtimeClassName: nvidia            # <- 声明要用 GPU 注入
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
            limits: { nvidia.com/gpu: 1 }   # <- 这就是全部的关机
```

```console
$ kubectl apply -f manifests/vllm-gpu-native.yaml
deployment.apps/vllm-qwen created
$ kubectl -n llm-d get pods -l llm-d.ai/guide=gpu-kind-native
NAME                        READY   STATUS              RESTARTS   AGE
vllm-qwen-66c85c6f4-hfbgd   0/1     ContainerCreating   0          0s
```

> ### ⚠️ 真实踩坑 1:冷拉镜像要花好几分钟
>
> Kind 嵌套的 containerd 有**自己独立的镜像存储**,和宿主机 Docker 的镜像缓
> 存完全是两码事——即便 `vllm-gpu-0` 在 Kind 之外已经拉过这个镜像,集群内
> 的这个 Pod 还是得把全部 9.5GB 重新拉一遍:
> ```console
> Normal  Pulling  kubelet  spec.containers{vllm}: Pulling image "nvcr.io/nvidia/vllm:26.05-py3"
> Normal  Pulled   kubelet  Successfully pulled image ... in 2m58.136s. Image size: 9486739495 bytes.
> ```
>
> ### ⚠️ 真实踩坑 2:Pod 崩了一次,然后自己好了
> ```console
> $ kubectl -n llm-d get pods -l llm-d.ai/guide=gpu-kind-native
> NAME                        READY   STATUS    RESTARTS      AGE
> vllm-qwen-66c85c6f4-hfbgd   0/1     Running   1 (42s ago)   4m
> ```
> 第一次尝试踩到了和上面 `vllm-gpu-0` 那次一样的 KV-cache 显存分配错误
> (`ValueError: No available memory for the cache blocks`)——不意外,因为
> 这块 GPU 此刻同时被第二个 vLLM 引擎和宿主机上的 ComfyUI 会话共享着。**这
> 次没有人手动 `docker start`——kubelet 按默认重启策略自己把容器拉起来
> 了,第二次直接就成功了。** 这正是本 demo 起源的那个概念性讨论
> ("Kubernetes 管理容器的生命周期")在实际操作层面的具体体现。

```console
$ kubectl -n llm-d wait --for=condition=Ready pod -l llm-d.ai/guide=gpu-kind-native --timeout=900s
pod/vllm-qwen-66c85c6f4-hfbgd condition met
$ kubectl -n llm-d get pods -l llm-d.ai/guide=gpu-kind-native
NAME                        READY   STATUS    RESTARTS      AGE
vllm-qwen-66c85c6f4-hfbgd   1/1     Running   1 (93s ago)   4m51s
```

### 步骤 8 —— 安装路由层(EPP + InferencePool)

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

`helm-values/gw-kind-gpu.values.yaml` 里设置了
`router.modelServers.matchLabels: {llm-d.ai/guide: gpu-kind-native}`——就这
一行,是 EPP 和真实 vLLM Pod 之间**全部**的连接点;其余所有路由逻辑(打分、
KV-cache 感知)都是通用的,根本不知道也不关心这次的后端恰好是块真实 GPU。

```console
$ kubectl -n llm-d get pods
NAME                                       READY   STATUS    RESTARTS      AGE
llm-d-epp-7c8c9f5b8d-tf7sm                 2/2     Running   0             5m17s
llm-d-inference-gateway-86b846c879-4dcjb   1/1     Running   0             6m20s
vllm-qwen-66c85c6f4-hfbgd                  1/1     Running   1 (2m ago)    5m57s
```

**整个 demo 里最重要的一行日志**——证明代理这一层是真的彻底消失了:

```console
$ kubectl -n llm-d logs deploy/llm-d-epp -c epp | grep zmq
{"logger":"zmq-subscriber","msg":"Connected subscriber socket","endpoint":"tcp://10.244.0.10:5556"}
```

`10.244.0.10` 就是 `vllm-qwen` 这个 Pod 自己的 IP。对比 `llm-d-gpu-demo`
里,同样这行日志指向的是 `gpu-vllm-proxy` 那个 Pod 的 IP,再由它转发到局域
网里完全另一台机器上。

### 步骤 9 —— 通过 Gateway 做端到端测试

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

一个真正的补全结果,来自真实 GPU,走完了完整的 Gateway → EPP →
InferencePool → Pod 这条链路,而这个集群里唯一"非标准"的地方,只有一个
Deployment 上的 `runtimeClassName: nvidia`。

对应的 EPP 端日志——同一个请求,`x-request-id` 和上面 `chatcmpl-...` 的 id
对得上:

```console
$ kubectl -n llm-d logs deploy/llm-d-epp -c epp --tail 30 | grep prefix
{"logger":"prefix","msg":"PrefixCacheMatchInfo not found for endpoints, assigning score 0",
 "x-request-id":"e343c7b9-7fc3-428c-a36f-7145163e22b7","incomingModelName":"Qwen/Qwen2.5-1.5B-Instruct"}
```

(打分是 0,因为这是第一个请求——KV-cache 索引里还什么都没有。如果第二个请
求的 prompt 前缀和第一个有重叠,打分就会大于 0;不过本 demo 里只有一个后端
Pod,打分再高也改变不了"选哪个 Pod"这个结果——但一旦扩到 N 个副本,驱动真
实路由决策的就是这同一套机制。)

确认此刻这块 GPU 上同时活着两个 vLLM 引擎(本 demo 的 `vllm-qwen` + 旧
`llm-d-gpu-demo` 的 `vllm-gpu-0`,后者完全没被打扰,一直在跑):

```console
$ nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
pid, process_name, used_gpu_memory [MiB]
3858903, VLLM::EngineCore, 6265 MiB
3880364, VLLM::EngineCore, 5530 MiB
```

节点的资源记账现在把 GPU 当成和其他资源完全一样的东西来对待:

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

## 5. 每个组件/CR 到底是什么

| 资源 | 类型 | 命名空间 | 在这里的含义 |
|---|---|---|---|
| `RuntimeClass/nvidia` | K8s 内置类型 | 集群级 | 指向一个 containerd runtime handler 的命名指针。任何 Pod 只要设置 `spec.runtimeClassName: nvidia`,它的容器就会用 `nvidia-container-runtime`(而不是普通的 `runc`)来创建——真正把 `/dev/nvidia*` 和驱动库注入到这个容器里的正是这一步。节点上其他一切不受影响(`default_runtime_name` 仍然是 `runc`)。 |
| `DaemonSet/nvidia-device-plugin-daemonset` | `apps/v1` | `kube-system` | 每个节点一个 Pod;通过 NVML 枚举物理 GPU,并通过一个 Unix socket(`/var/lib/kubelet/device-plugins/`)向 kubelet 注册 `nvidia.com/gpu` 这个资源。没有这个组件,Pod spec 里写的 `nvidia.com/gpu` 对调度器来说毫无意义——直接调度失败("Insufficient nvidia.com/gpu")。 |
| `GatewayClass/agentgateway` | Gateway API | 集群级 | 声明"存在一个叫 `agentgateway.dev/agentgateway` 的控制器,能实现引用这个 class 的 `Gateway` 资源"。类比存储领域的 `StorageClass`。 |
| `Gateway/llm-d-inference-gateway` | Gateway API | `llm-d` | 真正的监听器(这里是 80 端口),agentgateway 会把它编译进数据面代理的实际配置。`status.conditions[Programmed]=True` 意味着代理配置真的生成并生效了,而不只是这个对象被 API server 接受了而已。 |
| `HTTPRoute/llm-d` | Gateway API | `llm-d` | 把上面那个 `Gateway` 上的一个路径前缀(`/`)绑定到一个 `backendRef`——而这个 backend 不是普通 `Service`,而是一个 `InferencePool`(见下一行)。这正是"通用 HTTP 网关"变成"推理感知网关"的扩展点。 |
| `InferencePool/llm-d` | Gateway API Inference Extension | `llm-d` | llm-d 的核心抽象:"同一个模型的一组可互换的模型服务副本",通过 `spec.selector.matchLabels`(这里是 `llm-d.ai/guide: gpu-kind-native`)来标识——**这是一个 Pod 标签选择器,实时对着 Kubernetes 的 Pod API 求值,从来不经过 Service 的 VIP。** `spec.endpointPickerRef` 指向 EPP 的 Service:端口,由它来决定每个请求具体交给选中集合里的哪个 Pod。 |
| `Deployment/llm-d-epp` | `apps/v1` | `llm-d` | Endpoint Picker(EPP)——一个 2 容器的 Pod(`epp` + `vllm-render` 分词器 sidecar)。实现了 agentgateway 每个请求都会调用的 `ext_proc` gRPC 协议;按配置好的插件链(见第 6 节)从 `InferencePool` 当前的成员集合里挑出目标 Pod IP。 |
| `Deployment/vllm-qwen` | `apps/v1` | `llm-d` | 模型服务本体。唯一和 GPU 相关的字段就是 `spec.template.spec.runtimeClassName: nvidia` 和 `resources.limits.{nvidia.com/gpu: 1}`——其余部分就是一个彻头彻尾普通的 Deployment。 |
| `Secret/llm-d-hf-token` | 核心 `v1` | `llm-d` | 一个(对公开模型来说是空的)Hugging Face token。EPP 的 `vllm-render` sidecar 容器在 chart 模板里无条件引用了这个环境变量;不建这个 Secret 的话 Pod 会报 `CreateContainerConfigError`,即便这个 token 对公开模型根本用不上。 |
| `ServiceAccount/sa` | 核心 `v1` | `llm-d` | 工作负载 Pod 运行时使用的身份;设了 `automountServiceAccountToken: false`,因为本 demo 里没有任何 Pod 内部代码需要调用 Kubernetes API。 |

## 6. 请求流程详解

对照步骤 9 里那次 `curl` 测试,按顺序编号:

1. **客户端 → Gateway Service。** `curl` 打到 `llm-d-inference-gateway` 的
   `ClusterIP:80`。这是一个普通的 L4、`LoadBalancer` 类型的 Service(在
   Kind 里外部 IP 一直是 pending 状态,没关系,我们直接打的是 ClusterIP),
   它的 Endpoints 指向 `agentgateway` 那个数据面 Pod。
2. **agentgateway 匹配 `HTTPRoute`。** 这个 `Gateway` 上路径 `/` 匹配到
   `HTTPRoute/llm-d` 这条规则,它的 `backendRef` 是 `InferencePool/llm-d`,
   而不是一个普通 Service。
3. **agentgateway 在转发之前,先通过 `ext_proc`(gRPC)调用 EPP。** 因为安
   装时设置了 `inferenceExtension.enabled=true`,agentgateway 知道
   "backend 是 `InferencePool`"意味着"要问这个 EPP 该用哪个 Pod",而不是
   "在 Service 的 Endpoints 之间做负载均衡"。
4. **EPP 解析池子里的成员。** 它持续监听 Kubernetes 的 Pod API,找匹配
   `InferencePool.spec.selector`(`llm-d.ai/guide: gpu-kind-native`)的
   Pod——此刻正好只有一个,就是 `vllm-qwen` 这个 Pod。
5. **EPP 跑打分插件链**(配置在
   `helm-values/precise-prefix-router.values.yaml` 里):
   - `token-producer`——通过 `vllm-render` sidecar 对输入 prompt 做分词,
     让后面的插件能按真实 token 数量而不是字符数来判断。
   - `precise-prefix-cache-producer`——维护一份"每个 Pod 上,vLLM 引擎当前
     持有哪些 64-token KV-cache 块"的索引,**索引数据来自 vLLM 在 5556 端
     口发布的真实 ZMQ 事件**(这正是步骤 8 里那条直接连到 `vllm-qwen` Pod
     IP、不经过任何代理的订阅连接)。
   - `prefix-cache-scorer`(权重 3.0)、`kv-cache-utilization-scorer`(权
     重 2.0)、`queue-scorer`(权重 2.0)——给每个候选 Pod 打分;
     `max-score-picker` 选出得分最高的那个。
6. **EPP 通过同一次 `ext_proc` 调用,把选中 Pod 的 IP:端口返回给
   agentgateway。**
7. **agentgateway 把原始 HTTP 请求直接代理到 `vllm-qwen` 的 Pod IP**(本次
   运行是 `10.244.0.10:8000`)——一次普通的集群内 L3/L4 跳转,不再经过任何
   中间层。
8. **vLLM 在真实的 GB10 GPU 上执行这个请求**,流式返回一个 OpenAI 兼容的响
   应,原路返回给客户端。
9. **旁路、持续发生的事情:** vLLM 每次分配或回收一个 KV-cache 块,都会在
   5556 端口通过 ZMQ 发布一条"块新增/移除"事件;EPP 的
   `precise-prefix-cache-producer` 独立消费这些事件,与任何具体请求无关,
   持续保持索引最新——这样*下一个*请求的 `prefix-cache-scorer` 打分才是准
   的。

## 7. 清理

```console
$ kind delete cluster --name llm-d-gpu-kind
```

一条命令删掉整个集群(所有 Pod、节点容器、里面的 containerd/kubelet,全
部)。它**不会**动宿主机上的 `/etc/docker/daemon.json` 或
`/etc/nvidia-container-runtime/config.toml`——如果想把 Docker 的默认
runtime 改回 `runc`,需要手动改这两个文件再 `sudo systemctl restart
docker`(记得这次重启同样会停掉那些"裸"跑的容器,和步骤 2 一样)。

## 8. 已知限制

- **只支持单节点。** 多节点的 Kind-on-GPU 需要在每个节点上重复一遍同样的
  GPU 穿透配置,而且只有每个节点都有自己独立的物理 GPU 时才有意义。
- **GPU 显存是共享的、会变化的。** 这台 DGX Spark 的统一内存和主机上其他
  GPU 工作负载共享(本次搭建全程还有两个 ComfyUI 进程和旧
  `llm-d-gpu-demo` 的 `vllm-gpu-0` 在跑);今天能用的
  `--gpu-memory-utilization` 值,明天不一定还够用。看到
  `ValueError: No available memory for the cache blocks` 就调高这个值。
- **两层容器嵌套需要保持同步。** 如果以后重新创建节点(比如升级 Docker 后
  `kind delete && kind create`),步骤 4-5(在节点**内部**装
  `nvidia-container-toolkit`、注册 `RuntimeClass`)都要重新做一遍——它们
  不是原版 `kindest/node` 镜像自带的。
- **本 demo 没有做自动扩缩容、链路追踪、P/D 分离** ——这些和"Kind 是不是
  跑在 GPU 主机上"这个问题是正交的,`llm-d-gpu-demo` 里的 WVA/HPA、Jaeger、
  P/D 章节已经分别覆盖过了。
