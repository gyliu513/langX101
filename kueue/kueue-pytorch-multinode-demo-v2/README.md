# Kueue + PyTorch 多节点 DDP 训练 Demo（kind 多节点集群版）

> **验证目标**：两个训练 Pod 分别运行在两个不同的 kind Worker 节点上，通过 Kueue gang scheduling 一起被调度。

## 概述

本 Demo 在**本机 kind 多节点集群**上演示：

- **多节点 kind 集群**：1 个 control-plane + 2 个 worker 节点
- **Kueue gang scheduling**：2 个 Pod 作为一个 Workload 一起被准入或等待
- **Pod 反亲和性**：强制保证 Pod-0 和 Pod-1 落在不同 Worker 节点
- **PyTorch DDP 跨节点训练**：2 个 Pod × 2 个进程 = world_size 4，gloo backend（CPU 模式）
- **Headless Service**：为 master Pod 提供稳定 DNS，解决多节点 rendezvous 问题

## 架构

```
本机 Docker
└── kind 集群（kueue-demo）
    ├── control-plane      ← 只运行系统组件（有 NoSchedule taint）
    ├── worker-1           ← 运行 Pod-0（node_rank=0，master）
    └── worker-2           ← 运行 Pod-1（node_rank=1，worker）

                    Kueue ClusterQueue
                    （统一配额 + gang 调度）
                           │
              Workload: job-pytorch-multinode-training
                    （两个 Pod 一起 Admitted）
                           │
          ┌────────────────┴────────────────┐
          │                                 │
    Pod-0（worker-1）              Pod-1（worker-2）
    node_rank=0                    node_rank=1
    ┌──────────────────┐           ┌──────────────────┐
    │ torchrun         │           │ torchrun         │
    │  Rank 0（进程0）  │           │  Rank 2（进程0）  │
    │  Rank 1（进程1）  │           │  Rank 3（进程1）  │
    └────────┬─────────┘           └────────┬─────────┘
             │                              │
             └──── gloo all-reduce（梯度同步）────┘

    pytorch-master-svc（Headless Service）
      → 选中 index=0 的 Pod（Pod-0）
      → DNS: pytorch-master-svc.default.svc.cluster.local
      → 所有 Pod 的 --master_addr 指向此 DNS
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `kind-cluster.yaml` | kind 集群配置：1 control-plane + 2 worker |
| `00-kueue-resources.yaml` | ResourceFlavor、ClusterQueue、LocalQueue |
| `01-master-service.yaml` | Headless Service，选中 index=0 的 Pod |
| `02-pytorch-multinode-job.yaml` | Indexed Job，启用反亲和性，2 个 Pod |

---

## 步骤一：安装前置工具

确保本机已安装以下工具：

```bash
# 检查工具版本
kind version       # 需要 v0.20+
kubectl version --client
docker info        # 需要 Docker Desktop 或 Docker Engine 运行中
```

如需安装 kind：

```bash
# macOS（Apple Silicon 或 Intel）
brew install kind

# 或直接下载二进制（Apple Silicon）
curl -Lo /usr/local/bin/kind \
  https://kind.sigs.k8s.io/dl/v0.31.0/kind-darwin-arm64
chmod +x /usr/local/bin/kind
```

---

## 步骤二：创建 kind 多节点集群

### 2.1 创建集群

```bash
kind create cluster --config kind-cluster.yaml
```

集群名称为 `kueue-demo`，包含 3 个节点。创建过程约需 1～2 分钟，输出示例：

```
Creating cluster "kueue-demo" ...
 ✓ Ensuring node image (kindest/node:v1.32.0) 🖼
 ✓ Preparing nodes 📦 📦 📦
 ✓ Writing configuration 📜
 ✓ Starting control-plane 🕹️
 ✓ Installing CNI 🔌
 ✓ Installing StorageClass 💾
 ✓ Joining worker nodes 🚜
