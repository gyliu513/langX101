# 在 DGX Spark 上用 kind 测试 NVIDIA DRA（以及 Kueue + DRA）

[English version](README_EN.md)

本文在一台 **NVIDIA DGX Spark（GB10，arm64）** 上用 **kind** 搭一个 Kubernetes 集群，装上
**NVIDIA DRA Driver for GPUs**，用 5 个例子演示 DRA（Dynamic Resource Allocation，动态资源分配）
如何把 GPU 分配给 Pod。然后再装 **Kueue**，验证 Kueue 对 DRA 的支持，并给出 Kueue + DRA 结合的例子。

文中所有命令都是 2026-11-16 在这台 Spark 上真实运行的，输出也是原样粘贴的（太长的地方用 `...` 截断）。

## 目录

- [1. 背景：DRA 是什么，和 device plugin 有什么不同](#1-背景dra-是什么和-device-plugin-有什么不同)
- [2. 测试环境与版本](#2-测试环境与版本)
- [3. 目录结构](#3-目录结构)
- [4. 第 0 步：检查宿主机](#4-第-0-步检查宿主机)
- [5. 第 1 步：创建 kind 集群并把 GPU 传进节点](#5-第-1-步创建-kind-集群并把-gpu-传进节点)
- [6. 第 2 步：安装 NVIDIA DRA Driver](#6-第-2-步安装-nvidia-dra-driver)
- [7. 第 3 步：DRA 单独测试（例 1–5）](#7-第-3-步dra-单独测试例-15)
- [8. 第 4 步：Kueue 支持 DRA 吗？](#8-第-4-步kueue-支持-dra-吗)
- [9. 第 5 步：安装 Kueue 并开启 DRA 映射](#9-第-5-步安装-kueue-并开启-dra-映射)
- [10. 第 6 步：Kueue + DRA 例子（例 6–9）](#10-第-6-步kueue--dra-例子例-69)
- [11. 踩坑记录与发现](#11-踩坑记录与发现)
- [12. 清理](#12-清理)
- [13. 参考资料](#13-参考资料)

## 1. 背景：DRA 是什么，和 device plugin 有什么不同

传统做法是 **device plugin**：节点上报一个整数资源（如 `nvidia.com/gpu: 1`），Pod 在
`resources.limits` 里写一个数字。调度器只知道"数量"，不知道 GPU 型号、算力版本、是否要共享等。

**DRA**（Kubernetes 1.34 GA，API 组 `resource.k8s.io/v1`）把 GPU 当成带属性的"设备"来管理：

| 对象 | 谁创建 | 作用 |
|---|---|---|
| `DeviceClass` | 驱动（Helm chart） | 一类设备，比如 `gpu.nvidia.com` |
| `ResourceSlice` | 驱动的 kubelet plugin | 每个节点上有哪些设备，以及每个设备的属性（型号、架构、UUID、CUDA 版本…） |
| `ResourceClaim` | 用户 / 调度器 | "我要一个满足某些条件的设备"，分配结果写在 `status.allocation` 里 |
| `ResourceClaimTemplate` | 用户 | 每个 Pod 自动生成一个独立的 ResourceClaim（Pod 删了 claim 也删） |

整个流程：

```
              ┌─────────────── kube-scheduler ───────────────┐
 Pod ──refs──▶│ ResourceClaim(Template)  +  ResourceSlice     │──▶ 写入 claim.status.allocation
              │ (CEL 选择器 / 数量 / DeviceClass)            │    （选中哪个节点上的哪块 GPU）
              └───────────────────────────────────────────────┘
                                   │ Pod 绑定到节点
                                   ▼
 kubelet ──NodePrepareResources──▶ NVIDIA DRA kubelet plugin (gpu.nvidia.com)
                                   │ 应用 GpuConfig（时间片 / MPS …），生成 CDI spec
                                   ▼
 containerd ──CDI 设备名──▶ 把 /dev/nvidia* 和驱动库注入容器
```

和 device plugin 相比，DRA 多了：按属性选设备（CEL 表达式）、多个 Pod / 容器共享同一个 claim、
驱动特有的配置（时间片、MPS、MIG），还有 claim 的生命周期管理。

## 2. 测试环境与版本

| 组件 | 版本 |
|---|---|
| 硬件 | NVIDIA DGX Spark（`spark-3bee`），1 × GB10（Blackwell，算力 12.1，128 GB 统一内存），aarch64 |
| OS / 驱动 | Ubuntu 24.04.5，NVIDIA 驱动 580.173.02，CUDA 13.0 |
| 容器 | Docker 29.2.1（默认 runtime = `nvidia`），NVIDIA Container Toolkit 1.20.0 |
| kind | v0.33.0，节点镜像 `kindest/node:v1.37.0`（containerd 2.3.4） |
| kubectl / helm | v1.37.0 / v3.22.0 |
| NVIDIA DRA Driver | **v0.5.1**（`oci://registry.k8s.io/dra-driver-nvidia/charts/dra-driver-nvidia-gpu`，镜像支持 arm64） |
| Kueue | **v0.20.6**（2026-11-12 发布，当前最新） |

> 说明：NVIDIA DRA driver 项目已经迁到 `kubernetes-sigs/dra-driver-nvidia-gpu`，版本号也从
> `v25.x` 改成了 `v0.x`。镜像和 chart 现在都发布在 `registry.k8s.io/dra-driver-nvidia/` 下面。

## 3. 目录结构

```
nvidia/dra/
├── README.md / README_EN.md            # 本文（中文 / 英文）
├── kind/
│   ├── kind-config.yaml                # kind 集群：1 control-plane + 1 带 GPU 的 worker
│   └── dra-driver-values.yaml          # DRA driver 的 Helm values
├── manifests/                          # DRA 单独测试
│   ├── 00-namespace.yaml
│   ├── 01-single-gpu-claim-template.yaml   # 例 1：ResourceClaimTemplate，一个 Pod 一块 GPU
│   ├── 02-exclusive-two-pods.yaml          # 例 2：两个 Pod 各要一块 GPU（独占，第二个 Pending）
│   ├── 03-shared-claim.yaml                # 例 3：两个 Pod 共享同一个 ResourceClaim
│   ├── 04-cel-selector.yaml                # 例 4：CEL 按属性选 GPU
│   └── 05-time-slicing.yaml                # 例 5：GpuConfig 时间片共享
├── kueue/                              # Kueue + DRA
│   ├── controller_manager_config.yaml      # Kueue 配置（默认配置 + deviceClassMappings）
│   ├── 10-queues.yaml                      # ResourceFlavor / ClusterQueue / LocalQueue / 模板
│   ├── 11-gpu-jobs.yaml                    # 例 6：两个 Job 抢 1 块 GPU 的配额
│   ├── 12-too-big-job.yaml                 # 例 7：一个 Job 要 2 块 GPU（超过配额）
│   ├── 13-direct-claim-job.yaml            # 例 8：直接引用 ResourceClaim（Kueue 不支持）
│   └── 14-extended-resource.yaml           # 例 9：用 nvidia.com/gpu 扩展资源写法走 DRA
└── scripts/
    ├── setup.sh                        # 一键：建集群 + 装 driver + 装 Kueue
    └── cleanup.sh                      # 删除集群并检查 GPU 状态
```

下面所有命令都在 Spark 上、`~/nvidia-dra-demo`（即本目录的拷贝）里执行：

```console
gyliu-cary@gyliu513-MacBook-Pro-2 dra % rsync -a ./ mygpu:~/nvidia-dra-demo/
```

## 4. 第 0 步：检查宿主机

DRA driver 通过宿主机的 NVIDIA 驱动和 NVIDIA Container Toolkit 工作。先确认架构、GPU、驱动：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ uname -m; lsb_release -ds
aarch64
Ubuntu 24.04.5 LTS

gyliu@spark-3bee:~/nvidia-dra-demo$ nvidia-smi
Mon Nov 16 22:09:31 2026
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.173.02             Driver Version: 580.173.02     CUDA Version: 13.0     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GB10                    On  |   0000000F:01:00.0 Off |                  N/A |
| N/A   39C    P0              9W /  N/A  | Not Supported          |      0%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A            2401      C   ...yliu/ComfyUI/.venv/bin/python      40979MiB |
+-----------------------------------------------------------------------------------------+

gyliu@spark-3bee:~/nvidia-dra-demo$ nvidia-smi --query-gpu=name,compute_cap,driver_version,compute_mode --format=csv
name, compute_cap, driver_version, compute_mode
NVIDIA GB10, 12.1, 580.173.02, Default
```

> GB10 是统一内存架构，`nvidia-smi` 的显存一栏显示 `Not Supported`。上面看到有一个 ComfyUI
> 进程占了约 40 GB 统一内存，本文的测试负载都很小（`nvidia-smi`、vectorAdd、nbody），可以和它共存。

Docker 的默认 runtime 必须是 `nvidia`，并且 `accept-nvidia-visible-devices-as-volume-mounts = true`。
kind 没有 `--gpus` 参数，我们靠这个开关，用一个 bind mount 把 GPU 传进 kind 节点容器（见下一步）：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ docker info --format "Server: {{.ServerVersion}}  DefaultRuntime: {{.DefaultRuntime}}  CgroupDriver: {{.CgroupDriver}}"
Server: 29.2.1  DefaultRuntime: nvidia  CgroupDriver: systemd

gyliu@spark-3bee:~/nvidia-dra-demo$ nvidia-ctk --version
NVIDIA Container Toolkit CLI version 1.20.0
commit: 5505e2f94d9aaa08561490db974ba3cd676af209

gyliu@spark-3bee:~/nvidia-dra-demo$ grep -E "^accept-nvidia-visible-devices-as-volume-mounts" /etc/nvidia-container-runtime/config.toml
accept-nvidia-visible-devices-as-volume-mounts = true
```

如果这两项不对，可以这样改（会重启 Docker，所有容器都会重启）：

```bash
sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
sudo nvidia-ctk config --set accept-nvidia-visible-devices-as-volume-mounts=true --in-place
sudo systemctl restart docker
```

kind / kubectl / helm 装在 `~/bin` 下（安装方法见 [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation)、
[kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/)、[helm](https://helm.sh/docs/intro/install/)，
记得下载 `linux/arm64` 版本；helm 用 v3，不要用 v4）：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kind version; kubectl version --client; helm version --short
kind v0.33.0 go1.26.7 linux/arm64
Client Version: v1.37.0
Kustomize Version: v5.8.1
v3.22.0+g144ca65
```

## 5. 第 1 步：创建 kind 集群并把 GPU 传进节点

kind 配置（[kind/kind-config.yaml](kind/kind-config.yaml)）。它基于上游
`demo/clusters/kind/scripts/kind-cluster-config.yaml`，为单 GPU 的 Spark 做了精简：

```yaml
# kind/kind-config.yaml
# kind cluster for testing the NVIDIA DRA driver on a DGX Spark (GB10, arm64).
# Based on upstream demo/clusters/kind/scripts/kind-cluster-config.yaml
# (kubernetes-sigs/dra-driver-nvidia-gpu v0.5.1), trimmed for a single-GPU host.
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: dra
# Kubernetes >= 1.34 serves resource.k8s.io/v1 (DRA GA) by default, so no
# featureGates / runtime-config are needed here.
containerdConfigPatches:
# Let containerd inside the kind node resolve CDI device names
# (the DRA kubelet plugin hands containerd CDI device IDs).
- |-
  [plugins."io.containerd.cri.v1.runtime"]
    enable_cdi = true
    cdi_spec_dirs = ["/etc/cdi", "/var/run/cdi"]
nodes:
- role: control-plane
- role: worker
  labels:
    nvidia.com/gpu.present: "true"
  extraMounts:
  # Inject the host GPU (device nodes + driver libraries) into this kind node.
  # Requires `accept-nvidia-visible-devices-as-volume-mounts = true` in
  # /etc/nvidia-container-runtime/config.toml and Docker's default runtime = nvidia.
  # The hostPath is irrelevant; the containerPath name selects the GPU(s).
  - hostPath: /dev/null
    containerPath: /var/run/nvidia-container-devices/cdi/runtime.nvidia.com/gpu/all
  # The CDI spec the DRA driver generates calls `nvidia-ctk hook ...`;
  # kind nodes don't ship nvidia-ctk, so borrow the host binary.
  - hostPath: /usr/bin/nvidia-ctk
    containerPath: /usr/bin/nvidia-ctk
```

要点：

1. **不需要 feature gate**：Kubernetes 1.34 起 DRA 已经 GA，`resource.k8s.io/v1` 默认开启。上游 demo 里的
   `featureGates: DynamicResourceAllocation` 和 `runtime-config: resource.k8s.io/v1beta1` 是给老版本用的。
2. **`enable_cdi = true`**：DRA kubelet plugin 返回给 kubelet 的是 CDI 设备名
   （如 `k8s.gpu.nvidia.com/claim=<uid>-gpu-0`），containerd 要开 CDI 才能把它解析成设备节点和挂载。
   containerd 2.x 的插件名是 `io.containerd.cri.v1.runtime`（1.x 是 `io.containerd.grpc.v1.cri`）。
3. **GPU 注入**：`containerPath: /var/run/nvidia-container-devices/cdi/runtime.nvidia.com/gpu/all` 这个挂载会让
   nvidia runtime 把宿主机全部 GPU（设备节点 + 驱动库 + `nvidia-smi`）注入 `dra-worker` 节点容器。
   只给 worker 注入，control-plane 不需要 GPU。
4. **挂载 `nvidia-ctk`**：driver 生成的 CDI spec 里有 `nvidia-ctk hook ...`，kind 节点镜像里没有这个二进制。
5. 上游配置里的 `/run/nvidia-fabricmanager/socket`、`/dev/vfio` 挂载在 Spark 上用不到（没有 NVSwitch / VFIO），已删掉。

创建集群：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kind create cluster --config kind/kind-config.yaml 2>&1 | grep -v "^ •"
Creating cluster "dra" ...
 ✓ Ensuring node image (kindest/node:v1.37.0) 🖼️
 ✓ Preparing nodes 📦 📦
 ✓ Writing configuration 📜
 ✓ Starting control-plane 🕹️
 ✓ Installing CNI 🔌
 ✓ Installing StorageClass 💾
 ✓ Joining worker nodes 🚜
Set kubectl context to "kind-dra"
You can now use your cluster with:

kubectl cluster-info --context kind-dra

Have a question, bug, or feature request? Let us know! https://kind.sigs.k8s.io/#community 🙂

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl get nodes -o wide
NAME                STATUS     ROLES           AGE   VERSION   INTERNAL-IP   EXTERNAL-IP   OS-IMAGE                       KERNEL-VERSION               CONTAINER-RUNTIME
dra-control-plane   NotReady   control-plane   15s   v1.37.0   172.18.0.2    <none>        Debian GNU/Linux 13 (trixie)   6.17.0-1032-nvidia (arm64)   containerd://2.3.4
dra-worker          NotReady   <none>          1s    v1.37.0   172.18.0.3    <none>        Debian GNU/Linux 13 (trixie)   6.17.0-1032-nvidia (arm64)   containerd://2.3.4
```

确认 worker 节点容器里能看到 GPU、设备节点、`nvidia-ctk`，containerd 已开启 CDI：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ docker exec dra-worker nvidia-smi -L
GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)

gyliu@spark-3bee:~/nvidia-dra-demo$ docker exec dra-worker ls /dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm /usr/bin/nvidia-ctk
/dev/nvidia-uvm
/dev/nvidia0
/dev/nvidiactl
/usr/bin/nvidia-ctk

gyliu@spark-3bee:~/nvidia-dra-demo$ docker exec dra-worker grep -B1 -A2 enable_cdi /etc/containerd/config.toml
    cdi_spec_dirs = ["/etc/cdi", "/var/run/cdi"]
    enable_cdi = true
  [plugins."io.containerd.grpc.v1.cri"]
    restrict_oom_score_adj = false
```

确认 DRA API 可用，相关 feature gate 已开启（`stage=""` 表示 GA）：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl api-resources --api-group=resource.k8s.io
NAME                     SHORTNAMES   APIVERSION           NAMESPACED   KIND
deviceclasses                         resource.k8s.io/v1   false        DeviceClass
devicetaintrules                      resource.k8s.io/v1   false        DeviceTaintRule
resourceclaims                        resource.k8s.io/v1   true         ResourceClaim
resourceclaimtemplates                resource.k8s.io/v1   true         ResourceClaimTemplate
resourceslices                        resource.k8s.io/v1   false        ResourceSlice

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl get --raw /metrics | grep -E "kubernetes_feature_enabled\{name=\"(DynamicResourceAllocation|DRAExtendedResource|DRAPrioritizedList|DRAPartitionableDevices|DRAConsumableCapacity)\""
kubernetes_feature_enabled{name="DRAConsumableCapacity",stage="BETA"} 1
kubernetes_feature_enabled{name="DRAExtendedResource",stage=""} 1
kubernetes_feature_enabled{name="DRAPartitionableDevices",stage="BETA"} 1
kubernetes_feature_enabled{name="DRAPrioritizedList",stage=""} 1
kubernetes_feature_enabled{name="DynamicResourceAllocation",stage=""} 1
```

## 6. 第 2 步：安装 NVIDIA DRA Driver

Helm values（[kind/dra-driver-values.yaml](kind/dra-driver-values.yaml)）：

```yaml
# kind/dra-driver-values.yaml
# Helm values for dra-driver-nvidia-gpu v0.5.1 on a single DGX Spark (GB10).
# GPU allocation is still marked "not officially supported" upstream, so the
# chart refuses to enable it unless this override is set.
gpuResourcesEnabledOverride: true
resources:
  gpus:
    enabled: true
  # ComputeDomains = Multi-Node NVLink (IMEX). A single Spark has no MNNVL
  # fabric, so turn this part off.
  computeDomains:
    enabled: false
featureGates:
  # Needed for GpuConfig.sharing.strategy=TimeSlicing (example 5).
  TimeSlicingSettings: true
```

- `gpuResourcesEnabledOverride: true`：上游目前把"GPU 分配"标为尚未正式支持（ComputeDomain 部分是正式支持的），
  不加这个开关 chart 不会启用 GPU kubelet plugin。
- `computeDomains.enabled: false`：ComputeDomain 用于多节点 NVLink（IMEX），单台 Spark 用不上。
- `TimeSlicingSettings: true`：例 5 要用 `GpuConfig` 设置时间片，不开这个 gate 会报错（见[踩坑记录](#11-踩坑记录与发现)）。

安装（chart 以 OCI 方式发布，不需要 `helm repo add`）：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ helm install dra-driver-nvidia-gpu oci://registry.k8s.io/dra-driver-nvidia/charts/dra-driver-nvidia-gpu --version 0.5.1 --namespace dra-driver-nvidia-gpu --create-namespace -f kind/dra-driver-values.yaml
Pulled: registry.k8s.io/dra-driver-nvidia/charts/dra-driver-nvidia-gpu:0.5.1
Digest: sha256:43a177ebd628565fff5c78a2e489e455161cbfd3e3ecdd3e80e50318c7d40ff1
NAME: dra-driver-nvidia-gpu
LAST DEPLOYED: Mon Nov 16 22:33:27 2026
NAMESPACE: dra-driver-nvidia-gpu
STATUS: deployed
REVISION: 1
TEST SUITE: None

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-driver-nvidia-gpu wait --for=condition=Ready pod -l app.kubernetes.io/name=dra-driver-nvidia-gpu --timeout=300s
pod/dra-driver-nvidia-gpu-kubelet-plugin-b8hvr condition met

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-driver-nvidia-gpu get pod -o wide
NAME                                         READY   STATUS    RESTARTS   AGE   IP           NODE         NOMINATED NODE   READINESS GATES
dra-driver-nvidia-gpu-kubelet-plugin-b8hvr   1/1     Running   0          7s    10.244.1.2   dra-worker   <none>           <none>
```

只有一个 DaemonSet Pod（`kubelet-plugin`），因为关掉了 ComputeDomain，所以没有 controller Pod。

driver 注册的 DeviceClass：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl get deviceclass
NAME                  AGE
gpu.nvidia.com        16s
mig.nvidia.com        16s
vfio.gpu.nvidia.com   16s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl get deviceclass gpu.nvidia.com -o yaml | sed -n "/^spec:/,\$p"
spec:
  extendedResourceName: nvidia.com/gpu
  selectors:
  - cel:
      expression: device.driver == 'gpu.nvidia.com' && device.attributes['gpu.nvidia.com'].type
        == 'gpu'
```

注意 `gpu.nvidia.com` 自带 `extendedResourceName: nvidia.com/gpu`。这表示 Pod 用老写法
`limits: {nvidia.com/gpu: 1}` 也能通过 DRA 拿到 GPU（Kubernetes 1.37 中 `DRAExtendedResource` 已 GA），例 9 会用到。

kubelet plugin 为 `dra-worker` 发布的 ResourceSlice，能看到 GB10 的全部属性：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl get resourceslice -o wide
NAME                                    NODE         DRIVER           POOL         AGE
00000-gpu.nvidia.com-dra-worker-h2pwb   dra-worker   gpu.nvidia.com   dra-worker   2s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl get resourceslice -o yaml | sed -n "/^  spec:/,/^kind:/p"
  spec:
    devices:
    - attributes:
        addressingMode:
          string: ATS
        architecture:
          string: Blackwell
        brand:
          string: NvidiaRTX
        cudaComputeCapability:
          version: 12.1.0
        cudaDriverVersion:
          version: 13.0.0
        driverVersion:
          version: 580.173.2
        productName:
          string: NVIDIA GB10
        resource.kubernetes.io/pciBusID:
          string: 000f:01:00.0
        resource.kubernetes.io/pcieRoot:
          string: pci000f:00
        type:
          string: gpu
        uuid:
          string: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57
      name: gpu-0
    driver: gpu.nvidia.com
    nodeName: dra-worker
    pool:
      generation: 1
      name: dra-worker
      resourceSliceCount: 1
kind: List
```

> GB10 是统一内存，所以 ResourceSlice 里**没有 `capacity.memory`**。在独立显卡（如 H100）上这里会有显存容量，
> 可以用 CEL 按显存选卡；在 Spark 上只能按 `productName` / `architecture` / `cudaComputeCapability` 等属性选。

## 7. 第 3 步：DRA 单独测试（例 1–5）

### 例 1：ResourceClaimTemplate，一个 Pod 拿一块 GPU

```yaml
# manifests/01-single-gpu-claim-template.yaml
# Example 1: one Pod gets one whole GPU through a ResourceClaimTemplate.
# The scheduler creates a ResourceClaim from the template for the Pod,
# picks a device from the gpu.nvidia.com DeviceClass, and the DRA kubelet
# plugin injects that GPU into the container via CDI.
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  namespace: dra-demo
  name: single-gpu
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
---
apiVersion: v1
kind: Pod
metadata:
  namespace: dra-demo
  name: gpu-pod
spec:
  restartPolicy: Never
  containers:
  - name: vectoradd
    image: nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0
    command: ["bash", "-c"]
    args:
    - |
      echo "== nvidia-smi -L"; nvidia-smi -L
      echo "== NVIDIA_VISIBLE_DEVICES=${NVIDIA_VISIBLE_DEVICES:-<unset>}"
      echo "== vectorAdd"; /cuda-samples/vectorAdd
    resources:
      claims:
      - name: gpu          # must match spec.resourceClaims[].name
  resourceClaims:
  - name: gpu
    resourceClaimTemplateName: single-gpu
```

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply -f manifests/00-namespace.yaml -f manifests/01-single-gpu-claim-template.yaml
namespace/dra-demo created
resourceclaimtemplate.resource.k8s.io/single-gpu created
pod/gpu-pod created

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo wait --for=jsonpath={.status.phase}=Succeeded pod/gpu-pod --timeout=300s
pod/gpu-pod condition met

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get pod gpu-pod -o wide
NAME      READY   STATUS      RESTARTS   AGE   IP           NODE         NOMINATED NODE   READINESS GATES
gpu-pod   0/1     Completed   0          7s    10.244.1.3   dra-worker   <none>           <none>

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo logs gpu-pod
== nvidia-smi -L
GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)
== NVIDIA_VISIBLE_DEVICES=void
== vectorAdd
[Vector addition of 50000 elements]
Copy input data from the host memory to the CUDA device
CUDA kernel launch with 196 blocks of 256 threads
Copy output data from the CUDA device to the host memory
Test PASSED
Done
```

- 容器里 `nvidia-smi -L` 看到了 GB10，CUDA vectorAdd `Test PASSED`，说明 GPU 是通过 DRA 注入并且能真正计算。
- `NVIDIA_VISIBLE_DEVICES=void`：GPU 不是靠 nvidia runtime 的环境变量注入的，而是 DRA plugin 通过 CDI 注入的。

调度器根据模板为 Pod 生成了一个 ResourceClaim（名字是 `<pod>-<claim>-<随机后缀>`）。Pod 结束后，这个 claim 会被自动释放并删除：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get pod gpu-pod -o jsonpath="{.status.resourceClaimStatuses}"; echo
[{"name":"gpu","resourceClaimName":"gpu-pod-gpu-zpqpb"}]

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get resourceclaim
No resources found in dra-demo namespace.

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo delete pod gpu-pod
pod "gpu-pod" deleted from dra-demo namespace
```

### 例 2：两个 Pod 各自要一块 GPU（独占）

```yaml
# manifests/02-exclusive-two-pods.yaml
# Example 2: two Pods, each with its *own* claim from the same template.
# A whole-GPU claim is exclusive, and the Spark has exactly one GPU,
# so the second Pod stays Pending until the first one releases the GPU.
apiVersion: v1
kind: Pod
metadata:
  namespace: dra-demo
  name: exclusive-1
spec:
  containers:
  - name: ctr
    image: ubuntu:24.04
    command: ["bash", "-c", "nvidia-smi -L; trap 'exit 0' TERM; sleep 9999 & wait"]
    resources:
      claims:
      - name: gpu
  resourceClaims:
  - name: gpu
    resourceClaimTemplateName: single-gpu
---
apiVersion: v1
kind: Pod
metadata:
  namespace: dra-demo
  name: exclusive-2
spec:
  containers:
  - name: ctr
    image: ubuntu:24.04
    command: ["bash", "-c", "nvidia-smi -L; trap 'exit 0' TERM; sleep 9999 & wait"]
    resources:
      claims:
      - name: gpu
  resourceClaims:
  - name: gpu
    resourceClaimTemplateName: single-gpu
```

两个 Pod 用同一个模板，但**各自生成独立的 claim**。整块 GPU 的分配是独占的，Spark 只有一块 GPU，所以第二个 Pod 会 Pending：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply -f manifests/02-exclusive-two-pods.yaml
pod/exclusive-1 created
pod/exclusive-2 created

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get pod -o wide
NAME          READY   STATUS    RESTARTS   AGE   IP           NODE         NOMINATED NODE   READINESS GATES
exclusive-1   1/1     Running   0          15s   10.244.1.4   dra-worker   <none>           <none>
exclusive-2   0/1     Pending   0          15s   <none>       <none>       <none>           <none>

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get resourceclaim
NAME                    STATE                AGE
exclusive-1-gpu-662dp   allocated,reserved   15s
exclusive-2-gpu-fns9j   pending              15s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get resourceclaim -o jsonpath="{range .items[*]}{.metadata.name}{\"  allocated: \"}{.status.allocation.devices.results[*].device}{\"  reservedFor: \"}{.status.reservedFor[*].name}{\"\n\"}{end}"
exclusive-1-gpu-662dp  allocated: gpu-0  reservedFor: exclusive-1
exclusive-2-gpu-fns9j  allocated:   reservedFor:

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get events --field-selector involvedObject.name=exclusive-2 -o custom-columns=REASON:.reason,MESSAGE:.message
REASON             MESSAGE
FailedScheduling   0/2 nodes are available: 1 cannot allocate all claims, 1 node(s) had untolerated taint(s). preemption: 0/2 nodes are available: 2 Preemption is not helpful for scheduling.
```

调度失败的原因是 `1 cannot allocate all claims`（另外 1 个节点是 control-plane，带污点）。删掉第一个 Pod 后，GPU 被释放，第二个 Pod 马上被调度：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo logs exclusive-1
GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo delete pod exclusive-1
pod "exclusive-1" deleted from dra-demo namespace

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get pod,resourceclaim
NAME              READY   STATUS    RESTARTS   AGE
pod/exclusive-2   1/1     Running   0          16s

NAME                                                  STATE                AGE
resourceclaim.resource.k8s.io/exclusive-2-gpu-fns9j   allocated,reserved   16s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo logs exclusive-2
GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo delete pod exclusive-2
pod "exclusive-2" deleted from dra-demo namespace
```

### 例 3：两个 Pod 共享同一个 ResourceClaim

```yaml
# manifests/03-shared-claim.yaml
# Example 3: one standalone ResourceClaim referenced by two Pods.
# Both Pods (and every container in them that lists the claim) see the
# *same* physical GPU. The claim lives until it is deleted explicitly.
apiVersion: resource.k8s.io/v1
kind: ResourceClaim
metadata:
  namespace: dra-demo
  name: shared-gpu
spec:
  devices:
    requests:
    - name: gpu
      exactly:
        deviceClassName: gpu.nvidia.com
---
apiVersion: v1
kind: Pod
metadata:
  namespace: dra-demo
  name: shared-1
spec:
  containers:
  - name: ctr
    image: ubuntu:24.04
    command: ["bash", "-c", "nvidia-smi -L; trap 'exit 0' TERM; sleep 9999 & wait"]
    resources:
      claims:
      - name: gpu
  resourceClaims:
  - name: gpu
    resourceClaimName: shared-gpu
---
apiVersion: v1
kind: Pod
metadata:
  namespace: dra-demo
  name: shared-2
spec:
  containers:
  - name: ctr0
    image: ubuntu:24.04
    command: ["bash", "-c", "nvidia-smi -L; trap 'exit 0' TERM; sleep 9999 & wait"]
    resources:
      claims:
      - name: gpu
  - name: ctr1
    image: ubuntu:24.04
    command: ["bash", "-c", "nvidia-smi -L; trap 'exit 0' TERM; sleep 9999 & wait"]
    resources:
      claims:
      - name: gpu
  resourceClaims:
  - name: gpu
    resourceClaimName: shared-gpu
```

这次是手工创建的 `ResourceClaim`（不是模板），两个 Pod 都用 `resourceClaimName` 引用它。三个容器拿到的是**同一块** GPU（UUID 相同）。claim 的 `reservedFor` 里有两个 Pod：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply -f manifests/03-shared-claim.yaml
resourceclaim.resource.k8s.io/shared-gpu created
pod/shared-1 created
pod/shared-2 created

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo wait --for=condition=Ready pod/shared-1 pod/shared-2 --timeout=120s
pod/shared-1 condition met
pod/shared-2 condition met

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get pod,resourceclaim
NAME           READY   STATUS    RESTARTS   AGE
pod/shared-1   1/1     Running   0          1s
pod/shared-2   2/2     Running   0          1s

NAME                                       STATE                AGE
resourceclaim.resource.k8s.io/shared-gpu   allocated,reserved   1s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get resourceclaim shared-gpu -o jsonpath="{.status.reservedFor[*].name}"; echo
shared-1 shared-2

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo logs shared-1
GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo logs shared-2 --all-containers --prefix
[pod/shared-2/ctr0] GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)
[pod/shared-2/ctr1] GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl delete -f manifests/03-shared-claim.yaml
resourceclaim.resource.k8s.io "shared-gpu" deleted from dra-demo namespace
pod "shared-1" deleted from dra-demo namespace
pod "shared-2" deleted from dra-demo namespace
```

> 用 `resourceClaimName` 引用的 claim 不会随 Pod 删除，要自己删。共享 claim 只是让多个容器看到同一块 GPU，
> 并不做算力隔离；要隔离可以用例 5 的时间片，或 MPS / MIG。

### 例 4：用 CEL 表达式按属性选 GPU

```yaml
# manifests/04-cel-selector.yaml
# Example 4: pick devices by attribute with a CEL selector.
# The ResourceSlice published by the driver carries attributes such as
# productName, architecture and cudaComputeCapability. "blackwell-gpu"
# matches the GB10; "h100-gpu" matches nothing on this node, so its Pod
# stays Pending with "cannot allocate all claims".
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  namespace: dra-demo
  name: blackwell-gpu
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
          selectors:
          - cel:
              expression: |
                device.attributes['gpu.nvidia.com'].architecture == 'Blackwell' &&
                device.attributes['gpu.nvidia.com'].cudaComputeCapability.isGreaterThan(semver('12.0.0'))
---
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  namespace: dra-demo
  name: h100-gpu
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
          selectors:
          - cel:
              expression: device.attributes['gpu.nvidia.com'].productName.lowerAscii().matches('h100')
---
apiVersion: v1
kind: Pod
metadata:
  namespace: dra-demo
  name: cel-blackwell
spec:
  restartPolicy: Never
  containers:
  - name: ctr
    image: ubuntu:24.04
    command: ["bash", "-c", "nvidia-smi --query-gpu=name,compute_cap,uuid --format=csv"]
    resources:
      claims:
      - name: gpu
  resourceClaims:
  - name: gpu
    resourceClaimTemplateName: blackwell-gpu
---
apiVersion: v1
kind: Pod
metadata:
  namespace: dra-demo
  name: cel-h100
spec:
  restartPolicy: Never
  containers:
  - name: ctr
    image: ubuntu:24.04
    command: ["bash", "-c", "nvidia-smi -L"]
    resources:
      claims:
      - name: gpu
  resourceClaims:
  - name: gpu
    resourceClaimTemplateName: h100-gpu
```

`blackwell-gpu` 要求 `architecture == 'Blackwell'` 且算力大于 12.0，GB10 满足；`h100-gpu` 要求型号里有 `h100`，这台机器上没有：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply -f manifests/04-cel-selector.yaml
resourceclaimtemplate.resource.k8s.io/blackwell-gpu created
resourceclaimtemplate.resource.k8s.io/h100-gpu created
pod/cel-blackwell created
pod/cel-h100 created

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo wait --for=jsonpath={.status.phase}=Succeeded pod/cel-blackwell --timeout=120s
pod/cel-blackwell condition met

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get pod,resourceclaim
NAME                READY   STATUS      RESTARTS   AGE
pod/cel-blackwell   0/1     Completed   0          2s
pod/cel-h100        0/1     Pending     0          2s

NAME                                               STATE     AGE
resourceclaim.resource.k8s.io/cel-h100-gpu-rlqhr   pending   2s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo logs cel-blackwell
name, compute_cap, uuid
NVIDIA GB10, 12.1, GPU-3f370c1d-e554-fce7-5841-cf15d5495a57

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get events --field-selector involvedObject.name=cel-h100 -o custom-columns=REASON:.reason,MESSAGE:.message
REASON             MESSAGE
FailedScheduling   0/2 nodes are available: 1 cannot allocate all claims, 1 node(s) had untolerated taint(s). preemption: 0/2 nodes are available: 2 Preemption is not helpful for scheduling.

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl delete -f manifests/04-cel-selector.yaml
resourceclaimtemplate.resource.k8s.io "blackwell-gpu" deleted from dra-demo namespace
resourceclaimtemplate.resource.k8s.io "h100-gpu" deleted from dra-demo namespace
pod "cel-blackwell" deleted from dra-demo namespace
pod "cel-h100" deleted from dra-demo namespace
```

### 例 5：GpuConfig 时间片共享

```yaml
# manifests/05-time-slicing.yaml
# Example 5: driver-specific configuration through an opaque GpuConfig.
# One claim, two containers, and the NVIDIA driver is told to configure
# the GPU for time-slicing (interval Long) before handing it out.
# Both containers run the CUDA nbody benchmark on the same GPU at once.
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  namespace: dra-demo
  name: timesliced-gpu
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
      config:
      - requests: ["gpu"]
        opaque:
          driver: gpu.nvidia.com
          parameters:
            apiVersion: resource.nvidia.com/v1beta1
            kind: GpuConfig
            sharing:
              strategy: TimeSlicing
              timeSlicingConfig:
                interval: Long
---
apiVersion: v1
kind: Pod
metadata:
  namespace: dra-demo
  name: timesliced
spec:
  restartPolicy: Never
  containers:
  - name: nbody-0
    image: nvcr.io/nvidia/k8s/cuda-sample:nbody-cuda11.6.0-ubuntu18.04
    command: ["/tmp/sample", "-benchmark", "-numbodies=524288"]
    resources:
      claims:
      - name: gpu
  - name: nbody-1
    image: nvcr.io/nvidia/k8s/cuda-sample:nbody-cuda11.6.0-ubuntu18.04
    command: ["/tmp/sample", "-benchmark", "-numbodies=524288"]
    resources:
      claims:
      - name: gpu
  resourceClaims:
  - name: gpu
    resourceClaimTemplateName: timesliced-gpu
```

`config.opaque` 里的参数由 NVIDIA driver 解析（API 是 `resource.nvidia.com/v1beta1`）。两个容器同时在同一块 GPU 上跑 nbody：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply -f manifests/05-time-slicing.yaml
resourceclaimtemplate.resource.k8s.io/timesliced-gpu created
pod/timesliced created

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo wait --for=jsonpath={.status.phase}=Succeeded pod/timesliced --timeout=300s
pod/timesliced condition met

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get pod timesliced
NAME         READY   STATUS      RESTARTS   AGE
timesliced   0/2     Completed   0          17s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo logs timesliced --all-containers --prefix | grep -E "GB10|total time|GFLOP"
[pod/timesliced/nbody-0] > Compute 12.1 CUDA device: [NVIDIA GB10]
[pod/timesliced/nbody-0] 524288 bodies, total time for 10 iterations: 7841.941 ms
[pod/timesliced/nbody-0] = 7010.456 single-precision GFLOP/s at 20 flops per interaction
[pod/timesliced/nbody-1] > Compute 12.1 CUDA device: [NVIDIA GB10]
[pod/timesliced/nbody-1] 524288 bodies, total time for 10 iterations: 7634.924 ms
[pod/timesliced/nbody-1] = 7200.541 single-precision GFLOP/s at 20 flops per interaction
```

单独跑这个 nbody 大约是 16000 GFLOP/s（见例 6 的日志），这里两个容器各约 7000 GFLOP/s，加起来差不多是一块 GPU 的算力，说明两个容器确实在分时共享同一块 GPU。

kubelet plugin 的日志和宿主机上的时间片策略：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-driver-nvidia-gpu logs ds/dra-driver-nvidia-gpu-kubelet-plugin -c gpus | grep -E "timesliced-gpu" | grep -v -E "ca_rotation" | head -3
I1117 03:34:17.734414       1 driver.go:433] Returning newly prepared devices for claim 'dra-demo/timesliced-gpu-96zz8:2971e02f-33e4-40ce-840e-20eca9458e60': [{[gpu] dra-worker gpu-0 [k8s.gpu.nvidia.com/claim=2971e02f-33e4-40ce-840e-20eca9458e60-gpu-0] <nil> <nil>}]

gyliu@spark-3bee:~/nvidia-dra-demo$ nvidia-smi compute-policy -l
+-------------------------------------+
| GPU compute policies:               |
| GPU     Name           Value        |
|=====================================|
|   0   Timeslice       Default       |
+-------------------------------------+

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl delete -f manifests/05-time-slicing.yaml
resourceclaimtemplate.resource.k8s.io "timesliced-gpu" deleted from dra-demo namespace
pod "timesliced" deleted from dra-demo namespace
```

> 时间片是**整块物理 GPU 的全局设置**（`nvidia-smi compute-policy --set-timeslice`）。claim 释放后 driver 会把它
> 恢复成 `Default`，所以上面看到的已经是 `Default`。如果这块 GPU 还被宿主机上的其他程序用（比如这台 Spark 上的 ComfyUI），
> 那么 claim 存在期间它们也会受这个设置影响。

## 8. 第 4 步：Kueue 支持 DRA 吗？

**支持。** 结论来自 Kueue 源码（`v0.20.6` tag）和官方文档 `site/content/en/v0.20/docs/concepts/dynamic_resource_allocation.md`：

| Kueue feature gate | v0.20.6 状态 | 作用 |
|---|---|---|
| `KueueDRAIntegration` | Beta，默认开启（v0.18 起；v0.18 之前叫 `DynamicResourceAllocation`） | 按 ResourceClaimTemplate 的设备数量计入配额 |
| `KueueDRAIntegrationExtendedResource` | Beta，默认开启（v0.19 起） | 支持 `nvidia.com/gpu` 这类 DRA 扩展资源写法 |
| `KueueDRAIntegrationPartitionableDevices` | Beta，默认开启 | 按 counter 计配额（如 MIG 切分） |
| `KueueDRAIntegrationConsumableCapacity` | Alpha，默认关闭 | 按容量（capacity）计配额 |
| `KueueDRAIntegrationPrioritizedList` | Alpha，默认关闭 | 支持 `firstAvailable` |

工作方式：

1. 在 Kueue 配置里写 `resources.deviceClassMappings`，把一个或多个 DeviceClass 映射成一个"逻辑资源名"
   （本文用 `nvidia.com/dra-gpu` ← `gpu.nvidia.com`）。
2. ClusterQueue 的 `coveredResources` 里写这个逻辑资源名，给它配额。
3. Job 的 Pod 模板通过 `ResourceClaimTemplate` 要设备，Kueue 按每个 `exactly` 请求的 `count`（默认 1）计入配额。

限制（v0.20.6）：

- **只支持 `ResourceClaimTemplate`**。直接引用 `ResourceClaim` 的 Workload 会被标为不可准入（例 8 验证）。
- 只支持 `allocationMode: ExactCount`；`allocationMode: All`、`constraints`（matchAttribute）、请求里的 `config` 不支持。
- CEL selector 支持（Kueue 会拿 ResourceSlice 校验一下是否有设备能满足）。
- Kueue 只管"配额"，不管"具体选哪块卡"，具体设备还是由 kube-scheduler 分配。上游建议配合 `waitForPodsReady` 做兜底。
- **配置只在启动时读取**，改了 ConfigMap 必须重启 `kueue-controller-manager`。
- 一个 DeviceClass 只能映射到一个逻辑资源名。

## 9. 第 5 步：安装 Kueue 并开启 DRA 映射

下载并安装 Kueue v0.20.6 的发布清单（CRD 很大，要用 `--server-side`）：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ curl -sSL -o kueue/manifests.yaml https://github.com/kubernetes-sigs/kueue/releases/download/v0.20.6/manifests.yaml && ls -l kueue/manifests.yaml
-rw-r--r-- 1 gyliu gyliu 1798254 Nov 16 22:34 kueue/manifests.yaml

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply --server-side -f kueue/manifests.yaml | tail -5
service/kueue-webhook-service serverside-applied
deployment.apps/kueue-controller-manager serverside-applied
apiservice.apiregistration.k8s.io/v1beta2.visibility.kueue.x-k8s.io serverside-applied
mutatingwebhookconfiguration.admissionregistration.k8s.io/kueue-mutating-webhook-configuration serverside-applied
validatingwebhookconfiguration.admissionregistration.k8s.io/kueue-validating-webhook-configuration serverside-applied

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-system rollout status deploy/kueue-controller-manager --timeout=300s
Waiting for deployment "kueue-controller-manager" rollout to finish: 0 of 1 updated replicas are available...
deployment "kueue-controller-manager" successfully rolled out
```

Kueue 配置（[kueue/controller_manager_config.yaml](kueue/controller_manager_config.yaml)）就是发布清单里的默认配置，
在最后加了 `resources.deviceClassMappings`：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ tail -20 kueue/controller_manager_config.yaml
  - "pod"
  - "deployment"
  - "statefulset"
  - "leaderworkerset.x-k8s.io/leaderworkerset"
# --- added for DRA -------------------------------------------------------
# Kueue cannot count "a ResourceClaimTemplate asking for 1 device of class
# gpu.nvidia.com" as quota by itself. This mapping turns every device
# requested from the gpu.nvidia.com DeviceClass into 1 unit of the logical
# resource "nvidia.com/dra-gpu", which ClusterQueues can then put a quota on.
# The same mapping also covers Pods that ask for the classic extended
# resource nvidia.com/gpu: the driver's gpu.nvidia.com DeviceClass sets
# extendedResourceName: nvidia.com/gpu, and Kueue charges such Pods to the
# mapped name (see 14-extended-resource.yaml).
# (KueueDRAIntegration and KueueDRAIntegrationExtendedResource are beta and
# on by default in v0.20, so no --feature-gates flag is needed.)
resources:
  deviceClassMappings:
  - name: nvidia.com/dra-gpu
    deviceClassNames:
    - gpu.nvidia.com
```

用这个文件替换 `kueue-manager-config` ConfigMap，然后重启 controller（Kueue 只在启动时读配置）：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-system create configmap kueue-manager-config --from-file=controller_manager_config.yaml=kueue/controller_manager_config.yaml --dry-run=client -o yaml | kubectl apply --server-side --force-conflicts -f -
configmap/kueue-manager-config serverside-applied

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-system rollout restart deploy/kueue-controller-manager
deployment.apps/kueue-controller-manager restarted

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-system rollout status deploy/kueue-controller-manager --timeout=300s
Waiting for deployment "kueue-controller-manager" rollout to finish: 1 old replicas are pending termination...
Waiting for deployment "kueue-controller-manager" rollout to finish: 1 old replicas are pending termination...
deployment "kueue-controller-manager" successfully rolled out

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-system get pod
NAME                                        READY   STATUS    RESTARTS   AGE
kueue-controller-manager-85d8bbc768-56m24   1/1     Running   0          32s
```

确认新 Pod 加载了 DRA 映射（Kueue 启动时会把完整配置打到日志里）：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-system logs deploy/kueue-controller-manager | grep -m1 -o "resources:.n  deviceClassMappings:.*name: nvidia.com/dra-gpu" | sed "s/\\\\n/\\n/g"
resources:
  deviceClassMappings:
  - deviceClassNames:
    - gpu.nvidia.com
    name: nvidia.com/dra-gpu
```

> 重启后**稍等几秒再建 Kueue 对象**。新 Pod 变成 Ready 后，webhook 可能还没开始服务，这时创建 ResourceFlavor
> 会报 `failed calling webhook "mresourceflavor.kb.io" ... context deadline exceeded`（第一次录制时就遇到了）。
> 等旧 Pod 完全退出、再重试一次就好。

## 10. 第 6 步：Kueue + DRA 例子（例 6–9）

队列定义：一个 ClusterQueue，`nvidia.com/dra-gpu` 配额是 1（Spark 只有一块 GB10）：

```yaml
# kueue/10-queues.yaml
# Kueue objects for the DRA demo.
# The ClusterQueue owns exactly 1 unit of nvidia.com/dra-gpu (the logical
# resource that kueue/controller_manager_config.yaml maps from the
# gpu.nvidia.com DeviceClass) -- the Spark has one GB10.
apiVersion: v1
kind: Namespace
metadata:
  name: kueue-dra
---
apiVersion: kueue.x-k8s.io/v1beta2
kind: ResourceFlavor
metadata:
  name: spark-gb10
---
apiVersion: kueue.x-k8s.io/v1beta2
kind: ClusterQueue
metadata:
  name: gpu-cq
spec:
  namespaceSelector: {}
  queueingStrategy: BestEffortFIFO
  resourceGroups:
  - coveredResources: ["cpu", "memory", "nvidia.com/dra-gpu"]
    flavors:
    - name: spark-gb10
      resources:
      - name: cpu
        nominalQuota: 8
      - name: memory
        nominalQuota: 16Gi
      - name: nvidia.com/dra-gpu
        nominalQuota: 1
---
apiVersion: kueue.x-k8s.io/v1beta2
kind: LocalQueue
metadata:
  namespace: kueue-dra
  name: gpu-lq
spec:
  clusterQueue: gpu-cq
---
# Kueue only supports ResourceClaimTemplates (not pre-created ResourceClaims).
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  namespace: kueue-dra
  name: single-gpu
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
---
# Asks for 2 GPUs in one claim (count: 2); used by 12-too-big-job.yaml.
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  namespace: kueue-dra
  name: two-gpus
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
          count: 2
```

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply -f kueue/10-queues.yaml
namespace/kueue-dra created
resourceflavor.kueue.x-k8s.io/spark-gb10 created
clusterqueue.kueue.x-k8s.io/gpu-cq created
localqueue.kueue.x-k8s.io/gpu-lq created
resourceclaimtemplate.resource.k8s.io/single-gpu created
resourceclaimtemplate.resource.k8s.io/two-gpus created

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl get clusterqueue gpu-cq -o wide; kubectl -n kueue-dra get localqueue
NAME     COHORT   STRATEGY         PENDING WORKLOADS   ADMITTED WORKLOADS   ACTIVE   REASON
gpu-cq            BestEffortFIFO   0                   0                    True     Ready
NAME     CLUSTERQUEUE   PENDING WORKLOADS   ADMITTED WORKLOADS
gpu-lq   gpu-cq         0                   0
```

### 例 6：两个 Job 抢 1 块 GPU 的配额

```yaml
# kueue/11-gpu-jobs.yaml
# Two batch Jobs, each needs one GPU through a ResourceClaimTemplate.
# Kueue charges 1 nvidia.com/dra-gpu per Job; quota is 1, so only one Job is
# admitted (unsuspended) at a time and the other one waits *inside Kueue*
# (suspended, no Pod, no ResourceClaim) instead of as a Pending Pod.
apiVersion: batch/v1
kind: Job
metadata:
  namespace: kueue-dra
  name: train-a
  labels:
    kueue.x-k8s.io/queue-name: gpu-lq
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: cuda
        image: nvcr.io/nvidia/k8s/cuda-sample:nbody-cuda11.6.0-ubuntu18.04
        command: ["bash", "-c"]
        args:
        - |
          nvidia-smi -L
          /tmp/sample -benchmark -numbodies=524288 | tail -3
          echo "pretend to train for 45s ..."; sleep 45; echo done
        resources:
          requests:
            cpu: "1"
            memory: 1Gi
          claims:
          - name: gpu
      resourceClaims:
      - name: gpu
        resourceClaimTemplateName: single-gpu
---
apiVersion: batch/v1
kind: Job
metadata:
  namespace: kueue-dra
  name: train-b
  labels:
    kueue.x-k8s.io/queue-name: gpu-lq
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: cuda
        image: nvcr.io/nvidia/k8s/cuda-sample:nbody-cuda11.6.0-ubuntu18.04
        command: ["bash", "-c"]
        args:
        - |
          nvidia-smi -L
          /tmp/sample -benchmark -numbodies=524288 | tail -3
          echo "pretend to train for 45s ..."; sleep 45; echo done
        resources:
          requests:
            cpu: "1"
            memory: 1Gi
          claims:
          - name: gpu
      resourceClaims:
      - name: gpu
        resourceClaimTemplateName: single-gpu
```

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply -f kueue/11-gpu-jobs.yaml
job.batch/train-a created
job.batch/train-b created

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get job,workload,pod,resourceclaim
NAME                STATUS      COMPLETIONS   DURATION   AGE
job.batch/train-a   Running     0/1           10s        10s
job.batch/train-b   Suspended   0/1                      10s

NAME                                        QUEUE    RESERVED IN   ADMITTED   FINISHED   AGE
workload.kueue.x-k8s.io/job-train-a-b4bce   gpu-lq   gpu-cq        True                  10s
workload.kueue.x-k8s.io/job-train-b-37c04   gpu-lq                 False                 10s

NAME                READY   STATUS    RESTARTS   AGE
pod/train-a-bzpkd   1/1     Running   0          10s

NAME                                                    STATE                AGE
resourceclaim.resource.k8s.io/train-a-bzpkd-gpu-9fsvv   allocated,reserved   10s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get workload -o custom-columns=WORKLOAD:.metadata.name,QUOTA_RESERVED:.status.conditions[?\(@.type==\"QuotaReserved\"\)].status,MESSAGE:.status.conditions[?\(@.type==\"QuotaReserved\"\)].message
WORKLOAD            QUOTA_RESERVED   MESSAGE
job-train-a-b4bce   True             Quota reserved in ClusterQueue gpu-cq
job-train-b-37c04   False            couldn't assign flavors to pod set main: insufficient unused quota for nvidia.com/dra-gpu in flavor spark-gb10, 1 more needed
```

和例 2 对比：

- 例 2（没有 Kueue）：第二个 Pod 已经创建出来，卡在调度器里 Pending，它的 ResourceClaim 也已经创建，状态是 `pending`。
- 例 6（有 Kueue）：`train-b` 的 Job 是 **Suspended**，**没有 Pod，也没有 ResourceClaim**，在 Kueue 里排队，
  原因是 `insufficient unused quota for nvidia.com/dra-gpu ... 1 more needed`。

ClusterQueue 的用量和 `train-a` 的 Workload 准入结果，可以看到 Kueue 把 DRA 设备换算成了 `nvidia.com/dra-gpu: 1`：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl get clusterqueue gpu-cq -o jsonpath="{.status.flavorsUsage}" | python3 -m json.tool
[
    {
        "name": "spark-gb10",
        "resources": [
            {
                "borrowed": "0",
                "name": "cpu",
                "total": "1"
            },
            {
                "borrowed": "0",
                "name": "memory",
                "total": "1Gi"
            },
            {
                "borrowed": "0",
                "name": "nvidia.com/dra-gpu",
                "total": "1"
            }
        ]
    }
]

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get workload -l kueue.x-k8s.io/job-uid=$(kubectl -n kueue-dra get job train-a -o jsonpath={.metadata.uid}) -o jsonpath="{.items[0].status.admission}" | python3 -m json.tool
{
    "clusterQueue": "gpu-cq",
    "podSetAssignments": [
        {
            "count": 1,
            "flavors": {
                "cpu": "spark-gb10",
                "memory": "spark-gb10",
                "nvidia.com/dra-gpu": "spark-gb10"
            },
            "name": "main",
            "resourceUsage": {
                "cpu": "1",
                "memory": "1Gi",
                "nvidia.com/dra-gpu": "1"
            }
        }
    ]
}
```

`train-a` 跑完后释放配额，Kueue 自动把 `train-b` 解除挂起（unsuspend），它的 Pod 和 ResourceClaim 这时才被创建：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra wait --for=condition=complete job/train-a --timeout=300s
job.batch/train-a condition met

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get job,workload,pod
NAME                STATUS     COMPLETIONS   DURATION   AGE
job.batch/train-a   Complete   1/1           53s        58s
job.batch/train-b   Running    0/1           4s         58s

NAME                                        QUEUE    RESERVED IN   ADMITTED   FINISHED   AGE
workload.kueue.x-k8s.io/job-train-a-b4bce   gpu-lq   gpu-cq        True       True       58s
workload.kueue.x-k8s.io/job-train-b-37c04   gpu-lq   gpu-cq        True                  58s

NAME                READY   STATUS      RESTARTS   AGE
pod/train-a-bzpkd   0/1     Completed   0          58s
pod/train-b-fn8zw   1/1     Running     0          4s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra logs job/train-a
GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)
524288 bodies, total time for 10 iterations: 3445.974 ms
= 797.678 billion interactions per second
= 15953.570 single-precision GFLOP/s at 20 flops per interaction
pretend to train for 45s ...
done

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra wait --for=condition=complete job/train-b --timeout=300s
job.batch/train-b condition met

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get job,workload
NAME                STATUS     COMPLETIONS   DURATION   AGE
job.batch/train-a   Complete   1/1           53s        107s
job.batch/train-b   Complete   1/1           53s        107s

NAME                                        QUEUE    RESERVED IN   ADMITTED   FINISHED   AGE
workload.kueue.x-k8s.io/job-train-a-b4bce   gpu-lq   gpu-cq        True       True       107s
workload.kueue.x-k8s.io/job-train-b-37c04   gpu-lq   gpu-cq        True       True       107s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra logs job/train-b
GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)
524288 bodies, total time for 10 iterations: 3455.006 ms
= 795.593 billion interactions per second
= 15911.865 single-precision GFLOP/s at 20 flops per interaction
pretend to train for 45s ...
done

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra delete job train-a train-b
job.batch "train-a" deleted from kueue-dra namespace
job.batch "train-b" deleted from kueue-dra namespace
```

### 例 7：一个 Job 要 2 块 GPU（超过配额上限）

```yaml
# kueue/12-too-big-job.yaml
# A Job whose claim asks for 2 GPUs (count: 2). Kueue computes 2 units of
# nvidia.com/dra-gpu, which can never fit the ClusterQueue's quota of 1,
# so the Workload is never admitted and no Pod is ever created.
apiVersion: batch/v1
kind: Job
metadata:
  namespace: kueue-dra
  name: needs-two-gpus
  labels:
    kueue.x-k8s.io/queue-name: gpu-lq
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: cuda
        image: ubuntu:24.04
        command: ["nvidia-smi", "-L"]
        resources:
          requests:
            cpu: "1"
            memory: 1Gi
          claims:
          - name: gpus
      resourceClaims:
      - name: gpus
        resourceClaimTemplateName: two-gpus
```

claim 里 `count: 2`，Kueue 算出需要 2 个 `nvidia.com/dra-gpu`，超过了 ClusterQueue 的上限 1，所以原因是
`ExceedsMaxQuota`，Job 一直是 Suspended，不会创建 Pod，也不会去占调度器：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply -f kueue/12-too-big-job.yaml
job.batch/needs-two-gpus created

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get job,workload,pod
NAME                       STATUS      COMPLETIONS   DURATION   AGE
job.batch/needs-two-gpus   Suspended   0/1                      8s

NAME                                               QUEUE    RESERVED IN   ADMITTED   FINISHED   AGE
workload.kueue.x-k8s.io/job-needs-two-gpus-6cf3d   gpu-lq                 False                 8s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get workload -o jsonpath="{range .items[*]}{range .status.conditions[*]}{.type}={.status} {.reason}: {.message}{\"\n\"}{end}{end}"
QuotaReserved=False ExceedsMaxQuota: couldn't assign flavors to pod set main: insufficient quota for nvidia.com/dra-gpu in flavor spark-gb10, previously considered podsets requests (0) + current podset request (2) > maximum capacity (1)
Admitted=False NoReservation: The workload has no reservation
PodsReady=False WaitForStart: Not all pods are ready or succeeded

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra delete -f kueue/12-too-big-job.yaml
job.batch "needs-two-gpus" deleted from kueue-dra namespace
```

### 例 8：直接引用 ResourceClaim（Kueue 不支持）

```yaml
# kueue/13-direct-claim-job.yaml
# Negative test: Kueue's DRA integration only understands
# ResourceClaimTemplates. A Job that points at a pre-created ResourceClaim
# is marked inadmissible (Kueue cannot tell how much of the claim is "new"
# usage that should be charged to the queue).
apiVersion: resource.k8s.io/v1
kind: ResourceClaim
metadata:
  namespace: kueue-dra
  name: preallocated-gpu
spec:
  devices:
    requests:
    - name: gpu
      exactly:
        deviceClassName: gpu.nvidia.com
---
apiVersion: batch/v1
kind: Job
metadata:
  namespace: kueue-dra
  name: uses-resourceclaim
  labels:
    kueue.x-k8s.io/queue-name: gpu-lq
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: cuda
        image: ubuntu:24.04
        command: ["nvidia-smi", "-L"]
        resources:
          requests:
            cpu: "1"
            memory: 1Gi
          claims:
          - name: gpu
      resourceClaims:
      - name: gpu
        resourceClaimName: preallocated-gpu
```

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply -f kueue/13-direct-claim-job.yaml
resourceclaim.resource.k8s.io/preallocated-gpu created
job.batch/uses-resourceclaim created

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get job,workload,pod,resourceclaim
NAME                           STATUS      COMPLETIONS   DURATION   AGE
job.batch/uses-resourceclaim   Suspended   0/1                      8s

NAME                                                   QUEUE    RESERVED IN   ADMITTED   FINISHED   AGE
workload.kueue.x-k8s.io/job-uses-resourceclaim-b9dcc   gpu-lq                 False                 8s

NAME                                             STATE     AGE
resourceclaim.resource.k8s.io/preallocated-gpu   pending   8s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get workload -o jsonpath="{range .items[*]}{range .status.conditions[*]}{.type}={.status} {.reason}: {.message}{\"\n\"}{end}{end}"
QuotaReserved=False Misconfigured: KueueDRAIntegration feature does not support use of resource claims
Admitted=False NoReservation: The workload has no reservation
Requeued=False Inadmissible: DRA resource claims not supported
PodsReady=False WaitForStart: Not all pods are ready or succeeded

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl delete -f kueue/13-direct-claim-job.yaml
resourceclaim.resource.k8s.io "preallocated-gpu" deleted from kueue-dra namespace
job.batch "uses-resourceclaim" deleted from kueue-dra namespace
```

Workload 被标记为 `Misconfigured` / `Inadmissible`：`KueueDRAIntegration feature does not support use of resource claims`。
和 Kueue 一起用时，要用 `ResourceClaimTemplate`。

### 例 9：扩展资源写法（`nvidia.com/gpu: 1`）也走 DRA，并且共用同一份配额

```yaml
# kueue/14-extended-resource.yaml
# DRA "extended resource" mode (KEP-5004, GA in Kubernetes 1.37).
# The driver's gpu.nvidia.com DeviceClass already sets
#   spec.extendedResourceName: nvidia.com/gpu
# so a Pod can keep the classic device-plugin syntax
#   resources.limits: {nvidia.com/gpu: 1}
# and the scheduler creates a DRA ResourceClaim for it behind the scenes
# (no ResourceClaimTemplate needed). Kueue sees that nvidia.com/gpu is backed
# by gpu.nvidia.com, which is mapped to nvidia.com/dra-gpu, and charges the
# same 1-GPU quota as the ResourceClaimTemplate Jobs.
apiVersion: batch/v1
kind: Job
metadata:
  namespace: kueue-dra
  name: ext-a
  labels:
    kueue.x-k8s.io/queue-name: gpu-lq
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: cuda
        image: nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0
        command: ["bash", "-c", "nvidia-smi -L; /cuda-samples/vectorAdd | tail -2; sleep 30"]
        resources:
          requests:
            cpu: "1"
            memory: 1Gi
          limits:
            nvidia.com/gpu: 1
---
apiVersion: batch/v1
kind: Job
metadata:
  namespace: kueue-dra
  name: ext-b
  labels:
    kueue.x-k8s.io/queue-name: gpu-lq
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: cuda
        image: nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0
        command: ["bash", "-c", "nvidia-smi -L; /cuda-samples/vectorAdd | tail -2; sleep 30"]
        resources:
          requests:
            cpu: "1"
            memory: 1Gi
          limits:
            nvidia.com/gpu: 1
```

这两个 Job 没有 ResourceClaimTemplate，只写了 `limits: nvidia.com/gpu: 1`（和 device plugin 的写法一样）。
因为 `gpu.nvidia.com` 设置了 `extendedResourceName: nvidia.com/gpu`，调度器会自动为 Pod 创建一个
`<pod>-extended-resources-xxxxx` ResourceClaim。Kueue 知道 `nvidia.com/gpu` 背后是 `gpu.nvidia.com`，
而 `gpu.nvidia.com` 已经映射到 `nvidia.com/dra-gpu`，所以按 `nvidia.com/dra-gpu: 1` 计配额，和例 6 共用同一份配额：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl apply -f kueue/14-extended-resource.yaml
job.batch/ext-a created
job.batch/ext-b created

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get job,workload,pod,resourceclaim
NAME              STATUS      COMPLETIONS   DURATION   AGE
job.batch/ext-a   Running     0/1           10s        10s
job.batch/ext-b   Suspended   0/1                      10s

NAME                                      QUEUE    RESERVED IN   ADMITTED   FINISHED   AGE
workload.kueue.x-k8s.io/job-ext-a-03dcb   gpu-lq   gpu-cq        True                  11s
workload.kueue.x-k8s.io/job-ext-b-9d995   gpu-lq                 False                 11s

NAME              READY   STATUS    RESTARTS   AGE
pod/ext-a-872p2   1/1     Running   0          11s

NAME                                                                 STATE                AGE
resourceclaim.resource.k8s.io/ext-a-872p2-extended-resources-vxhg8   allocated,reserved   10s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get workload -o custom-columns=WORKLOAD:.metadata.name,QUOTA_RESERVED:.status.conditions[?\(@.type==\"QuotaReserved\"\)].status,MESSAGE:.status.conditions[?\(@.type==\"QuotaReserved\"\)].message,USAGE:.status.admission.podSetAssignments[0].resourceUsage
WORKLOAD          QUOTA_RESERVED   MESSAGE                                                                                                                         USAGE
job-ext-a-03dcb   True             Quota reserved in ClusterQueue gpu-cq                                                                                           map[cpu:1 memory:1Gi nvidia.com/dra-gpu:1]
job-ext-b-9d995   False            couldn't assign flavors to pod set main: insufficient unused quota for nvidia.com/dra-gpu in flavor spark-gb10, 1 more needed   <none>

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get resourceclaim -o yaml | grep -E "name:|extended|request:|device:" | head -12
      resource.kubernetes.io/extended-resource-claim: "true"
    generateName: ext-a-872p2-extended-resources-
    name: ext-a-872p2-extended-resources-vxhg8
      name: ext-a-872p2
        name: container-0-request-2
        - device: gpu-0
          request: container-0-request-2
    - name: ext-a-872p2
```

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra wait --for=condition=complete job/ext-a job/ext-b --timeout=300s
job.batch/ext-a condition met
job.batch/ext-b condition met

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra get job,workload
NAME              STATUS     COMPLETIONS   DURATION   AGE
job.batch/ext-a   Complete   1/1           34s        69s
job.batch/ext-b   Complete   1/1           34s        69s

NAME                                      QUEUE    RESERVED IN   ADMITTED   FINISHED   AGE
workload.kueue.x-k8s.io/job-ext-a-03dcb   gpu-lq   gpu-cq        True       True       69s
workload.kueue.x-k8s.io/job-ext-b-9d995   gpu-lq   gpu-cq        True       True       69s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-dra logs job/ext-a; kubectl -n kueue-dra logs job/ext-b
GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)
Test PASSED
Done
GPU 0: NVIDIA GB10 (UUID: GPU-3f370c1d-e554-fce7-5841-cf15d5495a57)
Test PASSED
Done

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl delete -f kueue/14-extended-resource.yaml
job.batch "ext-a" deleted from kueue-dra namespace
job.batch "ext-b" deleted from kueue-dra namespace
```

> 如果 `gpu.nvidia.com` **没有**写进 `deviceClassMappings`，Kueue 会按扩展资源名 `nvidia.com/gpu` 计配额。
> 这时 ClusterQueue 里也要有 `nvidia.com/gpu`，否则会报 `resource nvidia.com/gpu unavailable in ClusterQueue`
> （测试过程中遇到过）。不要让同一块 GPU 通过两个逻辑名各有一份配额，否则 Kueue 会以为有两块卡。

## 11. 踩坑记录与发现

1. **时间片需要 `TimeSlicingSettings` feature gate。** 不开的话，Pod 一直 `ContainerCreating`，事件是：
   ```text
   Warning  FailedPrepareDynamicResources  kubelet  Failed to prepare dynamic resources: ... error validating GPU config:
   "TimeSlicing" is selected as the GPU sharing strategy, but the "TimeSlicingSettings" feature gate is not enabled
   ```
   在 Helm values 里加 `featureGates.TimeSlicingSettings: true` 后 `helm upgrade` 即可。

2. **MPS 在这台 Spark 上跑不起来，而且在共享 GPU 上很危险，所以没有放进例子。**
   开 `featureGates.MPSSupport: true`，用 `sharing.strategy: MPS` 的 GpuConfig（上游 `gpu-test-mps.yaml`）时：
   - driver 会为 claim 启动一个 `mps-control-daemon-<claim-uid>` Deployment。v0.5.1 的模板在 `nvidiaDriverRoot=/`
     时走 `chroot /driver-root` 分支，这个分支**没有设置 `CUDA_MPS_PIPE_DIRECTORY`**，于是 daemon 一直 CrashLoopBackOff：
     ```text
     CUDA_MPS_PIPE_DIRECTORY must be set to start or to communicate with MPS control daemon
     ```
     （`templates/mps-control-daemon.tmpl.yaml`：只有在非 chroot 分支里才 export 这两个变量）
   - **更重要的是**：MPS 启动时会把整块物理 GPU 设成 `EXCLUSIVE_PROCESS` 计算模式。这台 Spark 上 ComfyUI 也在用这块 GPU，
     `EXCLUSIVE_PROCESS` 会让它没法再创建新的 CUDA 上下文。
   - prepare 失败后删掉 Pod 和 claim，driver **没有清理**：Deployment 还在，GPU 还停在 `Exclusive_Process`。只能手工恢复：
     ```console
     gyliu@spark-3bee:~/nvidia-dra-demo$ nvidia-smi --query-gpu=compute_mode --format=csv,noheader
     Exclusive_Process
     gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-driver-nvidia-gpu delete deploy mps-control-daemon-3fe33433-5f4d-4ad0-911b-c8281e8005c6-6e2cf --wait
     deployment.apps "mps-control-daemon-3fe33433-5f4d-4ad0-911b-c8281e8005c6-6e2cf" deleted from dra-driver-nvidia-gpu namespace
     gyliu@spark-3bee:~/nvidia-dra-demo$ sudo nvidia-smi -c DEFAULT
     Set compute mode to DEFAULT for GPU 0000000F:01:00.0.
     All done.
     gyliu@spark-3bee:~/nvidia-dra-demo$ nvidia-smi --query-gpu=compute_mode --format=csv,noheader
     Default
     ```
   结论：在跟其他程序共用的 GPU 上不要测 MPS；`scripts/cleanup.sh` 最后会检查 compute mode 和时间片策略。

3. **GB10 的 ResourceSlice 没有显存容量**（统一内存），不能用 `device.capacity[...].memory` 写 CEL 选择器。

4. **kind 节点里没有 `nvidia-ctk`**，driver 生成的 CDI spec 要调用它的 hook，所以要从宿主机挂进去（`/usr/bin/nvidia-ctk`）。

5. **driver 的 DaemonSet 刚创建时 `rollout status` 会立刻返回成功**（这时还没有 Pod）。要等 Pod 出现以后再
   `kubectl wait --for=condition=Ready`，ResourceSlice 也要再等几秒才会发布。

6. **Kueue 配置只在启动时读取**：改了 `deviceClassMappings` 一定要 `rollout restart`。重启后马上建对象可能撞上 webhook 还没就绪（见第 9 节）。

7. **Kueue + DRA 只支持 ResourceClaimTemplate**；需要几个 Pod 共享一块卡（例 3）时，Kueue 管不了。

8. **项目改名**：NVIDIA DRA driver 现在是 `kubernetes-sigs/dra-driver-nvidia-gpu`，chart 是
   `oci://registry.k8s.io/dra-driver-nvidia/charts/dra-driver-nvidia-gpu`，版本号从 v0.4.0 开始重新编号。网上很多老文章用的是
   `nvidia/k8s-dra-driver-gpu` 的 helm repo 和 `v25.x` 版本。

## 12. 清理

[scripts/cleanup.sh](scripts/cleanup.sh) 删除 kind 集群，并检查物理 GPU 的 compute mode 和时间片策略有没有恢复成默认值：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl delete ns dra-demo kueue-dra
namespace "dra-demo" deleted
namespace "kueue-dra" deleted

gyliu@spark-3bee:~/nvidia-dra-demo$ scripts/cleanup.sh
Deleting cluster "dra" ...
Deleted nodes: ["dra-control-plane" "dra-worker"]
Default
+-------------------------------------+
| GPU compute policies:               |
| GPU     Name           Value        |
|=====================================|
|   0   Timeslice       Default       |
+-------------------------------------+
```

[scripts/setup.sh](scripts/setup.sh) 可以一键重建整个环境（kind 集群 + DRA driver + Kueue + 队列），本文最后就是用它把环境重新建起来的：

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ scripts/setup.sh 2>&1 | grep -v -E "^(customresourcedefinition|Waiting for deployment)" | tail -30
Pulled: registry.k8s.io/dra-driver-nvidia/charts/dra-driver-nvidia-gpu:0.5.1
Digest: sha256:43a177ebd628565fff5c78a2e489e455161cbfd3e3ecdd3e80e50318c7d40ff1
NAME: dra-driver-nvidia-gpu
LAST DEPLOYED: Mon Nov 16 22:39:45 2026
NAMESPACE: dra-driver-nvidia-gpu
STATUS: deployed
REVISION: 1
TEST SUITE: None
pod/dra-driver-nvidia-gpu-kubelet-plugin-52mzm condition met
NAME                                    NODE         DRIVER           POOL         AGE
00000-gpu.nvidia.com-dra-worker-22nr6   dra-worker   gpu.nvidia.com   dra-worker   2s
==> Kueue v0.20.6
deployment "kueue-controller-manager" successfully rolled out
configmap/kueue-manager-config serverside-applied
deployment.apps/kueue-controller-manager restarted
deployment "kueue-controller-manager" successfully rolled out
namespace/kueue-dra created
clusterqueue.kueue.x-k8s.io/gpu-cq created
localqueue.kueue.x-k8s.io/gpu-lq created
resourceclaimtemplate.resource.k8s.io/single-gpu created
resourceclaimtemplate.resource.k8s.io/two-gpus created
Error from server (InternalError): error when creating "kueue/10-queues.yaml": Internal error occurred: failed calling webhook "mresourceflavor.kb.io": failed to call webhook: Post "https://kueue-webhook-service.kueue-system.svc:443/mutate-kueue-x-k8s-io-v1beta2-resourceflavor?timeout=10s": context deadline exceeded
webhook not ready, retrying in 5s
namespace/kueue-dra unchanged
resourceflavor.kueue.x-k8s.io/spark-gb10 created
clusterqueue.kueue.x-k8s.io/gpu-cq configured
localqueue.kueue.x-k8s.io/gpu-lq unchanged
resourceclaimtemplate.resource.k8s.io/single-gpu configured
resourceclaimtemplate.resource.k8s.io/two-gpus configured
==> done

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl get nodes; kubectl get resourceslice
NAME                STATUS   ROLES           AGE     VERSION
dra-control-plane   Ready    control-plane   3m10s   v1.37.0
dra-worker          Ready    <none>          2m56s   v1.37.0
NAME                                    NODE         DRIVER           POOL         AGE
00000-gpu.nvidia.com-dra-worker-22nr6   dra-worker   gpu.nvidia.com   dra-worker   2m36s

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl get clusterqueue,resourceflavor; kubectl -n kueue-dra get localqueue,resourceclaimtemplate
NAME                                 COHORT   PENDING WORKLOADS
clusterqueue.kueue.x-k8s.io/gpu-cq            0

NAME                                       AGE
resourceflavor.kueue.x-k8s.io/spark-gb10   0s
NAME                               CLUSTERQUEUE   PENDING WORKLOADS   ADMITTED WORKLOADS
localqueue.kueue.x-k8s.io/gpu-lq   gpu-cq         0                   0

NAME                                               AGE
resourceclaimtemplate.resource.k8s.io/single-gpu   6s
resourceclaimtemplate.resource.k8s.io/two-gpus     6s
```

## 13. 参考资料

- NVIDIA DRA Driver：<https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu>，文档 <https://dra-driver-nvidia-gpu.sigs.k8s.io/docs/>
- Kubernetes DRA：<https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/>
- Kueue DRA 概念：<https://kueue.sigs.k8s.io/docs/concepts/dynamic_resource_allocation/>
- Kueue DRA 配置：<https://kueue.sigs.k8s.io/docs/tasks/manage/setup_dra/>
- KEP-5004 DRA 扩展资源：<https://github.com/kubernetes/enhancements/issues/5004>
