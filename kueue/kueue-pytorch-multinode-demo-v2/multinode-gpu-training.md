# Multi-Node GPU Training on Kubernetes: Architecture Guide

## The Scenario

You have a **2-node GPU cluster**, with **8 GPUs per node** (16 GPUs total). You want to run a **single distributed PyTorch training job** that uses all 16 GPUs together — for example, training a large model with Distributed Data Parallel (DDP).

The core design question is:

> **How do you map GPUs → processes → Pods → nodes?**

Two common but very different answers:

| Approach | Layout |
|----------|--------|
| **A** | 8 Pods per node, 1 GPU per Pod → **16 Pods total** |
| **B** | 1 Pod per node, 8 training processes per Pod → **2 Pods total** |

**Approach B is the industry-standard optimal solution.** The rest of this document explains why, using your cluster as the concrete example.

---

## Recommended Architecture: 1 Pod per Node, 8 Processes per Pod

### Topology

```
Cluster: 2 nodes × 8 GPUs = 16 GPUs total

Kubernetes Job (completions=2, parallelism=2, completionMode= Indexed)
│
├── Pod-0  (scheduled on Node-1, node_rank=0, 8 GPUs)
│   └── torchrun --nnodes=2 --nproc_per_node=8 --node_rank=0
│       ├── Rank 0  → GPU 0
│       ├── Rank 1  → GPU 1
│       ├── ...
│       └── Rank 7  → GPU 7
│
└── Pod-1  (scheduled on Node-2, node_rank=1, 8 GPUs)
    └── torchrun --nnodes=2 --nproc_per_node=8 --node_rank=1
        ├── Rank 8  → GPU 0
        ├── ...
        └── Rank 15 → GPU 7

Global world_size = 2 nodes × 8 processes = 16 ranks
Communication backend: NCCL (GPU)
Master rendezvous: Headless Service → Pod-0 (index=0)
```

### Key Parameters

**Kubernetes Job:**

```yaml
spec:
  completions: 2        # 2 Pods total (one per node)
  parallelism: 2        # launch both Pods simultaneously (gang scheduling)
  completionMode: Indexed
```

**torchrun (inside each Pod):**

```bash
torchrun \
  --nnodes=2 \
  --nproc_per_node=8 \
  --node_rank=${JOB_COMPLETION_INDEX} \
  --master_addr=pytorch-master-svc.default.svc.cluster.local \
  --master_port=29500 \
  train.py
```

**Resource requests (per Pod):**

```yaml
resources:
  limits:
    nvidia.com/gpu: "8"
    memory: "64Gi"   # example
    cpu: "32"
```

**Training script (per process):**

```python
local_rank = int(os.environ["LOCAL_RANK"])
rank       = int(os.environ["RANK"])        # 0–15 globally
world_size = int(os.environ["WORLD_SIZE"]) # 16

torch.cuda.set_device(local_rank)
device = torch.device(f"cuda:{local_rank}")

dist.init_process_group(backend="nccl")
model = nn.parallel.DistributedDataParallel(model.to(device), device_ids=[local_rank])
```

### Why This Is Optimal

This design aligns with how **PyTorch, NCCL, and torchrun** are built:

1. **Process = GPU.** PyTorch DDP assigns one training process per GPU. `LOCAL_RANK` maps directly to a GPU index inside the Pod.
2. **Node = Pod.** A physical machine (node) is represented as one Kubernetes Pod. All 8 GPUs on that machine are visible inside the same Pod.
3. **torchrun is designed for this.** `--nproc_per_node=8` forks 8 worker processes on the local machine, sets `RANK`, `LOCAL_RANK`, `WORLD_SIZE`, etc., and coordinates rendezvous across nodes.
4. **NCCL performs best within a Pod.** GPUs on the same node communicate over NVLink/PCIe. Keeping all 8 local processes in one Pod avoids unnecessary container-network hops.
5. **Minimal scheduling overhead.** Only 2 Pods to schedule, admit, monitor, and tear down — not 16.

---

## How This Maps to Your Existing Demo

Your `kueue-pytorch-multinode-demo-v2` is a **scaled-down version of this exact pattern**:

| Demo (CPU) | Production (GPU) |
|------------|------------------|
| 2 Pods | 2 Pods |
| `--nproc_per_node=2` | `--nproc_per_node=8` |
| `world_size=4` | `world_size=16` |
| `backend=gloo` (CPU) | `backend=nccl` (GPU) |
| 2 CPU per Pod | 8 GPUs per Pod |
| Headless Service for master | Same Headless Service |
| Kueue gang scheduling | Same Kueue gang scheduling |

The architecture does not change — only the scale and backend change. Your demo already demonstrates the correct pattern.

---

## Alternative Approaches (and Why They Are Worse)

### Approach A: 8 Pods per Node, 1 GPU per Pod (16 Pods Total)

```
Node-1                          Node-2
├── Pod-gpu-0  (1 GPU, rank ?)  ├── Pod-gpu-8  (1 GPU)
├── Pod-gpu-1  (1 GPU)          ├── Pod-gpu-9  (1 GPU)
├── ...                         ├── ...
└── Pod-gpu-7  (1 GPU)          └── Pod-gpu-15 (1 GPU)

Each Pod runs: torchrun --nproc_per_node=1 --nnodes=16 --node_rank=?
```