Set kubectl context to "kind-kueue-demo"
```

### 2.2 验证集群节点

```bash
kubectl get nodes -o wide
```

预期输出（3 个节点，全部 Ready）：

```
NAME                       STATUS   ROLES           AGE   VERSION
kueue-demo-control-plane   Ready    control-plane   60s   v1.32.0
kueue-demo-worker          Ready    <none>          45s   v1.32.0
kueue-demo-worker2         Ready    <none>          45s   v1.32.0
```

> **关键**：`control-plane` 节点有 `node-role.kubernetes.io/control-plane:NoSchedule` 污点，普通 Pod 不会被调度到此节点。

### 2.3 确认节点标签（供反亲和性参考）

```bash
kubectl get nodes --show-labels | grep -v control-plane
```

---

## 步骤三：安装 Kueue

### 3.1 安装 Kueue v0.11.4

```bash
kubectl apply --server-side \
  -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.11.4/manifests.yaml
```

### 3.2 等待 Kueue 就绪

```bash
kubectl -n kueue-system wait deployment/kueue-controller-manager \
  --for=condition=Available --timeout=120s
```

输出：
```
deployment.apps/kueue-controller-manager condition met
```

### 3.3 验证 Kueue 组件

```bash
kubectl get pods -n kueue-system
```

预期输出（所有 Pod 均为 Running）：

```
NAME                                        READY   STATUS    AGE
kueue-controller-manager-xxxxxxxxx-xxxxx   2/2     Running   30s
```

### 3.4 确认 CRD 已注册

```bash
kubectl get crd | grep kueue
```

应看到 `clusterqueues.kueue.x-k8s.io`、`localqueues.kueue.x-k8s.io`、`workloads.kueue.x-k8s.io` 等。

---

## 步骤四：部署 Demo

### 4.1 创建 Kueue 资源

```bash
kubectl apply -f 00-kueue-resources.yaml
```

验证：

```bash
kubectl get clusterqueue multinode-cluster-queue -o wide
kubectl get localqueue multinode-user-queue -n default
```

预期输出：

```
NAME                     COHORT   PENDING WORKLOADS   ...
multinode-cluster-queue           0

NAME                   CLUSTERQUEUE             PENDING WORKLOADS
multinode-user-queue   multinode-cluster-queue  0
```

### 4.2 创建 Master Headless Service

```bash
kubectl apply -f 01-master-service.yaml
```

验证：

```bash
kubectl get svc pytorch-master-svc -n default
```

预期输出（CLUSTER-IP 为 None 即为 Headless Service）：

```
NAME                 TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)     AGE
pytorch-master-svc   ClusterIP   None         <none>        29500/TCP   5s
```

### 4.3 提交训练 Job

```bash
kubectl apply -f 02-pytorch-multinode-job.yaml
```

---

## 步骤五：观察调度结果

### 5.1 查看 Kueue Workload 状态

```bash
kubectl get workloads -n default
```

预期输出（ADMITTED=True 说明 Kueue 已批准此 Workload）：

```
NAME                                         QUEUE                  ADMITTED   AGE
job-pytorch-multinode-training-xxxxxxxxxx   multinode-user-queue   True       10s
```

### 5.2 查看 Job 状态

```bash
kubectl get jobs -n default
```

预期输出：

```
NAME                         STATUS    COMPLETIONS   DURATION   AGE
pytorch-multinode-training   Running   0/2           10s        15s
```

### 5.3 验证两个 Pod 运行在不同 Worker 节点上（核心验证）

```bash
kubectl get pods -n default -o wide
```

**预期输出**：

```
NAME                                 READY   STATUS    NODE                  AGE
pytorch-multinode-training-0-xxxxx   1/1     Running   kueue-demo-worker     30s
pytorch-multinode-training-1-xxxxx   1/1     Running   kueue-demo-worker2    30s
```

> 关键验证点：`-0-` 的 Pod 在 `kueue-demo-worker`，`-1-` 的 Pod 在 `kueue-demo-worker2`，两个 Pod 在**不同节点**。这由 `podAntiAffinity` 强制保证。

### 5.4 确认 Pod 节点分布（更详细）

```bash
kubectl get pods -n default \
  -o custom-columns="POD:.metadata.name,STATUS:.status.phase,NODE:.spec.nodeName,INDEX:.metadata.labels['batch\.kubernetes\.io/job-completion-index']"
