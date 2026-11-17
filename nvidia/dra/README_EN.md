# Testing NVIDIA DRA (and Kueue + DRA) on a DGX Spark with kind

[中文版](README.md)

This guide builds a Kubernetes cluster with **kind** on an **NVIDIA DGX Spark (GB10, arm64)** and installs the
**NVIDIA DRA Driver for GPUs**. Five examples then show how DRA (Dynamic Resource Allocation) hands GPUs to Pods.
After that it installs **Kueue**, checks how Kueue supports DRA, and adds Kueue + DRA examples.

Every command below was run on this Spark on 2026-11-16, and the output is pasted unedited. Long output is cut
with a `...` line.

## Contents

- [1. Background: what DRA is and how it differs from a device plugin](#1-background-what-dra-is-and-how-it-differs-from-a-device-plugin)
- [2. Test environment and versions](#2-test-environment-and-versions)
- [3. Directory layout](#3-directory-layout)
- [4. Step 0: check the host](#4-step-0-check-the-host)
- [5. Step 1: create the kind cluster and pass the GPU into a node](#5-step-1-create-the-kind-cluster-and-pass-the-gpu-into-a-node)
- [6. Step 2: install the NVIDIA DRA driver](#6-step-2-install-the-nvidia-dra-driver)
- [7. Step 3: DRA on its own (examples 1–5)](#7-step-3-dra-on-its-own-examples-15)
- [8. Step 4: does Kueue support DRA?](#8-step-4-does-kueue-support-dra)
- [9. Step 5: install Kueue and enable the DRA mapping](#9-step-5-install-kueue-and-enable-the-dra-mapping)
- [10. Step 6: Kueue + DRA examples (examples 6–9)](#10-step-6-kueue--dra-examples-examples-69)
- [11. Pitfalls and findings](#11-pitfalls-and-findings)
- [12. Cleanup](#12-cleanup)
- [13. References](#13-references)

## 1. Background: what DRA is and how it differs from a device plugin

The classic approach is a **device plugin**. The node reports an integer resource such as `nvidia.com/gpu: 1`,
and a Pod puts a number in `resources.limits`. The scheduler only sees a count. It does not know the GPU model,
its compute capability, or whether the GPU should be shared.

**DRA** treats GPUs as devices that have attributes. It is GA since Kubernetes 1.34, in API group `resource.k8s.io/v1`.

| Object | Created by | Purpose |
|---|---|---|
| `DeviceClass` | the driver (Helm chart) | A class of devices, e.g. `gpu.nvidia.com` |
| `ResourceSlice` | the driver's kubelet plugin | Which devices each node has, plus each device's attributes (model, architecture, UUID, CUDA version, …) |
| `ResourceClaim` | a user or the scheduler | "I need one device that matches these conditions." The result is written to `status.allocation`. |
| `ResourceClaimTemplate` | a user | Creates a separate ResourceClaim for each Pod. The claim is deleted together with the Pod. |

The flow:

```
              ┌─────────────── kube-scheduler ───────────────┐
 Pod ──refs──▶│ ResourceClaim(Template)  +  ResourceSlice     │──▶ writes claim.status.allocation
              │ (CEL selectors / count / DeviceClass)        │    (which GPU on which node)
              └───────────────────────────────────────────────┘
                                   │ Pod bound to the node
                                   ▼
 kubelet ──NodePrepareResources──▶ NVIDIA DRA kubelet plugin (gpu.nvidia.com)
                                   │ applies GpuConfig (time-slicing / MPS …), writes a CDI spec
                                   ▼
 containerd ──CDI device name──▶ injects /dev/nvidia* and the driver libraries into the container
```

DRA adds several things a device plugin does not have:
- picking devices by attribute with CEL expressions;
- several Pods or containers sharing one claim;
- driver-specific configuration such as time-slicing, MPS and MIG;
- lifecycle management for claims.

## 2. Test environment and versions

| Component | Version |
|---|---|
| Hardware | NVIDIA DGX Spark (`spark-3bee`), 1 × GB10 (Blackwell, compute capability 12.1, 128 GB unified memory), aarch64 |
| OS / driver | Ubuntu 24.04.5, NVIDIA driver 580.173.02, CUDA 13.0 |
| Containers | Docker 29.2.1 (default runtime = `nvidia`), NVIDIA Container Toolkit 1.20.0 |
| kind | v0.33.0, node image `kindest/node:v1.37.0` (containerd 2.3.4) |
| kubectl / helm | v1.37.0 / v3.22.0 |
| NVIDIA DRA Driver | **v0.5.1** (`oci://registry.k8s.io/dra-driver-nvidia/charts/dra-driver-nvidia-gpu`, arm64 images available) |
| Kueue | **v0.20.6** (released 2026-11-12, latest) |

> Note: the NVIDIA DRA driver project moved to `kubernetes-sigs/dra-driver-nvidia-gpu`, and its version numbers
> went from `v25.x` to `v0.x`. Images and the chart are now published under `registry.k8s.io/dra-driver-nvidia/`.

## 3. Directory layout

```
nvidia/dra/
├── README.md / README_EN.md            # this guide (Chinese / English)
├── kind/
│   ├── kind-config.yaml                # kind cluster: 1 control-plane + 1 worker with the GPU
│   └── dra-driver-values.yaml          # Helm values for the DRA driver
├── manifests/                          # DRA on its own
│   ├── 00-namespace.yaml
│   ├── 01-single-gpu-claim-template.yaml   # ex 1: ResourceClaimTemplate, one Pod gets one GPU
│   ├── 02-exclusive-two-pods.yaml          # ex 2: two Pods each want a GPU (exclusive, 2nd Pending)
│   ├── 03-shared-claim.yaml                # ex 3: two Pods share one ResourceClaim
│   ├── 04-cel-selector.yaml                # ex 4: select a GPU by attribute with CEL
│   └── 05-time-slicing.yaml                # ex 5: time-slicing via GpuConfig
├── kueue/                              # Kueue + DRA
│   ├── controller_manager_config.yaml      # Kueue config (release default + deviceClassMappings)
│   ├── 10-queues.yaml                      # ResourceFlavor / ClusterQueue / LocalQueue / templates
│   ├── 11-gpu-jobs.yaml                    # ex 6: two Jobs compete for a quota of 1 GPU
│   ├── 12-too-big-job.yaml                 # ex 7: one Job asks for 2 GPUs (over the quota)
│   ├── 13-direct-claim-job.yaml            # ex 8: references a ResourceClaim directly (not supported)
│   └── 14-extended-resource.yaml           # ex 9: classic nvidia.com/gpu syntax, served by DRA
└── scripts/
    ├── setup.sh                        # one shot: cluster + driver + Kueue
    └── cleanup.sh                      # delete the cluster, check the GPU state
```

All commands below run on the Spark, inside `~/nvidia-dra-demo`, which is a copy of this directory:

```console
gyliu-cary@gyliu513-MacBook-Pro-2 dra % rsync -a ./ mygpu:~/nvidia-dra-demo/
```

## 4. Step 0: check the host

The DRA driver relies on the host's NVIDIA driver and on the NVIDIA Container Toolkit. First check the
architecture, the GPU and the driver:

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

> GB10 uses unified memory, so `nvidia-smi` shows `Not Supported` in the memory column. A ComfyUI process
> already holds about 40 GB of unified memory. The test workloads here are tiny (`nvidia-smi`, vectorAdd,
> nbody), so they can run next to it.

Docker's default runtime must be `nvidia`, and `accept-nvidia-visible-devices-as-volume-mounts` must be `true`.
kind has no `--gpus` flag. Instead, that setting lets a single bind mount pass the GPU into the kind node container
(see the next step):

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ docker info --format "Server: {{.ServerVersion}}  DefaultRuntime: {{.DefaultRuntime}}  CgroupDriver: {{.CgroupDriver}}"
Server: 29.2.1  DefaultRuntime: nvidia  CgroupDriver: systemd

gyliu@spark-3bee:~/nvidia-dra-demo$ nvidia-ctk --version
NVIDIA Container Toolkit CLI version 1.20.0
commit: 5505e2f94d9aaa08561490db974ba3cd676af209

gyliu@spark-3bee:~/nvidia-dra-demo$ grep -E "^accept-nvidia-visible-devices-as-volume-mounts" /etc/nvidia-container-runtime/config.toml
accept-nvidia-visible-devices-as-volume-mounts = true
```

If either setting is wrong, you can fix it like this. This restarts Docker, which restarts every container:

```bash
sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
sudo nvidia-ctk config --set accept-nvidia-visible-devices-as-volume-mounts=true --in-place
sudo systemctl restart docker
```

kind, kubectl and helm live in `~/bin`. Install guides: [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation),
[kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/), [helm](https://helm.sh/docs/intro/install/).
Download the `linux/arm64` builds, and use helm v3 rather than v4.

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kind version; kubectl version --client; helm version --short
kind v0.33.0 go1.26.7 linux/arm64
Client Version: v1.37.0
Kustomize Version: v5.8.1
v3.22.0+g144ca65
```

## 5. Step 1: create the kind cluster and pass the GPU into a node

The kind config is [kind/kind-config.yaml](kind/kind-config.yaml). It is based on upstream's
`demo/clusters/kind/scripts/kind-cluster-config.yaml`, trimmed for a single-GPU Spark:

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

Key points:

1. **No feature gates needed.** DRA is GA since Kubernetes 1.34, and `resource.k8s.io/v1` is on by default.
   Upstream's `featureGates: DynamicResourceAllocation` and `runtime-config: resource.k8s.io/v1beta1` are for
   older releases.
2. **`enable_cdi = true`.** The DRA kubelet plugin gives kubelet CDI device names, such as
   `k8s.gpu.nvidia.com/claim=<uid>-gpu-0`. containerd needs CDI enabled to turn these into device nodes and mounts.
   In containerd 2.x the plugin is named `io.containerd.cri.v1.runtime`; in 1.x it was `io.containerd.grpc.v1.cri`.
3. **GPU injection.** The mount with `containerPath: /var/run/nvidia-container-devices/cdi/runtime.nvidia.com/gpu/all`
   makes the nvidia runtime inject every host GPU (device nodes, driver libraries and `nvidia-smi`) into the
   `dra-worker` node container. Only the worker gets the GPU; the control-plane does not need one.
4. **Mount `nvidia-ctk`.** The CDI spec that the driver generates calls `nvidia-ctk hook ...`, and the kind node
   image does not ship that binary.
5. Upstream also mounts `/run/nvidia-fabricmanager/socket` and `/dev/vfio`. The Spark has no NVSwitch and no VFIO
   devices, so those mounts were dropped.

Create the cluster:

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

Check that the worker node container sees the GPU, the device nodes and `nvidia-ctk`, and that CDI is on in
containerd:

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

Check that the DRA API is served and the related feature gates are on (`stage=""` means GA):

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

## 6. Step 2: install the NVIDIA DRA driver

The Helm values are in [kind/dra-driver-values.yaml](kind/dra-driver-values.yaml):

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

- `gpuResourcesEnabledOverride: true`: upstream does not yet officially support GPU allocation (ComputeDomains are
  supported). Without this override the chart does not enable the GPU kubelet plugin.
- `computeDomains.enabled: false`: ComputeDomains are for Multi-Node NVLink (IMEX). A single Spark cannot use them.
- `TimeSlicingSettings: true`: example 5 sets time-slicing through `GpuConfig`. Without this gate, the claim fails
  to prepare (see [Pitfalls](#11-pitfalls-and-findings)).

Install. The chart is published as an OCI artifact, so you do not need `helm repo add`:

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

There is only one DaemonSet Pod (`kubelet-plugin`). ComputeDomains are off, so there is no controller Pod.

The DeviceClasses that the driver registers:

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

Note that `gpu.nvidia.com` already sets `extendedResourceName: nvidia.com/gpu`. This means a Pod that uses the
classic `limits: {nvidia.com/gpu: 1}` syntax also gets its GPU through DRA, because `DRAExtendedResource` is GA in
Kubernetes 1.37. Example 9 relies on this.

The ResourceSlice that the kubelet plugin publishes for `dra-worker` lists every GB10 attribute:

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

> GB10 uses unified memory, so the ResourceSlice has **no `capacity.memory`**. On a discrete GPU such as an H100,
> this field holds the memory size and you can write CEL rules on it. On the Spark you can only select by
> attributes such as `productName`, `architecture` and `cudaComputeCapability`.

## 7. Step 3: DRA on its own (examples 1–5)

### Example 1: ResourceClaimTemplate, one Pod gets one GPU

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

- Inside the container, `nvidia-smi -L` lists the GB10 and CUDA vectorAdd prints `Test PASSED`. So the GPU was
  injected through DRA and it really computes.
- `NVIDIA_VISIBLE_DEVICES=void` shows that the nvidia runtime's environment variable did not inject the GPU.
  The DRA plugin injected it through CDI.

The scheduler created a ResourceClaim for the Pod from the template, named `<pod>-<claim>-<random suffix>`.
When the Pod finished, the claim was released and deleted automatically:

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get pod gpu-pod -o jsonpath="{.status.resourceClaimStatuses}"; echo
[{"name":"gpu","resourceClaimName":"gpu-pod-gpu-zpqpb"}]

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo get resourceclaim
No resources found in dra-demo namespace.

gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n dra-demo delete pod gpu-pod
pod "gpu-pod" deleted from dra-demo namespace
```

### Example 2: two Pods, each with its own GPU (exclusive)

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

Both Pods use the same template, but **each one gets its own claim**. A whole-GPU allocation is exclusive and the
Spark has one GPU, so the second Pod stays Pending:

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

The scheduler reports `1 cannot allocate all claims`. The other node is the control-plane, which has a taint.
Once the first Pod is deleted the GPU is free, and the second Pod is scheduled right away:

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

### Example 3: two Pods share one ResourceClaim

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

This time the `ResourceClaim` is created by hand, not from a template, and both Pods reference it with
`resourceClaimName`. All three containers get **the same** GPU (same UUID), and the claim's `reservedFor` lists
both Pods:

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

> A claim referenced with `resourceClaimName` is not deleted together with its Pods; you delete it yourself.
> A shared claim only lets several containers see the same GPU. It does not isolate their compute. For that, use
> time-slicing (example 5), MPS or MIG.

### Example 4: select a GPU by attribute with CEL

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

`blackwell-gpu` asks for `architecture == 'Blackwell'` and compute capability above 12.0, which the GB10 matches.
`h100-gpu` asks for a product name containing `h100`, and this machine has no such GPU:

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

### Example 5: time-slicing through GpuConfig

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

The NVIDIA driver parses the parameters under `config.opaque` (API `resource.nvidia.com/v1beta1`). Two containers
run nbody on the same GPU at the same time:

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

Running alone, this nbody reaches about 16,000 GFLOP/s (see the logs of example 6). Here each container gets
about 7,000 GFLOP/s, which together add up to roughly one GPU. So the two containers really are taking turns on
one GPU.

The kubelet plugin log and the time-slice policy on the host:

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

> Time-slicing is a **GPU-wide setting on the physical GPU** (`nvidia-smi compute-policy --set-timeslice`).
> The driver resets it to `Default` when the claim is released, which is why it already shows `Default` above.
> If host processes also use this GPU (ComfyUI does on this Spark), they are affected while the claim exists.

## 8. Step 4: does Kueue support DRA?

**Yes.** This comes from the Kueue source at tag `v0.20.6` and the official doc
`site/content/en/v0.20/docs/concepts/dynamic_resource_allocation.md`:

| Kueue feature gate | State in v0.20.6 | What it does |
|---|---|---|
| `KueueDRAIntegration` | Beta, on by default since v0.18 (called `DynamicResourceAllocation` before v0.18) | Counts devices from ResourceClaimTemplates against quota |
| `KueueDRAIntegrationExtendedResource` | Beta, on by default since v0.19 | Supports DRA-backed extended resources such as `nvidia.com/gpu` |
| `KueueDRAIntegrationPartitionableDevices` | Beta, on by default | Counter-based quota, e.g. MIG partitions |
| `KueueDRAIntegrationConsumableCapacity` | Alpha, off | Capacity-based quota |
| `KueueDRAIntegrationPrioritizedList` | Alpha, off | Supports `firstAvailable` |

How it works:

1. In the Kueue configuration, `resources.deviceClassMappings` maps one or more DeviceClasses to a logical resource
   name. This guide maps `gpu.nvidia.com` to `nvidia.com/dra-gpu`.
2. The ClusterQueue lists that logical name in `coveredResources` and gives it a quota.
3. A Job's Pod template asks for devices through a `ResourceClaimTemplate`. Kueue charges the `count` of each
   `exactly` request (default 1) against the quota.

Limitations in v0.20.6:

- **Only `ResourceClaimTemplate` is supported.** A Workload that references a `ResourceClaim` directly is marked
  inadmissible (example 8 shows this).
- Only `allocationMode: ExactCount` is supported. `allocationMode: All`, `constraints` (matchAttribute) and a
  per-request `config` are not.
- CEL selectors are supported. Kueue checks them against the ResourceSlices to make sure some device can match.
- Kueue only handles quota, not which GPU is picked; kube-scheduler still chooses the device. Upstream recommends
  `waitForPodsReady` as a safety net.
- **The configuration is read only at startup.** After changing the ConfigMap you must restart
  `kueue-controller-manager`.
- A DeviceClass can map to only one logical resource name.

## 9. Step 5: install Kueue and enable the DRA mapping

Download and install the Kueue v0.20.6 release manifest. The CRDs are large, so use `--server-side`:

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

The Kueue config, [kueue/controller_manager_config.yaml](kueue/controller_manager_config.yaml), is the default
config from the release manifest with `resources.deviceClassMappings` added at the end:

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

Replace the `kueue-manager-config` ConfigMap with this file and restart the controller, because Kueue reads its
config only at startup:

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

Check that the new Pod loaded the DRA mapping. Kueue prints its full config to the log at startup:

```console
gyliu@spark-3bee:~/nvidia-dra-demo$ kubectl -n kueue-system logs deploy/kueue-controller-manager | grep -m1 -o "resources:.n  deviceClassMappings:.*name: nvidia.com/dra-gpu" | sed "s/\\\\n/\\n/g"
resources:
  deviceClassMappings:
  - deviceClassNames:
    - gpu.nvidia.com
    name: nvidia.com/dra-gpu
```

> **Wait a few seconds after the restart before creating Kueue objects.** The new Pod can be Ready before its webhook
> serves requests. If you create a ResourceFlavor at that moment, it fails with
> `failed calling webhook "mresourceflavor.kb.io" ... context deadline exceeded`. This happened on the first
> recording run. Wait until the old Pod is gone, then retry.

## 10. Step 6: Kueue + DRA examples (examples 6–9)

The queues: one ClusterQueue with a quota of 1 `nvidia.com/dra-gpu`, because the Spark has one GB10:

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

### Example 6: two Jobs compete for a quota of 1 GPU

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

Compare with example 2:

- Example 2 (no Kueue): the second Pod exists and sits Pending in the scheduler. Its ResourceClaim also exists, in
  state `pending`.
- Example 6 (with Kueue): Job `train-b` is **Suspended**, with **no Pod and no ResourceClaim**. It waits in Kueue
  with the reason `insufficient unused quota for nvidia.com/dra-gpu ... 1 more needed`.

The ClusterQueue's usage and the admission of `train-a`'s Workload show that Kueue turned the DRA device into
`nvidia.com/dra-gpu: 1`:

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

When `train-a` finishes it releases the quota. Kueue then unsuspends `train-b`, and only now are its Pod and
ResourceClaim created:

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

### Example 7: one Job asks for 2 GPUs (more than the quota allows)

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

The claim says `count: 2`, so Kueue computes 2 `nvidia.com/dra-gpu`. That is more than the ClusterQueue's limit of
1, so the reason is `ExceedsMaxQuota`. The Job stays Suspended: it never creates a Pod and never takes up
scheduler time.

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

### Example 8: a Job that references a ResourceClaim directly (not supported)

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

The Workload is marked `Misconfigured` / `Inadmissible` with the message
`KueueDRAIntegration feature does not support use of resource claims`. With Kueue, use a `ResourceClaimTemplate`.

### Example 9: the extended-resource syntax (`nvidia.com/gpu: 1`) also uses DRA and shares the same quota

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

These two Jobs have no ResourceClaimTemplate. They only set `limits: nvidia.com/gpu: 1`, the same syntax a device
plugin uses. Here is how that plays out:
- `gpu.nvidia.com` sets `extendedResourceName: nvidia.com/gpu`, so the scheduler creates a
  `<pod>-extended-resources-xxxxx` ResourceClaim for the Pod automatically.
- Kueue knows that `nvidia.com/gpu` is backed by `gpu.nvidia.com`, which is mapped to `nvidia.com/dra-gpu`.
- So Kueue charges `nvidia.com/dra-gpu: 1`, the same quota that example 6 uses.

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

> If `gpu.nvidia.com` is **not** in `deviceClassMappings`, Kueue charges the extended resource name
> `nvidia.com/gpu` instead. The ClusterQueue then needs a quota for `nvidia.com/gpu` too, otherwise the Workload
> fails with `resource nvidia.com/gpu unavailable in ClusterQueue`; this happened during testing. Don't give the
> same GPU a separate quota under two logical names, or Kueue will think there are two GPUs.

## 11. Pitfalls and findings

1. **Time-slicing needs the `TimeSlicingSettings` feature gate.** Without it the Pod stays in `ContainerCreating`
   and the event says:
   ```text
   Warning  FailedPrepareDynamicResources  kubelet  Failed to prepare dynamic resources: ... error validating GPU config:
   "TimeSlicing" is selected as the GPU sharing strategy, but the "TimeSlicingSettings" feature gate is not enabled
   ```
   Add `featureGates.TimeSlicingSettings: true` to the Helm values and run `helm upgrade`.

2. **MPS does not work on this Spark and is risky on a shared GPU, so it is not one of the examples.**
   This was tested with `featureGates.MPSSupport: true` and a GpuConfig with `sharing.strategy: MPS` (upstream
   `gpu-test-mps.yaml`):
   - The driver starts an `mps-control-daemon-<claim-uid>` Deployment for the claim. With `nvidiaDriverRoot=/`,
     the v0.5.1 template takes the `chroot /driver-root` branch. That branch **never sets
     `CUDA_MPS_PIPE_DIRECTORY`**, so the daemon stays in CrashLoopBackOff:
     ```text
     CUDA_MPS_PIPE_DIRECTORY must be set to start or to communicate with MPS control daemon
     ```
     In `templates/mps-control-daemon.tmpl.yaml`, only the non-chroot branch exports the MPS variables.
   - **More importantly**, starting MPS switches the whole physical GPU to `EXCLUSIVE_PROCESS` compute mode.
     ComfyUI also uses this GPU on the Spark, and in that mode it could no longer create new CUDA contexts.
   - After the prepare failed and the Pod and claim were deleted, the driver **did not clean up**. The Deployment
     stayed, and the GPU stayed in `Exclusive_Process`. Recovery had to be done by hand:
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
   Conclusion: don't test MPS on a GPU that other programs share. `scripts/cleanup.sh` ends by checking the compute
   mode and the time-slice policy.

3. **GB10's ResourceSlice has no memory capacity** (unified memory), so CEL selectors cannot use
   `device.capacity[...].memory`.

4. **kind nodes have no `nvidia-ctk`**, but the CDI spec that the driver generates calls its hook, so mount it
   from the host (`/usr/bin/nvidia-ctk`).

5. **`rollout status` on the driver's new DaemonSet returns success at once**, before any Pod exists. Wait until
   the Pod appears, then run `kubectl wait --for=condition=Ready`. The ResourceSlice also takes a few more seconds
   to appear.

6. **Kueue reads its config only at startup.** After changing `deviceClassMappings` you must `rollout restart`.
   Creating objects right after the restart can hit a webhook that is not ready yet (see section 9).

7. **Kueue + DRA only supports ResourceClaimTemplates.** Kueue cannot manage several Pods sharing one GPU through
   a single claim, as in example 3.

8. **The project was renamed.** The NVIDIA DRA driver is now `kubernetes-sigs/dra-driver-nvidia-gpu`, the chart is
   `oci://registry.k8s.io/dra-driver-nvidia/charts/dra-driver-nvidia-gpu`, and version numbers restarted at
   v0.4.0. Many older articles use the `nvidia/k8s-dra-driver-gpu` Helm repo and `v25.x` versions.

## 12. Cleanup

[scripts/cleanup.sh](scripts/cleanup.sh) deletes the kind cluster and checks that the physical GPU's compute mode
and time-slice policy are back to their defaults:

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

[scripts/setup.sh](scripts/setup.sh) rebuilds the whole environment in one go (kind cluster + DRA driver + Kueue +
queues). That is how the environment was rebuilt at the end of this guide:

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

## 13. References

- NVIDIA DRA Driver: <https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu>, docs <https://dra-driver-nvidia-gpu.sigs.k8s.io/docs/>
- Kubernetes DRA: <https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/>
- Kueue DRA concepts: <https://kueue.sigs.k8s.io/docs/concepts/dynamic_resource_allocation/>
- Kueue DRA setup: <https://kueue.sigs.k8s.io/docs/tasks/manage/setup_dra/>
- KEP-5004 DRA extended resources: <https://github.com/kubernetes/enhancements/issues/5004>
