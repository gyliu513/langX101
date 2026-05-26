# Kueue + PyTorch DDP 数据并行训练 Demo

> **依赖**：仅需 Kueue，无需 Kubeflow / JobSet / KubeRay

## 概述

本 Demo 演示如何用**最简单的方式**通过 Kueue 调度 PyTorch 分布式数据并行（DDP）训练任务：

- 使用原生 `batch/v1 Job`，Job 上打 `kueue.x-k8s.io/queue-name` 标签即可接入 Kueue 调度
- 单 Pod 内用 `torchrun --nproc_per_node=2` 启动 2 个训练进程，模拟数据并行
- 使用 `gloo` 通信后端，**纯 CPU 可运行**，无需 GPU
- 训练任务：合成数据集上的线性回归（目标函数 `y = 3x + 2`），验证 DDP 梯度同步正确性

## 架构

```
┌─────────────────────────────────────────────────┐
│  batch/v1 Job  (kueue.x-k8s.io/queue-name: ...)│
│  ┌──────────────────────────────────────────┐   │
│  │  Pod                                     │   │
│  │  ┌──────────────┐  ┌──────────────┐     │   │
│  │  │  torchrun    │  │  torchrun    │     │   │
│  │  │  Rank 0      │  │  Rank 1      │     │   │
│  │  │  500 samples │  │  500 samples │     │   │
│  │  └──────┬───────┘  └──────┬───────┘     │   │
│  │         └────── gloo ─────┘             │   │
│  │           (all-reduce 梯度)              │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
         ↑ Kueue Workload 调度管理
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `00-kueue-resources.yaml` | ResourceFlavor、ClusterQueue、LocalQueue |
| `01-pytorch-ddp-job.yaml` | PyTorch DDP 训练 Job（含内联训练脚本） |

## 前置条件

- Kubernetes 集群（kind、minikube 均可）
- Kueue 已安装（`kueue.x-k8s.io/v1beta2`）

Kueue 安装：
```bash
kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.11.4/manifests.yaml
```

## 运行步骤

### 1. 创建 Kueue 队列资源

```bash
kubectl apply -f 00-kueue-resources.yaml
```

验证：
```bash
kubectl get clusterqueue pytorch-cluster-queue
kubectl get localqueue pytorch-user-queue -n default
```

### 2. 提交训练 Job

```bash
kubectl apply -f 01-pytorch-ddp-job.yaml
```

### 3. 观察 Kueue 调度过程

```bash
# 查看 Workload（Kueue 调度单元）
kubectl get workloads -n default

# 查看 Job 状态
kubectl get jobs -n default

# 查看 Pod 状态
kubectl get pods -n default
```

### 4. 查看训练日志

```bash
kubectl logs -f -l job-name=pytorch-ddp-training -n default
```

### 5. 预期输出

```
[Setup] Installing PyTorch (CPU)...
[Setup] PyTorch installed.
[Setup] Launching torchrun with 2 processes (DDP, gloo/CPU)...
[Rank 0/2] Process started
[Rank 1/2] Process started
[Rank 0/2] Dataset: 1000 samples → 500 samples/rank, 16 batches/epoch
[Rank 1/2] Dataset: 1000 samples → 500 samples/rank, 16 batches/epoch
[Rank 0/2] Starting DDP training  lr=0.05  epochs=10  backend=gloo
[Rank 1/2] Starting DDP training  lr=0.05  epochs=10  backend=gloo
[Rank 0/2] Epoch  1/10  loss=6.0214  w=2.3653  b=1.5546
[Rank 1/2] Epoch  1/10  loss=5.8276  w=2.3653  b=1.5546
...
[Rank 0/2] Epoch 10/10  loss=0.0104  w=3.0015  b=1.9930

═══════════════════════════════════════════
  Training complete (DDP, 2 processes)
  Learned : w=3.0015  b=1.9930
  Target  : w=3.0000  b=2.0000
  Error   : Δw=0.0015  Δb=0.0070
═══════════════════════════════════════════
```

关键观察点：
- **两个 Rank 的 `w`、`b` 值在每个 Epoch 结束后完全相同** → DDP all-reduce 梯度同步正确
- 每个 Rank 只看到 500 条样本（数据并行分片）
- Loss 从 6.0 快速收敛到 0.01 → 模型成功学习到 `y = 3x + 2`

### 6. 清理

```bash
kubectl delete -f 01-pytorch-ddp-job.yaml
kubectl delete -f 00-kueue-resources.yaml
```

## DDP 核心原理

| 概念 | 说明 |
|------|------|
| `DistributedSampler` | 将数据集按 Rank 均匀分片，避免数据重复 |
| `DistributedDataParallel` | 包装模型，反向传播时自动 all-reduce 梯度 |
| `gloo` 后端 | CPU 通信后端，无需 GPU / NCCL |
| `torchrun` | 自动设置 `RANK`、`WORLD_SIZE`、`MASTER_ADDR` 等环境变量 |

## 扩展到 GPU

如果集群有 GPU，只需两处修改：

1. 将 `dist.init_process_group(backend="gloo")` 改为 `backend="nccl"`
2. 在 Job spec 中添加 GPU 资源请求：
   ```yaml
   resources:
     limits:
       nvidia.com/gpu: "2"
   ```
   并在 ClusterQueue 中加入 `nvidia.com/gpu` 配额。

## 与 Kubeflow TrainJob 的对比

| | 本 Demo | kueue-trainjob-demo |
|--|---------|---------------------|
| 依赖 | **仅 Kueue** | Kueue + Kubeflow Training Operator v2 + JobSet |
| Job 类型 | `batch/v1 Job` | `trainer.kubeflow.org/v1alpha1 TrainJob` |
| 多节点 | 单节点多进程 | 多节点多进程 |
| 适用场景 | 快速验证、单机多卡 | 生产级多节点分布式训练 |