```

预期输出：

```
POD                                  STATUS    NODE                   INDEX
pytorch-multinode-training-0-xxxxx   Running   kueue-demo-worker      0
pytorch-multinode-training-1-xxxxx   Running   kueue-demo-worker2     1
```

---

## 步骤六：查看训练日志

### 6.1 实时查看所有 Pod 日志

```bash
kubectl logs -f -l job-name=pytorch-multinode-training \
  -n default --prefix --max-log-requests=2
```

### 6.2 单独查看某个 Pod 的日志

```bash
# 查看 master Pod（index=0）日志
kubectl logs -f -l batch.kubernetes.io/job-completion-index=0 \
  -n default -c trainer

# 查看 worker Pod（index=1）日志
kubectl logs -f -l batch.kubernetes.io/job-completion-index=1 \
  -n default -c trainer
```

### 6.3 预期日志输出

训练开始阶段：
```
[pod/pytorch-multinode-training-0-xxxxx/trainer] [Pod 0] Installing PyTorch (CPU)...
[pod/pytorch-multinode-training-1-xxxxx/trainer] [Pod 1] Installing PyTorch (CPU)...
[pod/pytorch-multinode-training-0-xxxxx/trainer] [Pod 0] Launching torchrun on node_rank=0
[pod/pytorch-multinode-training-1-xxxxx/trainer] [Pod 1] Launching torchrun on node_rank=1
[pod/pytorch-multinode-training-0-xxxxx/trainer] [Rank 0/4] node=0  local_rank=0  master=pytorch-master-svc...:29500
[pod/pytorch-multinode-training-0-xxxxx/trainer] [Rank 1/4] node=0  local_rank=1  master=pytorch-master-svc...:29500
[pod/pytorch-multinode-training-1-xxxxx/trainer] [Rank 2/4] node=1  local_rank=0  master=pytorch-master-svc...:29500
[pod/pytorch-multinode-training-1-xxxxx/trainer] [Rank 3/4] node=1  local_rank=1  master=pytorch-master-svc...:29500
[pod/.../trainer] [Rank 0/4] Process group initialized
```

训练过程中（每个 Epoch 结束后 4 个 Rank 的 `w`/`b` 完全相同，证明 all-reduce 正确）：
```
[pod/.../trainer] [Rank 0/4] Epoch  1/10  loss=4.0374  w=2.1221  b=1.2110
[pod/.../trainer] [Rank 1/4] Epoch  1/10  loss=3.7041  w=2.1221  b=1.2110
[pod/.../trainer] [Rank 2/4] Epoch  1/10  loss=3.8912  w=2.1221  b=1.2110
[pod/.../trainer] [Rank 3/4] Epoch  1/10  loss=3.9203  w=2.1221  b=1.2110
```

训练完成（Rank 0 打印最终结果）：
```
[pod/.../trainer] ===================================================
[pod/.../trainer]   Multi-node DDP training complete
[pod/.../trainer]   world_size=4 (2 nodes x 2 processes/node)
[pod/.../trainer]   Learned : w=3.0028  b=2.0004
[pod/.../trainer]   Target  : w=3.0000  b=2.0000
[pod/.../trainer]   Error   : dw=0.0028  db=0.0004
[pod/.../trainer] ===================================================
```

> **验证点**：每个 Epoch 所有 Rank 的 `w`/`b` 数值完全一致 → 跨节点梯度 all-reduce 工作正常。

### 6.4 等待 Job 完成

```bash
kubectl wait job/pytorch-multinode-training \
  --for=condition=Complete --timeout=600s -n default
