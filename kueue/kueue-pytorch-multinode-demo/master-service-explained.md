这个 `pytorch-master-svc` 的作用，是给 **多节点 PyTorch DDP 训练提供一个稳定的 master 地址（rendezvous 点）**。

## 核心问题：跨 Pod 怎么找到 master？

单 Pod demo 里可以直接用：

```bash
--master_addr=localhost
```

因为所有进程都在同一个 Pod 里。

多节点 demo 是 **2 个 Pod**（`completions: 2`, `parallelism: 2`），每个 Pod 里再跑 2 个进程，一共 4 个 rank：

```
Pod-0 (index=0): Rank 0, Rank 1   ← master 节点
Pod-1 (index=1): Rank 2, Rank 3   ← worker 节点
```

Pod-1 上的进程必须连到 Pod-0 上的 master，才能：

- 建立分布式进程组（`dist.init_process_group`）
- 交换 rank / world_size 等信息
- 做跨节点的梯度 all-reduce

但 Pod IP 是动态的，Pod 名字还带随机后缀，不能直接写死。所以需要 **一个固定 DNS 名字，始终指向 index=0 那个 Pod**。

## 这个 Service 具体做了什么

```5:18:kueue/kueue-pytorch-multinode-demo/01-master-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: pytorch-master-svc
  namespace: default
spec:
  clusterIP: None
  selector:
    batch.kubernetes.io/job-completion-index: "0"
    job-name: pytorch-multinode-training
  ports:
    - name: rdzv
      port: 29500
      targetPort: 29500
```

三个关键点：

| 配置 | 含义 |
|------|------|
| `clusterIP: None` | **Headless Service**，不做负载均衡，DNS 直接解析到后端 Pod 的真实 IP |
| `selector: job-completion-index: "0"` | 只选中 Indexed Job 里 **index=0 的 Pod**（master） |
| `port: 29500` | 暴露 torchrun 的 rendezvous 端口 |

Job 里所有 Pod 启动时都指向它：

```134:139:kueue/kueue-pytorch-multinode-demo/02-pytorch-multinode-job.yaml
              torchrun \
                --nproc_per_node=2 \
                --nnodes=2 \
                --node_rank=${JOB_COMPLETION_INDEX} \
                --master_addr=pytorch-master-svc.default.svc.cluster.local \
                --master_port=29500 \
```

## 通信流程

```
Pod-0 (index=0, master)          Pod-1 (index=1, worker)
├─ Rank 0 ─┐                     ├─ Rank 2 ──┐
└─ Rank 1 ─┤                     └─ Rank 3 ──┤
           │                                 │
           └──── 都连到 ────► pytorch-master-svc:29500
                            (DNS → Pod-0 的 IP)
```

- **Pod-0 上的 Rank 0/1**：本机就是 master，也通过 Service DNS 参与 rendezvous
- **Pod-1 上的 Rank 2/3**：通过 `pytorch-master-svc.default.svc.cluster.local:29500` 找到 Pod-0
- rendezvous 完成后，4 个 rank 组成 `world_size=4` 的进程组，训练时做跨 Pod 的梯度同步

## 为什么用 Headless，而不是普通 ClusterIP Service？

普通 ClusterIP 会把流量负载均衡到多个 Pod；这里只需要 **精确指向 index=0 那一个 Pod**。

Headless Service + selector 的效果是：

```
pytorch-master-svc.default.svc.cluster.local  →  Pod-0 的 IP
```

即使 Pod-0 重建、IP 变了，DNS 也会跟着更新，地址对训练脚本来说始终是稳定的。

## 和 Kueue 的关系

Kueue 负责 **调度 Job / 两个 Pod 何时运行**；这个 Service **不参与调度**，只解决 **Pod 之间的网络发现**。

可以简单理解为：

- **Kueue**：排队、配额、准入
- **Headless Service**：多节点 DDP 的“master 在哪”

## 一句话总结

**`pytorch-master-svc` 是一个 Headless Service，通过 selector 固定选中 completion-index=0 的 master Pod，给所有训练进程提供稳定的 `MASTER_ADDR`，解决多 Pod 分布式训练里的 rendezvous 地址问题。**
