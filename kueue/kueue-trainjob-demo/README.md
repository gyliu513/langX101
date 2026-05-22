# Kueue + Kubeflow Trainer v2 TrainJob 端到端测试报告

## 测试概述

| 项目 | 详情 |
|------|------|
| 测试日期 | 2026-05-22 |
| 集群类型 | kind (Kubernetes in Docker) v1.35.0 |
| Kueue 版本 | v0.17.3 |
| Kubeflow Trainer | v2.2.0 |
| JobSet | v0.8.0 |
| 训练算法 | 逻辑回归（SGD + Binary Cross Entropy） |
| 数据集 | 内嵌 2D 二分类数据集（100 样本，纯 Python 无依赖） |
| 测试结果 | **通过** ✅ |

---

## 1. 训练任务说明

### 1.1 任务目的

本 TrainJob 的目标是在 Kubernetes 集群上演示一个**完整的分布式二分类训练任务**，验证以下端到端能力：

- Kueue 能够对 TrainJob 进行资源配额管理和调度准入
- Kubeflow Trainer v2 能够将 TrainJob 展开为 JobSet，并正确注入分布式环境变量
- 两个训练节点能够读取各自的数据分片，执行真实的机器学习训练，并得到有意义的结果

### 1.2 问题定义

**任务：** 给定一个平面上的点 (x1, x2)，判断它属于哪一类。

```
数据集来自两个高斯分布簇：
  Class 1（正例）：以 (+1.5, +1.5) 为中心，标准差 0.6
  Class 0（负例）：以 (-1.5, -1.5) 为中心，标准差 0.6

x2
 3 │      ·  · ·
   │    · ·· ·· ·  ← Class 1（正例）
 1 │      ·· ·
   │- - - - - - - - 决策边界（x1 + x2 ≈ 0）
-1 │   ·· ·
   │ · ·· ·· ·     ← Class 0（负例）
-3 │  · · ·
   └──────────── x1
     -3  -1  1  3
```

两类样本在空间上线性可分，理论最优决策边界为 `w1·x1 + w2·x2 + b = 0`，大致沿 y = -x 方向。

### 1.3 实现的功能

| 功能 | 实现方式 |
|------|---------|
| 数据生成 | 固定 seed=42，纯 Python 高斯采样，100 个样本，两类各 50 个 |
| 数据分片 | 按 `PET_NODE_RANK` 将全量数据切分给各节点，每节点 50 个样本 |
| 前向传播 | `ŷ = sigmoid(w1·x1 + w2·x2 + b)` |
| 损失计算 | 二元交叉熵（Binary Cross-Entropy）：`L = -[y·log(ŷ) + (1-y)·log(1-ŷ)]` |
| 反向传播 | 解析梯度推导，无需自动微分框架 |
| 权重更新 | SGD 逐样本更新，学习率 lr=0.05 |
| 分布式协调 | 依赖 Trainer v2 注入的 `PET_NNODES` / `PET_NODE_RANK` 识别节点身份和数据分片边界 |
| 推理验证 | 训练完成后对 3 个典型点做推理，验证模型泛化能力 |

### 1.4 训练结果

**收敛过程：**

两个节点均在 **Epoch 2** 就达到 100% 准确率，并在后续 epoch 中持续降低损失（模型越来越"确信"）：

```
Epoch  1：loss ≈ 0.27，acc = 98~100%   ← 快速收敛
Epoch  2：loss ≈ 0.087，acc = 100%     ← 完全分类正确
Epoch 10：loss ≈ 0.017，acc = 100%     ← 损失降低 94%，模型置信度持续提升
```

**最终模型能力：**

| 输入点 | 位置描述 | P(class=1) | 预测结果 |
|--------|---------|------------|---------|
| (+2.0, +2.0) | 正例簇中心附近 | 0.998~0.999 | Class 1 ✅ |
| (-2.0, -2.0) | 负例簇中心附近 | 0.001 | Class 0 ✅ |
| (0.0, 0.0) | 决策边界附近 | 0.47~0.49 | 接近 0.5，高度不确定（符合预期）|

原点的预测概率接近 0.5，说明模型正确识别出原点处于决策边界，对两类都无把握——这与数学上的预期完全一致（两类簇对称分布，原点等距）。

