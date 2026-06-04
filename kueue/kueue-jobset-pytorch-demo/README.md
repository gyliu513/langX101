# Kueue + JobSet：多节点 PyTorch CPU 训练 Demo

一个开箱即用的示例：在本地 **kind** 集群上运行**多节点 PyTorch DDP** 训练任务，
**无需 GPU，全部在 CPU 上运行**。

它演示了三个组件如何协作：

| 组件 | 作用 |
|------|------|
| **kind** | 本地的 Kubernetes 集群，包含**多个 worker 节点** |
| **JobSet** | 把训练 Pod 编排成一个整体（gang），并为 `torchrun` 提供稳定的 DNS 名称用于 rendezvous |
| **Kueue** | 基于 CPU/内存配额对 JobSet 进行排队与**整体准入（gang admission）** |

训练任务本身是一个很小的线性回归（`y = 3x + 2`），使用 PyTorch
`DistributedDataParallel`，通过 **gloo（CPU）** 后端在
**2 节点 × 2 进程 = world_size 4** 上训练。

---

## 拓扑结构

```
kind 集群 (kueue-jobset-demo)
 ├─ control-plane
 ├─ worker-1   ──►  Pod pytorch-workers-0-0  (node_rank 0，MASTER)  ┐
 ├─ worker-2   ──►  Pod pytorch-workers-0-1  (node_rank 1)          │  JobSet "pytorch"
 └─ worker-3        (备用容量)                                       ┘  由 Kueue 整体准入

  2 节点 × --nproc_per_node=2  =>  world_size = 4   (gloo / CPU)
```

通过 `podAntiAffinity` 强制让两个 Pod 落在**不同的节点**上，从而确保这是
真正的多节点训练，而不是同一台机器上的两个 Pod。

JobSet 会自动创建一个与 JobSet 同名的 headless Service，为每个 Pod 提供稳定
DNS 名称：

```
<jobset>-<replicatedJob>-<jobIndex>-<podIndex>.<jobset>
pytorch-workers-0-0.pytorch        # master / node_rank 0
```

所有 worker 的 `torchrun --master_addr` 都指向这个名称来完成 rendezvous。

---

## 前置条件

- `docker`（已启动）
- `kind`
- `kubectl`

脚本中固定的版本：**JobSet v0.12.0**、**Kueue v0.18.0**。
（Kueue v0.18 **默认已启用** `jobset.x-k8s.io/jobset` 集成，无需修改 ConfigMap。）

---

## 快速开始

```bash
./setup.sh     # 创建多节点 kind 集群，安装 JobSet + Kueue，创建配额对象
./run.sh       # 提交 PyTorch JobSet 并实时查看 master pod 日志
./cleanup.sh   # 删除整个 kind 集群
```

首次运行较慢：每个 Pod 在训练前都会先 `pip install` CPU 版的 PyTorch。

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `kind-cluster.yaml` | 1 个 control-plane + 3 个 worker 节点 |
| `00-kueue-resources.yaml` | `ResourceFlavor`、`ClusterQueue`（8 CPU / 8Gi）、`LocalQueue` |
| `01-pytorch-jobset.yaml` | 在 CPU 上运行多节点 `torchrun` DDP 的 `JobSet` |
| `setup.sh` | 集群 + JobSet + Kueue + 配额 |
| `run.sh` | 提交 JobSet，展示准入与调度位置，并查看日志 |
| `cleanup.sh` | `kind delete cluster` |

---

## 观察运行过程

```bash
# Kueue 已准入该 JobSet（ADMITTED=True 表示已作为一个整体预留配额）
kubectl get workloads -o wide

# 两个训练 pod，分布在两个不同节点上
kubectl get pods -l app=pytorch-jobset -o wide

# 每个 rank 的日志。Pod 的 DNS 主机名是固定的（pytorch-workers-0-0），
# 但 Pod 对象名带有随机后缀，因此按 completion index 选择：
kubectl logs -f -l app=pytorch-jobset,batch.kubernetes.io/job-completion-index=0  # node_rank 0（master）
kubectl logs -f -l app=pytorch-jobset,batch.kubernetes.io/job-completion-index=1  # node_rank 1
```

master 日志的预期结尾：

```
===================================================
  Multi-node DDP training complete
  world_size=4 (2 nodes x 2 processes/node)
  Learned : w=3.0xxx  b=2.0xxx
  Target  : w=3.0000  b=2.0000
===================================================
```

JobSet 完成后，其 Workload 被标记为 Finished，预留的配额会归还给 `ClusterQueue`。

---

## Kueue 如何对 JobSet 进行门控

1. JobSet 带有标签 `kueue.x-k8s.io/queue-name: jobset-user-queue`。Kueue 拦截它，
   并创建一个 **Workload** 对象，描述其总资源需求
   （2 个 Pod × 1 CPU + 1Gi = **2 CPU + 2Gi**）。
2. Kueue 检查 `jobset-cluster-queue` 配额（8 CPU / 8Gi）。如果**整体**需求能放下，
   就**作为一个整体准入该 JobSet**（gang 调度）并解除挂起；否则该 JobSet 在队列中等待。
3. 只有在准入之后，JobSet 才会创建 Job/Pod，随后运行 `torchrun` 开始训练。

想观察排队效果：把 `ClusterQueue` 配额调到小于 2 CPU，然后提交两个 JobSet——
第二个会保持 `Pending`，直到第一个完成。

---

## 切换到真实 GPU

manifest 中已用注释标注。需要做四处修改：

1. `backend="gloo"` → `backend="nccl"`
2. `device = torch.device("cpu")` → `device = torch.device(f"cuda:{local_rank}")`
3. 取消 `resources.limits` 下 `nvidia.com/gpu` 的注释
4. 在 `00-kueue-resources.yaml` 中增加 `nvidia.com/gpu` 配额，并在 `ResourceFlavor`
   上为 GPU 节点打标签
