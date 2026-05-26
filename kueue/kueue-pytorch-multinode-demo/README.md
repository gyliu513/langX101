# Kueue + PyTorch 多节点 DDP 训练 Demo（2 节点 × 2 GPU = 4 进程）

> **依赖**：仅 Kueue + 标准 Kubernetes Service，无需 Kubeflow / JobSet / KubeRay

## 概述

本 Demo 演示如何用**最少的依赖**在 Kubernetes 上运行真正的多节点 PyTorch DDP 训练：

- **2 个 Pod**，每个 Pod 模拟一个训练节点，运行 `torchrun --nproc_per_node=2`
- **4 个进程**（world_size=4），跨 Pod 通过 gloo/nccl 进行梯度 all-reduce
- 使用 `batch/v1 Job` 的 **`completionMode: Indexed`** 为每个 Pod 分配稳定的节点编号
- 使用 **Headless Service** 为 master Pod（index=0）提供稳定 DNS，解决多节点 rendezvous 问题
- CPU demo 可在 kind 等本地集群直接运行；**切换到 GPU 只需修改 2 处**

## 架构

```
                    Kueue ClusterQueue
                    (统一管理配额与调度)
                           │
              job-pytorch-multinode-training-xxxxx
                    (Kueue Workload)
                           │
          ┌────────────────┴────────────────┐
          │                                 │
  Pod-0 (index=0)                   Pod-1 (index=1)
  NODE_RANK=0                        NODE_RANK=1
  ┌──────────────────┐               ┌──────────────────┐
  │ torchrun         │               │ torchrun         │
  │  Rank 0 (GPU 0)  │               │  Rank 2 (GPU 0)  │
  │  Rank 1 (GPU 1)  │               │  Rank 3 (GPU 1)  │
  └────────┬─────────┘               └─────────┬────────┘
           │                                   │
           └─────── gloo/nccl all-reduce ───────┘
                 (跨 Pod 梯度同步)

  pytorch-master-svc (Headless Service)
    → 选中 index=0 的 Pod
    → DNS: pytorch-master-svc.default.svc.cluster.local
    → 所有 Pod 的 --master_addr 指向此 DNS
```

## 核心设计

### 问题：多节点如何互相发现？

单节点训练时 `--master_addr=localhost` 即可，但多节点时 Pod-1 需要知道 Pod-0 的地址。

### 解决方案：Indexed Job + Headless Service

| 机制 | 作用 |
|------|------|
| `completionMode: Indexed` | 每个 Pod 自动获得 `JOB_COMPLETION_INDEX` 环境变量（0 或 1） |
| Headless Service（选中 index=0） | 为 Pod-0 提供稳定 DNS，作为 `MASTER_ADDR` |
| `--node_rank=${JOB_COMPLETION_INDEX}` | torchrun 知道当前节点是第几个节点 |

## 文件说明

| 文件 | 说明 |
|------|------|
| `00-kueue-resources.yaml` | ResourceFlavor、ClusterQueue、LocalQueue |
| `01-master-service.yaml` | Headless Service，选中 index=0 的 Pod |
| `02-pytorch-multinode-job.yaml` | Indexed Job，2 个 Pod，每 Pod 2 个进程 |

## 前置条件

- Kubernetes 集群（kind、minikube 或真实集群）
- Kueue 已安装（`kueue.x-k8s.io/v1beta2`）

安装 Kueue：
```bash
kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.11.4/manifests.yaml
```

## 运行步骤

### 1. 创建 Kueue 资源

```bash
kubectl apply -f 00-kueue-resources.yaml
```

### 2. 创建 Master Service

```bash
kubectl apply -f 01-master-service.yaml
```

验证 Service：
```bash
kubectl get svc pytorch-master-svc -n default
# NAME                 TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)     AGE
# pytorch-master-svc   ClusterIP   None         <none>        29500/TCP   5s
```

### 3. 提交训练 Job

```bash
kubectl apply -f 02-pytorch-multinode-job.yaml
```

### 4. 观察调度过程

```bash
# Kueue Workload 状态
kubectl get workloads -n default

# Job 状态
kubectl get jobs -n default

# 两个 Pod（index 0 和 index 1）
kubectl get pods -n default -o wide
```

预期输出：
```
NAME                                   QUEUE                  ADMITTED   FINISHED
job-pytorch-multinode-training-xxxxx   multinode-user-queue   True

NAME                                  STATUS    COMPLETIONS   AGE
pytorch-multinode-training            Running   0/2           10s

NAME                                  READY   STATUS    NODE
pytorch-multinode-training-0-xxxxx    1/1     Running   node-1    # index=0, master
pytorch-multinode-training-1-xxxxx    1/1     Running   node-2    # index=1, worker
```