**两节点的权重差异与分析：**

两个节点因为各自只看到一半数据（无 AllReduce 梯度同步），最终权重略有不同：

```
Node 0：w1=1.537，w2=1.721  →  更依赖 x2 特征
Node 1：w1=1.777，w2=1.538  →  更依赖 x1 特征
```

这是 **data-parallel 无梯度同步** 的典型现象：Node 0 的数据分片恰好在 x2 方向分布更宽，Node 1 则相反，导致两者各自"偏好"不同特征。尽管权重不同，两者的推理结论完全一致，说明两个模型都找到了正确的决策边界方向（w1 ≈ w2 >> 0，b ≈ 0）。

---

## 2. 架构设计



### 1.1 系统组件关系

```
┌─────────────────────────────────────────────────────────────────┐
│                     kind Cluster (mykueue)                      │
│                                                                  │
│  ┌──────────────┐    ┌─────────────────────────────────────┐   │
│  │ kueue-system │    │         kubeflow-system              │   │
│  │              │    │                                      │   │
│  │  Kueue       │    │  Kubeflow Trainer Controller (v2)   │   │
│  │  Controller  │◄───┤  ─ 管理 TrainJob 生命周期            │   │
│  │  Manager     │    │  ─ 生成 JobSet 资源                  │   │
│  │  v0.17.3     │    │  ─ 注入 PET_* 环境变量               │   │
│  │              │    │                                      │   │
│  └──────┬───────┘    │  JobSet Controller (v0.8.0)          │   │
│         │            │  ─ 管理 ReplicatedJob/Job            │   │
│         │            │  ─ 提供 headless DNS 网络            │   │
│         │            └──────────────────────────────────────┘   │
│         │                                                        │
│  ┌──────▼──────────────────────────────────────────────────┐   │
│  │                    default namespace                      │   │
│  │                                                          │   │
│  │  LocalQueue(user-queue) → ClusterQueue(cluster-queue)   │   │
│  │                                                          │   │
│  │  TrainJob ──(Kueue 设 suspend=false)──▶ JobSet          │   │
│  │     └──▶ Workload（配额排队，不生成 JobSet）              │   │
│  │                                          ↓               │   │
│  │                                    Job(Indexed)          │   │
│  │                                          ↓               │   │
│  │                     Pod[0](Node 0)  +  Pod[1](Node 1)   │   │
│  │                     shard[0:50]        shard[50:100]     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 资源对象层级

```
TrainJob  (trainer.kubeflow.org/v1alpha1)
│  labels: kueue.x-k8s.io/queue-name: user-queue
│  spec.runtimeRef → ClusterTrainingRuntime/torch-distributed-cpu
│  spec.trainer.numNodes: 2
│  spec.suspend: true → false（由 Kueue 在准入后写入）
│
├── Workload  (kueue.x-k8s.io/v1beta1)    [Kueue 创建，用于配额排队]
│   ├── QuotaReserved: cluster-queue       ← 不触发任何业务资源
│   └── Admitted: True                    ← Kueue 将 TrainJob.suspend 改为 false
│
└── JobSet  (jobset.x-k8s.io/v1alpha2)    [Trainer v2 Controller 创建]
    │  触发条件：TrainJob.spec.suspend 变为 false    ← 与 Workload 无直接关系
    └── ReplicatedJob: node (replicas=1, completions=2, parallelism=2)
        └── Job: cpu-distributed-training-node-0    [JobSet Controller 创建]
            ├── Pod[0]  NODE_RANK=0  shard[0:50]    (26 正 / 24 负)
            └── Pod[1]  NODE_RANK=1  shard[50:100]  (24 正 / 26 负)
```

### 1.3 Kueue 调度流程

```
1. kubectl apply TrainJob
       ↓
2. Kueue webhook 拦截 → suspend=true（Job 暂停，不创建 Pod）
       ↓
3. Kueue 创建 Workload 对象（计算资源需求：2×500m CPU, 2×256Mi）
       ↓
4. 检查 ClusterQueue 配额（cpu: 4核 / memory: 8Gi）→ 充足
       ↓
5. QuotaReserved（等待 1s）→ Admitted（等待 0s）
       ↓