| Dimension | 1 Pod/node (recommended) | 8 Pods/node (not recommended) |
|-----------|--------------------------|-------------------------------|
| **Total Pods** | 2 | 16 |
| **Pod startup overhead** | Low (2 image pulls, 2 schedulings) | High (16× everything) |
| **PyTorch/torchrun support** | Native, first-class | Awkward; torchrun expects node=machine |
| **NCCL intra-node comms** | Direct NVLink/PCIe between GPUs in same Pod | Must traverse container network between Pods |
| **NCCL inter-node comms** | 2 endpoints (one per node) | 16 endpoints, more complex topology |
| **Gang scheduling (Kueue)** | Admit 2 Pods atomically | Must admit all 16 Pods before training starts |
| **Master rendezvous** | 1 Headless Service → Pod-0 | Complex: which of 16 Pods is master? |
| **Logging & debugging** | 2 log streams | 16 log streams |
| **Resource quota (Kueue)** | 16 GPUs in 2 Workload units | 16 GPUs in 16 Workload units |
| **Failure recovery** | Restart 1 node (8 GPUs) | Restart individual GPU Pod, re-coordination needed |
| **Network policies** | Simple (2 Pods) | 16 Pods need full mesh connectivity |

**When might 1-Pod-per-GPU make sense?**

- Running **16 independent, unrelated jobs** (not one distributed training job)
- GPU sharing across teams with strict isolation requirements
- MIG (Multi-Instance GPU) scenarios where each slice is a separate workload
- Legacy MPI/Horovod setups with specific launcher requirements

For a **single coordinated DDP training job**, this approach adds complexity with no benefit.

---

### Approach C: 1 Pod Total, 16 Processes (Single-Node Only)

```
1 Pod on 1 node
└── torchrun --nproc_per_node=16
    ├── Rank 0–15, all on same node
```

This works if all 16 GPUs happen to be on one physical machine (e.g., a DGX with 8 GPUs — you'd use `--nproc_per_node=8`). But with **2 separate nodes**, you cannot put all 16 GPUs in one Pod — Kubernetes schedules a Pod onto **one node** (unless using special multi-node Pod mechanisms, which are rare and not recommended).

So this approach is only valid for **single-node multi-GPU**, which is what your `kueue-pytorch-ddp-demo` demonstrates.

---

### Approach D: 2 Pods, but 1 Process per Pod (Underutilized)

```
2 Pods, each with 8 GPUs allocated
└── torchrun --nproc_per_node=1  (only uses 1 of 8 GPUs!)
```

You request 8 GPUs per Pod but only launch 1 process. The other 7 GPUs sit idle. This wastes 87.5% of your GPU capacity. Always set `--nproc_per_node` equal to the number of GPUs in the Pod.

---

## Side-by-Side Summary

```
Scenario: 2 nodes × 8 GPUs, one distributed training job

┌─────────────────────────────────────────────────────────────────┐
│                    APPROACH COMPARISON                          │
├──────────────┬──────────────┬──────────────┬────────────────────┤
│              │ B: Optimal   │ A: 1GPU/Pod  │ C: Single Pod     │
│              │ 1 Pod/node   │ 8 Pods/node  │ 16 procs          │
├──────────────┼──────────────┼──────────────┼────────────────────┤
│ Pods         │ 2            │ 16           │ 1 (impossible     │
│              │              │              │  across 2 nodes)  │
│ Processes    │ 16           │ 16           │ 16                │
│ GPU usage    │ 100%         │ 100%         │ N/A               │
│ NCCL perf    │ Best         │ Degraded     │ N/A               │
│ Complexity   │ Low          │ High         │ N/A               │
│ Kueue admit  │ 2 units      │ 16 units     │ N/A               │
│ torchrun fit │ Native       │ Poor         │ Single-node only  │
│ Recommended  │ YES          │ NO           │ NO (multi-node)   │
└──────────────┴──────────────┴──────────────┴────────────────────┘
```

---

## End-to-End Flow (Optimal Approach)

```
1. User submits Job with kueue.x-k8s.io/queue-name label
        │
2. Kueue creates Workload, checks quota: 16 GPUs available?
        │
3. Kueue admits → both Pods scheduled simultaneously
        │
4. Pod-0 (index=0) starts on Node-1
   Pod-1 (index=1) starts on Node-2
   (podAntiAffinity ensures different nodes)
        │
5. Both Pods run torchrun:
   - Pod-0: --node_rank=0, forks 8 processes (Rank 0–7)
   - Pod-1: --node_rank=1, forks 8 processes (Rank 8–15)
        │
6. All 16 processes rendezvous via Headless Service
   (pytorch-master-svc → Pod-0 IP:29500)
        │
7. dist.init_process_group(backend="nccl") succeeds
   world_size=16 established
        │
8. Training loop:
   - DistributedSampler splits data across 16 ranks
   - Each rank computes gradients on its GPU
   - DDP all-reduces gradients across all 16 ranks (NCCL)
   - All ranks stay synchronized
        │
9. Training completes → both Pods exit → Job Finished
   Kueue releases 16 GPU quota
```

---

## Practical Checklist for Your 2×8 GPU Cluster

| Item | Value |
|------|-------|
| Job type | `batch/v1 Job` with `completionMode: Indexed` |
| Pods | 2 (`completions=2, parallelism=2`) |
| GPUs per Pod | 8 (`nvidia.com/gpu: "8"`) |
| torchrun | `--nnodes=2 --nproc_per_node=8` |
| Backend | `nccl` |
| Master discovery | Headless Service selecting `completion-index=0` |
| Node placement | `podAntiAffinity` on `kubernetes.io/hostname` |
| Scheduler | Kueue (quota = 16 GPUs, gang admit both Pods) |
| world_size | 16 |

---

## One-Line Takeaway

**For a 2-node × 8-GPU distributed training job: use 2 Pods (one per node), launch 8 processes per Pod via `torchrun --nproc_per_node=8`, yielding 16 global ranks — not 16 Pods with 1 GPU each.** This is the pattern your multinode demo already follows; scale the numbers up and switch from `gloo`/CPU to `nccl`/GPU for production.