```

---

## 步骤七：清理环境

### 7.1 清理 Demo 资源

```bash
kubectl delete -f 02-pytorch-multinode-job.yaml
kubectl delete -f 01-master-service.yaml
kubectl delete -f 00-kueue-resources.yaml
```

### 7.2 删除 kind 集群（可选）

```bash
kind delete cluster --name kueue-demo
```

---

## 关键设计说明

### 为什么需要 Headless Service？

多节点训练时，Pod-1 需要知道 Pod-0 的地址作为 `--master_addr`。但 Pod IP 是动态分配的，Pod 名称也带随机后缀。

解决方案：**Indexed Job + Headless Service**

| 机制 | 作用 |
|------|------|
| `completionMode: Indexed` | 每个 Pod 自动获得 `JOB_COMPLETION_INDEX` 环境变量（0 或 1） |
| Headless Service（`selector: batch.kubernetes.io/job-completion-index: "0"`） | Kubernetes 自动为 Indexed Job Pod 加此 Label，Service 始终解析到 Pod-0 的 IP |
| `--node_rank=${JOB_COMPLETION_INDEX}` | torchrun 知道当前节点是第几个节点 |

### 为什么需要 Pod 反亲和性？

`podAntiAffinity: requiredDuringSchedulingIgnoredDuringExecution` 配合 `topologyKey: kubernetes.io/hostname`，**强制调度器将两个 Pod 放到不同的物理/虚拟节点**。

没有反亲和性时，两个 Pod 可能调度到同一个 Worker 节点（在 kind 集群上尤为常见），此时虽然 DDP 可以运行，但不是真正的"多节点"分布式训练。

### Kueue Gang Scheduling 如何工作？

```
Job 提交（2 个 Pod）
       │
       ▼
Kueue 创建 Workload
       │
       ▼
检查配额：2 × (500m CPU + 512Mi) = 1 CPU + 1Gi
       │
  配额充足？
  ├── 是 → QuotaReserved → Admitted → 两个 Pod 同时启动
  └── 否 → Pending（等待资源释放）
```

---

## 切换到真实 GPU（2 节点 × 2 GPU = 4 GPU）

在真实 GPU 集群上，只需修改 `02-pytorch-multinode-job.yaml` 中 2 处：

**1. 训练脚本：gloo → nccl + 移动模型到 GPU**
```python
# 修改前（CPU）
dist.init_process_group(backend="gloo")
device = torch.device("cpu")

# 修改后（GPU）
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
flavors:
  - name: default-flavor
    resources:
      - name: nvidia.com/gpu
        nominalQuota: "4"
```

---

## 故障排查

### Pod 卡在 Pending

```bash
kubectl describe pod <pod-name> -n default
```

**常见原因 1**：Kueue Workload 未被 Admitted（配额不足）
```bash
kubectl get workloads -n default
kubectl describe workload <workload-name> -n default
```

**常见原因 2**：反亲和性无法满足（Worker 节点不足）
- 确认 kind 集群有 2 个 Worker 节点：`kubectl get nodes`
- 如果只有 1 个 Worker，删除反亲和性配置或增加节点

**常见原因 3**：资源不足
```bash
kubectl describe node kueue-demo-worker
kubectl describe node kueue-demo-worker2
```

### 两个 Pod 在同一节点

确认 `02-pytorch-multinode-job.yaml` 中 `podAntiAffinity` 部分存在且 `requiredDuringSchedulingIgnoredDuringExecution` 正确缩进。

### Kueue CRD 版本不匹配

```bash
kubectl get crd clusterqueues.kueue.x-k8s.io -o jsonpath='{.spec.versions[*].name}'
```

确保使用 `v1beta1`。Kueue v0.11.4 使用 `kueue.x-k8s.io/v1beta1`，本 Demo 的 YAML 与此匹配。

### PyTorch 安装超时

默认镜像 `python:3.11-slim` 每次 Pod 启动都需下载 PyTorch（约 200MB）。如需加速，可构建包含 PyTorch 的自定义镜像。

---

## 与其他 Demo 对比

| | kueue-pytorch-ddp-demo | 本 Demo |
|--|------------------------|---------|
| kind 集群节点数 | 1 个 Worker 即可 | **需要 2 个 Worker** |
| Pod 数量 | 1 个 | **2 个** |
| 进程数（world_size） | 2 | **4** |
| 跨节点通信 | 无（Pod 内） | **有（通过 Headless Service）** |
| 反亲和性 | 无需 | **必须（保证跨节点）** |
| 适用场景 | 单机多卡验证 | **生产多节点多卡训练模拟** |