6. Kueue 设置 TrainJob.spec.suspend = false
       ↓
7. Trainer Controller 创建 JobSet
       ↓
8. JobSet Controller 创建 Indexed Job（completions=2, parallelism=2）
       ↓
9. Kube-scheduler 调度 Pod[0] 和 Pod[1]
       ↓
10. Trainer v2 通过 Downward API 注入 PET_* 环境变量
       ↓
11. 两个 Pod 并行执行逻辑回归训练（10 epochs）
       ↓
12. JobSet → Completed → TrainJob State: Complete
       ↓
13. Kueue 标记 Workload Finished，释放配额
```

### 1.4 Trainer v2 注入的环境变量

| 环境变量 | 值（示例） | 来源 |
|---------|-----------|------|
| `PET_NNODES` | `2` | mlPolicy.numNodes |
| `PET_NODE_RANK` | `0` / `1` | `batch.kubernetes.io/job-completion-index`（Downward API） |
| `PET_MASTER_ADDR` | `cpu-distributed-training-node-0-0.cpu-distributed-training` | JobSet headless Service DNS |
| `PET_MASTER_PORT` | `29500` | torchrun rendezvous 默认端口 |
| `PET_NPROC_PER_NODE` | `1` | mlPolicy.torch 默认值 |

> `PET_*` 前缀是 PyTorch Elastic Training 约定。真实 PyTorch 训练中，用户通过 `torchrun` 启动脚本，`torchrun` 读取这些变量并设置标准的 `RANK`/`WORLD_SIZE` 供 `torch.distributed` 使用。

---

## 3. 训练数据集设计

### 2.1 数据集说明

| 属性 | 值 |
|------|-----|
| 样本总数 | 100 |
| 特征维度 | 2（x1, x2） |
| 类别数 | 2（二分类） |
| 生成方式 | 固定 seed=42 高斯分布，纯 Python 内嵌 |
| 外部依赖 | 无 |

**Class 1（正例）：** 50 个样本，中心 (+1.5, +1.5)，标准差 0.6
**Class 0（负例）：** 50 个样本，中心 (-1.5, -1.5)，标准差 0.6

```
x2
 3 │      ·  · ·
   │    · ·· ·· ·  ← Class 1
 1 │      ·· ·
   │─────────────── 决策边界
-1 │   ·· ·
   │ · ·· ·· ·     ← Class 0
-3 │  · · ·
   └──────────── x1
     -3  -1  1  3
```

### 2.2 数据分片策略

固定 seed 保证所有 node 生成相同的全量数据集，再按 `PET_NODE_RANK` 切分：

```
全量数据集（100 samples, seed=42 shuffle）
       ├── Node 0 shard: [0:50]  → 26 正例 + 24 负例
       └── Node 1 shard: [50:100] → 24 正例 + 26 负例
```

### 2.3 训练算法

**模型：** 逻辑回归（Logistic Regression）
- 预测：`ŷ = sigmoid(w1·x1 + w2·x2 + b)`
- 损失：Binary Cross Entropy（BCE）
  ```
  L = -[y·log(ŷ) + (1-y)·log(1-ŷ)]
  ```
- 梯度（解析推导）：
  ```
  ∂L/∂w1 = (ŷ - y) · x1
  ∂L/∂w2 = (ŷ - y) · x2
  ∂L/∂b  = (ŷ - y)
  ```
- 更新：`w ← w - lr · ∂L/∂w`（SGD，逐样本更新）
- 学习率：lr = 0.05
- Epochs：10

---

## 4. 测试资源 YAML

### 3.1 Kueue 资源

```yaml
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: ResourceFlavor
metadata:
  name: default-cpu
spec: {}
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: ClusterQueue
metadata:
  name: cluster-queue
spec:
  namespaceSelector: {}
  resourceGroups:
    - coveredResources: ["cpu", "memory"]
      flavors:
        - name: default-cpu
          resources:
            - name: cpu
              nominalQuota: "4"
            - name: memory
              nominalQuota: "8Gi"
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: LocalQueue
metadata:
  name: user-queue
  namespace: default
spec:
  clusterQueue: cluster-queue