### 5. 查看训练日志

```bash
# 查看所有 Pod 的日志（加 --prefix 显示 Pod 来源）
kubectl logs -f -l job-name=pytorch-multinode-training -n default --prefix
```

### 6. 预期输出

```
[pod/.../trainer] [Pod 0] Launching torchrun: 2 nodes x 2 processes, node_rank=0
[pod/.../trainer] [Pod 1] Launching torchrun: 2 nodes x 2 processes, node_rank=1
[pod/.../trainer] [Rank 0/4] node=0  local_rank=0  master=pytorch-master-svc...:29500
[pod/.../trainer] [Rank 1/4] node=0  local_rank=1  master=pytorch-master-svc...:29500
[pod/.../trainer] [Rank 2/4] node=1  local_rank=0  master=pytorch-master-svc...:29500
[pod/.../trainer] [Rank 3/4] node=1  local_rank=1  master=pytorch-master-svc...:29500
[pod/.../trainer] [Rank 0/4] Process group initialized
...（4 个 Rank 并行训练）...
[pod/.../trainer] [Rank 0/4] Epoch  1/10  loss=4.0374  w=2.1221  b=1.2110
[pod/.../trainer] [Rank 2/4] Epoch  1/10  loss=3.7041  w=2.1221  b=1.2110
...
[pod/.../trainer] ═══════════════════════════════════════════════════
[pod/.../trainer]   Multi-node DDP training complete
[pod/.../trainer]   world_size=4 (2 nodes × 2 processes/node)
[pod/.../trainer]   Learned : w=3.0028  b=2.0004
[pod/.../trainer]   Target  : w=3.0000  b=2.0000
[pod/.../trainer]   Error   : Δw=0.0028  Δb=0.0004
[pod/.../trainer] ═══════════════════════════════════════════════════
```

关键观察点：
- **4 个 Rank 的 `w`/`b` 在每个 Epoch 结束后完全相同** → 跨 Pod 的梯度 all-reduce 正确
- Rank 0、1 来自 Pod-0（node=0），Rank 2、3 来自 Pod-1（node=1）
- 每个 Rank 只处理 500 条样本（2000 / 4）

### 7. 清理

```bash
kubectl delete -f 02-pytorch-multinode-job.yaml
kubectl delete -f 01-master-service.yaml
kubectl delete -f 00-kueue-resources.yaml
```

## 切换到真实 GPU（2 节点 × 2 GPU = 4 GPU）

只需修改 `02-pytorch-multinode-job.yaml` 中 **2 处**：

**1. 训练脚本：gloo → nccl**
```python
# 修改前
dist.init_process_group(backend="gloo")
device = torch.device("cpu")

# 修改后
dist.init_process_group(backend="nccl")
device = torch.device(f"cuda:{local_rank}")
model = model.to(device)
```

**2. 容器资源：加 GPU 请求**
```yaml
resources:
  limits:
    nvidia.com/gpu: "2"   # 取消注释
```

**3. ClusterQueue 加 GPU 配额**（`00-kueue-resources.yaml`）：
```yaml
coveredResources: ["cpu", "memory", "nvidia.com/gpu"]
# 在 flavors 中加：
- name: nvidia.com/gpu
  nominalQuota: "4"
```

**4. 可选：Pod 反亲和性**（确保 2 个 Pod 落在不同 GPU 节点）
取消 Job YAML 中 `affinity` 部分的注释。

## torchrun 环境变量说明

| 变量 | 来源 | 说明 |
|------|------|------|
| `JOB_COMPLETION_INDEX` | Kubernetes (Indexed Job) | Pod 的节点编号（0 或 1） |
| `RANK` | torchrun | 进程的全局 rank（0-3） |
| `LOCAL_RANK` | torchrun | 进程在当前节点的 rank（0 或 1） |
| `WORLD_SIZE` | torchrun | 总进程数（4） |
| `GROUP_RANK` | torchrun | 节点编号（等同于 NODE_RANK） |
| `MASTER_ADDR` | torchrun（从命令行参数） | master 地址（Headless Service DNS） |

## 与 kueue-pytorch-ddp-demo 的对比

| | kueue-pytorch-ddp-demo | 本 Demo |
|--|------------------------|---------|
| 节点数 | 1 个 Pod | **2 个 Pod** |
| 进程数 | 2（world_size=2） | **4（world_size=4）** |
| 跨 Pod 通信 | 无（Pod 内） | **有（通过 Headless Service）** |
| 额外资源 | 无 | 1 个 Headless Service |
| 适用场景 | 单机多卡验证 | **生产多节点多卡训练** |