```

### 3.2 ClusterTrainingRuntime（核心训练逻辑）

```yaml
apiVersion: trainer.kubeflow.org/v1alpha1
kind: ClusterTrainingRuntime
metadata:
  name: torch-distributed-cpu
  labels:
    trainer.kubeflow.org/framework: torch
spec:
  mlPolicy:
    numNodes: 2
    torch: {}
  template:
    spec:
      replicatedJobs:
        - name: node
          template:
            metadata:
              labels:
                trainer.kubeflow.org/trainjob-ancestor-step: trainer
            spec:
              template:
                spec:
                  containers:
                    - name: node
                      image: python:3.11-slim
                      command: [python3, -c, "<内嵌训练脚本>"]
                      resources:
                        requests: {cpu: "500m", memory: "256Mi"}
                        limits:   {cpu: "1",    memory: "512Mi"}
```

训练脚本关键片段：

```python
# 读取分布式环境变量
world_size = int(os.environ.get("PET_NNODES", "1"))
node_rank  = int(os.environ.get("PET_NODE_RANK", "0"))

# 生成 100 样本（固定 seed=42），按 node_rank 分片
random.seed(42)
dataset = make_cluster(50, 1.5, 1.5, 1) + make_cluster(50, -1.5, -1.5, 0)
random.shuffle(dataset)
shard = dataset[node_rank * 50 : (node_rank + 1) * 50]

# SGD 逻辑回归：10 epochs
w1, w2, b = 0.0, 0.0, 0.0
for epoch in range(10):
    for x1, x2, y in shard:
        pred = sigmoid(w1*x1 + w2*x2 + b)
        err  = pred - y
        w1 -= lr * err * x1
        w2 -= lr * err * x2
        b  -= lr * err
```

### 3.3 TrainJob

```yaml
apiVersion: trainer.kubeflow.org/v1alpha1
kind: TrainJob
metadata:
  name: cpu-distributed-training
  namespace: default
  labels:
    kueue.x-k8s.io/queue-name: user-queue
spec:
  runtimeRef:
    name: torch-distributed-cpu
    kind: ClusterTrainingRuntime
  trainer:
    numNodes: 2
    resourcesPerNode:
      requests: {cpu: "500m", memory: "256Mi"}
      limits:   {cpu: "1",    memory: "512Mi"}
```

---

## 5. 测试步骤

### Step 1：安装组件

```bash
# 安装 Kubeflow Trainer v2 + JobSet
kubectl apply -k "https://github.com/kubeflow/trainer/manifests/overlays/manager?ref=v2.2.0" \
  --server-side
kubectl rollout status deployment/kubeflow-trainer-controller-manager -n kubeflow-system
```

### Step 2：创建 Kueue 资源

```bash
kubectl apply -f 00-kueue-resources.yaml
# resourceflavor.kueue.x-k8s.io/default-cpu created
# clusterqueue.kueue.x-k8s.io/cluster-queue created
# localqueue.kueue.x-k8s.io/user-queue created
```

### Step 3：创建 ClusterTrainingRuntime

```bash
kubectl apply -f 01-cluster-training-runtime.yaml
# clustertrainingruntime.trainer.kubeflow.org/torch-distributed-cpu created
```

### Step 4：提交 TrainJob

```bash
kubectl apply -f 02-trainjob.yaml
# trainjob.trainer.kubeflow.org/cpu-distributed-training created
```

### Step 5：观察调度与执行

```bash
# 查看 Kueue 准入
kubectl get workload -n default
# NAME                                      QUEUE        RESERVED IN     ADMITTED
# trainjob-cpu-distributed-training-a783a   user-queue   cluster-queue   True

# 等待完成
kubectl get trainjob cpu-distributed-training
# NAME                       STATE      AGE
# cpu-distributed-training   Complete   9s

# 查看 Pod 状态
kubectl get pods -n default
# NAME                                      READY   STATUS      RESTARTS   AGE
# cpu-distributed-training-node-0-0-d72t2   0/1     Completed   0          9s
# cpu-distributed-training-node-0-1-84sd9   0/1     Completed   0          9s
```

### Step 6：查看训练日志

```bash
kubectl logs cpu-distributed-training-node-0-0-d72t2   # Node 0
kubectl logs cpu-distributed-training-node-0-1-84sd9   # Node 1
```

---

## 6. 测试日志

### 5.1 Node 0 完整日志

```
[Node 0] world_size=2  master=cpu-distributed-training-node-0-0.cpu-distributed-training:29500
[Node 0] Dataset: 100 total samples  → shard [0:50] (50 samples)
[Node 0] Shard distribution: 26 positive, 24 negative
[Node 0] Starting SGD  lr=0.05  epochs=10
[Node 0] Initial weights: w1=0.0000  w2=0.0000  b=0.0000
[Node 0] Epoch  1/10  loss=0.2602  acc=100.0%  w1=0.753  w2=0.755  b=-0.018
[Node 0] Epoch  2/10  loss=0.0867  acc=100.0%  w1=0.984  w2=1.014  b=-0.030
[Node 0] Epoch  3/10  loss=0.0559  acc=100.0%  w1=1.122  w2=1.178  b=-0.038
[Node 0] Epoch  4/10  loss=0.0423  acc=100.0%  w1=1.220  w2=1.300  b=-0.042
[Node 0] Epoch  5/10  loss=0.0344  acc=100.0%  w1=1.297  w2=1.398  b=-0.045
[Node 0] Epoch  6/10  loss=0.0292  acc=100.0%  w1=1.360  w2=1.480  b=-0.046
[Node 0] Epoch  7/10  loss=0.0255  acc=100.0%  w1=1.413  w2=1.551  b=-0.047
[Node 0] Epoch  8/10  loss=0.0228  acc=100.0%  w1=1.459  w2=1.613  b=-0.047
[Node 0] Epoch  9/10  loss=0.0206  acc=100.0%  w1=1.500  w2=1.670  b=-0.047
[Node 0] Epoch 10/10  loss=0.0188  acc=100.0%  w1=1.537  w2=1.721  b=-0.047
[Node 0] ── Training complete ──
[Node 0] Final weights: w1=1.5367  w2=1.7209  b=-0.0472
[Node 0] Inference check:
[Node 0]   input=(+2.0,+2.0)  P(class=1)=0.998  predict=1  true=1
[Node 0]   input=(-2.0,-2.0)  P(class=1)=0.001  predict=0  true=0
[Node 0]   input=(+0.0,+0.0)  P(class=1)=0.488  predict=0  true=?
```

### 5.2 Node 1 完整日志

```
[Node 1] world_size=2  master=cpu-distributed-training-node-0-0.cpu-distributed-training:29500
[Node 1] Dataset: 100 total samples  → shard [50:100] (50 samples)
[Node 1] Shard distribution: 24 positive, 26 negative
[Node 1] Starting SGD  lr=0.05  epochs=10
[Node 1] Initial weights: w1=0.0000  w2=0.0000  b=0.0000
[Node 1] Epoch  1/10  loss=0.2742  acc=98.0%  w1=0.801  w2=0.713  b=-0.041
[Node 1] Epoch  2/10  loss=0.0882  acc=100.0%  w1=1.079  w2=0.953  b=-0.059
[Node 1] Epoch  3/10  loss=0.0542  acc=100.0%  w1=1.249  w2=1.098  b=-0.071
[Node 1] Epoch  4/10  loss=0.0395  acc=100.0%  w1=1.373  w2=1.201  b=-0.081
[Node 1] Epoch  5/10  loss=0.0312  acc=100.0%  w1=1.469  w2=1.283  b=-0.088
[Node 1] Epoch  6/10  loss=0.0259  acc=100.0%  w1=1.549  w2=1.349  b=-0.095
[Node 1] Epoch  7/10  loss=0.0221  acc=100.0%  w1=1.618  w2=1.406  b=-0.101
[Node 1] Epoch  8/10  loss=0.0194  acc=100.0%  w1=1.677  w2=1.455  b=-0.106
[Node 1] Epoch  9/10  loss=0.0173  acc=100.0%  w1=1.730  w2=1.499  b=-0.110
[Node 1] Epoch 10/10  loss=0.0156  acc=100.0%  w1=1.777  w2=1.538  b=-0.115
[Node 1] ── Training complete ──
[Node 1] Final weights: w1=1.7772  w2=1.5380  b=-0.1146
[Node 1] Inference check:
[Node 1]   input=(+2.0,+2.0)  P(class=1)=0.999  predict=1  true=1
[Node 1]   input=(-2.0,-2.0)  P(class=1)=0.001  predict=0  true=0
[Node 1]   input=(+0.0,+0.0)  P(class=1)=0.471  predict=0  true=?
```

### 5.3 关键事件时间线

```
T+0s   TrainJob 提交
T+1s   Kueue 创建 Workload（QuotaReserved wait=1s，Admitted wait=0s）
T+2s   Trainer Controller 创建 JobSet（suspend=false 触发）
T+2s   JobSet Controller 创建 Indexed Job + 2 个 Pod
T+2s   Pod[0] 和 Pod[1] 调度成功（mykueue-control-plane）
T+3s   镜像缓存命中，容器启动（python:3.11-slim already present）
T+9s   两个 Pod 完成训练（10 epochs × 50 samples × 0.05s/sample ≈ 5s）
T+9s   JobSet AllJobsCompleted → TrainJob State: Complete
T+9s   Kueue Workload Finished，配额归零
```

---

## 7. 测试结果

### 6.1 功能验证

| 验证项 | 结果 | 说明 |
|--------|------|------|
| TrainJob 创建并挂起 | ✅ | Kueue webhook 正确拦截 |
| Kueue 准入 | ✅ | 总等待 1s（配额充足） |
| JobSet 自动创建 | ✅ | Trainer v2 正确触发 |
| 2 个 Pod 并行运行 | ✅ | Indexed Job completions=2 |
| 数据分片正确 | ✅ | Node 0: [0:50]，Node 1: [50:100] |
| PET_* 环境变量注入 | ✅ | world_size=2，master DNS 解析正确 |
| 真实梯度下降 | ✅ | Loss 从 0.26 降至 0.018（10 倍） |
| 推理结果正确 | ✅ | 两节点结论一致 |
| TrainJob 完成 | ✅ | State: Complete，耗时约 9s |
| Kueue 配额释放 | ✅ | ClusterQueue 恢复 0 使用量 |

### 6.2 训练指标对比

| Epoch | Node 0 Loss | Node 0 Acc | Node 1 Loss | Node 1 Acc |
|-------|-------------|------------|-------------|------------|
| 1 | 0.2602 | 100.0% | 0.2742 | 98.0% |
| 2 | 0.0867 | 100.0% | 0.0882 | 100.0% |
| 5 | 0.0344 | 100.0% | 0.0312 | 100.0% |
| 10 | **0.0188** | **100.0%** | **0.0156** | **100.0%** |

Loss 下降率：Node 0 降低 **92.8%**，Node 1 降低 **94.3%**

### 6.3 最终权重对比

| 参数 | Node 0 | Node 1 | 说明 |
|------|--------|--------|------|
| w1 | 1.5367 | 1.7772 | Node 1 的 w1 较大 |
| w2 | 1.7209 | 1.5380 | Node 0 的 w2 较大 |
| b | -0.0472 | -0.1146 | 均接近 0，类别平衡 |

两节点权重略有差异（w1/w2 互补）是 **data-parallel 无梯度同步** 的正常现象：各节点在自己的数据分片上收敛，分片的局部特征差异导致权重侧重不同。但推理结果一致，说明决策边界相近。

### 6.4 推理验证

| 输入 | Node 0 P(class=1) | Node 1 P(class=1) | 预测 | 解释 |
|------|-------------------|-------------------|------|------|
| (+2.0, +2.0) | 0.998 | 0.999 | Class 1 ✅ | 正例区域中心 |
| (-2.0, -2.0) | 0.001 | 0.001 | Class 0 ✅ | 负例区域中心 |
| (0.0, 0.0) | 0.488 | 0.471 | Class 0（边界） | 原点在决策边界附近，不确定性高 |

---

## 8. 测试分析

### 7.1 Kueue 的调度价值

本次测试所有资源均在配额范围内，TrainJob 获得即时准入（wait=1s）。在实际多租户场景中，Kueue 的价值体现在：
- **配额隔离**：不同团队的 LocalQueue 独立计算配额，防止单一任务耗尽集群资源
- **优先级抢占**：高优先级 TrainJob 可抢占低优先级 Job 的资源
- **公平调度**：多队列间按 nominalQuota 公平共享

### 7.2 Kubeflow Trainer v2 的分层设计

```
TrainJob（用户提交）
    ↓ 引用
ClusterTrainingRuntime（运维团队维护，定义运行时模板）
    ↓ 展开为
JobSet（底层执行，支持多角色、失败策略、headless DNS）
```

这种分层让用户只需关心 `numNodes` 和 `resourcesPerNode`，运行时细节（调度标签、网络配置、环境变量注入）由 Runtime 和 Controller 统一管理。

### 7.3 data-parallel 无梯度同步的影响

本 demo 每个节点独立训练自己的数据分片，未做梯度 AllReduce。在真实 PyTorch DDP 中：

```
每个 step：
  1. 各节点前向传播（本地数据）
  2. 各节点计算梯度
  3. NCCL AllReduce（梯度求平均）← 本 demo 缺少这步
  4. 各节点用相同梯度更新权重（保证权重一致）
```

正因为缺少第 3 步，两个节点的最终权重出现了差异。如需真实 DDP，使用 `pytorch/pytorch` 镜像并调用 `torch.distributed.init_process_group()`，Trainer v2 的 `PET_*` 变量会自动被 `torchrun` 转换为 `torch.distributed` 所需的标准环境变量。

### 7.4 安装过程中的问题与解决

| 问题 | 根本原因 | 解决方案 |
|------|---------|---------|
| Trainer v2 内置 JobSet 镜像不可用 | `us-central1-docker.pkg.dev/k8s-staging-images/jobset/jobset:v0.11.0` 是内部 staging 镜像 | 替换为公开稳定版 `registry.k8s.io/jobset/jobset:v0.8.0` |
| JobSet webhook 调用失败（connection refused） | 两套 JobSet 并存（jobset-system + kubeflow-system），webhook 指向无 Pod 的 Service | 统一到 kubeflow-system，修复 Deployment 的 Pod selector 标签 |
| ClusterTrainingRuntime 校验失败 | 容器名 `trainer` 不符合 Trainer v2 约定（应为 `node`） | 按官方 `torch-distributed` runtime 格式修正 |
| 脚本读取错误环境变量 | Trainer v2 注入 `PET_*` 前缀变量，非标准 `RANK`/`WORLD_SIZE` | 更新脚本使用 `PET_NNODES`/`PET_NODE_RANK` |

---

## 9. 扩展指南

### 8.1 接入真实数据集

**PVC 挂载（推荐 on-prem）：**
```yaml
# ClusterTrainingRuntime 中添加
volumes:
  - name: dataset
    persistentVolumeClaim:
      claimName: training-data-pvc
containers:
  - name: node
    volumeMounts:
      - mountPath: /data
        name: dataset
    command: [python3, train.py, --data-dir=/data]
```

**Trainer v2 原生 dataset initializer：**
```yaml
spec:
  initializer:
    dataset:
      storageUri: "hf://datasets/my-dataset"   # HuggingFace
      # storageUri: "s3://my-bucket/dataset"   # S3
```

### 8.2 多 TrainJob 优先级

```yaml
metadata:
  labels:
    kueue.x-k8s.io/queue-name: user-queue
    kueue.x-k8s.io/priority-class: high-priority
```

### 8.3 升级为真实 PyTorch DDP

```yaml
containers:
  - name: node
    image: pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime
    command: [torchrun, --nproc_per_node=1, train.py]
    # torchrun 自动读取 PET_* 变量并设置 RANK/WORLD_SIZE
```

---

## 附录：文件清单

| 文件 | 说明 |
|------|------|
| `00-kueue-resources.yaml` | ResourceFlavor / ClusterQueue / LocalQueue |
| `01-cluster-training-runtime.yaml` | 真实逻辑回归训练运行时（内嵌数据集） |
| `02-trainjob.yaml` | TrainJob（引用 Runtime，绑定 Kueue 队列） |
| `fix-jobset-deployment.yaml` | JobSet 控制器部署修复（稳定镜像） |
| `README.md` | 本文档（中文） |
| `README_EN.md` | 英文版报告 |
