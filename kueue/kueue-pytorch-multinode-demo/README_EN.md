# Kueue + PyTorch Multi-Node DDP Training Demo (2 nodes × 2 GPU = 4 processes)

> **Dependencies**: Kueue + standard Kubernetes Service only — no Kubeflow, no JobSet, no KubeRay

## Overview

This demo shows how to run real multi-node PyTorch Distributed Data Parallel (DDP) training on Kubernetes with minimal dependencies:

- **2 Pods**, each simulating one training node, running `torchrun --nproc_per_node=2`
- **4 processes total** (world_size=4), all-reducing gradients across Pods via gloo/nccl
- Uses `batch/v1 Job` with **`completionMode: Indexed`** to assign stable node ranks to each Pod
- Uses a **Headless Service** to give the master Pod (index=0) a stable DNS name, solving the multi-node rendezvous problem
- Runs on CPU in kind/minikube for local testing; **switching to GPU requires only 2 changes**

## Architecture

```
                    Kueue ClusterQueue
                    (quota & scheduling)
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
                 (cross-Pod gradient sync)

  pytorch-master-svc (Headless Service)
    → selects Pod with index=0
    → DNS: pytorch-master-svc.default.svc.cluster.local
    → all Pods set --master_addr to this DNS name
```

## Core Design

### The Problem: How Do Nodes Discover Each Other?

For single-node training `--master_addr=localhost` works fine. For multi-node, Pod-1 needs to know Pod-0's address — but pod IPs are dynamic and pod names have random suffixes.

### The Solution: Indexed Job + Headless Service

| Mechanism | Purpose |
|-----------|---------|
| `completionMode: Indexed` | Each Pod automatically gets `JOB_COMPLETION_INDEX` env var (0 or 1) |
| Headless Service selecting index=0 | Gives Pod-0 a stable DNS name to use as `MASTER_ADDR` |
| `--node_rank=${JOB_COMPLETION_INDEX}` | Tells `torchrun` which node this process group is |

The Headless Service uses `selector: batch.kubernetes.io/job-completion-index: "0"` — Kubernetes automatically adds this label to Indexed Job pods, so the Service always resolves to Pod-0's IP.

## Files

| File | Description |
|------|-------------|
| `00-kueue-resources.yaml` | ResourceFlavor, ClusterQueue, LocalQueue |
| `01-master-service.yaml` | Headless Service selecting index=0 Pod |
| `02-pytorch-multinode-job.yaml` | Indexed Job: 2 Pods × 2 processes each |

## Prerequisites

- Kubernetes cluster (kind, minikube, or a real cluster)
- Kueue installed (`kueue.x-k8s.io/v1beta2`)

Install Kueue:
```bash
kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.11.4/manifests.yaml
```

## Steps

### 1. Create Kueue Resources

```bash
kubectl apply -f 00-kueue-resources.yaml
```

### 2. Create the Master Service

```bash
kubectl apply -f 01-master-service.yaml
```

Verify:
```bash
kubectl get svc pytorch-master-svc -n default
# NAME                 TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)     AGE
# pytorch-master-svc   ClusterIP   None         <none>        29500/TCP   5s
```

### 3. Submit the Training Job

```bash
kubectl apply -f 02-pytorch-multinode-job.yaml
```

### 4. Observe Kueue Scheduling

```bash
# Kueue Workload
kubectl get workloads -n default

# Job status
kubectl get jobs -n default

# Both Pods (index 0 and index 1)
kubectl get pods -n default -o wide
```

Expected output:
```
NAME                                   QUEUE                  ADMITTED
job-pytorch-multinode-training-xxxxx   multinode-user-queue   True

NAME                                  STATUS    COMPLETIONS
pytorch-multinode-training            Running   0/2

NAME                                  READY   STATUS    NODE
pytorch-multinode-training-0-xxxxx    1/1     Running   node-1   # index=0, master
pytorch-multinode-training-1-xxxxx    1/1     Running   node-2   # index=1, worker
```

### 5. Stream Training Logs

```bash
kubectl logs -f -l job-name=pytorch-multinode-training -n default --prefix
```

### 6. Expected Output

```
[pod/.../trainer] [Pod 0] Launching torchrun: 2 nodes x 2 processes, node_rank=0
[pod/.../trainer] [Pod 1] Launching torchrun: 2 nodes x 2 processes, node_rank=1
[pod/.../trainer] [Rank 0/4] node=0  local_rank=0  master=pytorch-master-svc...:29500
[pod/.../trainer] [Rank 1/4] node=0  local_rank=1  master=pytorch-master-svc...:29500
[pod/.../trainer] [Rank 2/4] node=1  local_rank=0  master=pytorch-master-svc...:29500
[pod/.../trainer] [Rank 3/4] node=1  local_rank=1  master=pytorch-master-svc...:29500
[pod/.../trainer] [Rank 0/4] Process group initialized
...
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

Key observations:
- **All 4 ranks show identical `w`/`b` at the end of each epoch** → cross-Pod all-reduce is working correctly
- Ranks 0 and 1 come from Pod-0 (node=0); Ranks 2 and 3 come from Pod-1 (node=1)
- Each rank processes only 500 samples (2000 total / 4 ranks)

### 7. Cleanup

```bash
kubectl delete -f 02-pytorch-multinode-job.yaml
kubectl delete -f 01-master-service.yaml
kubectl delete -f 00-kueue-resources.yaml
```

## Switching to Real GPUs (2 nodes × 2 GPUs = 4 GPUs total)

Only **2 changes** needed in `02-pytorch-multinode-job.yaml`:

**1. Training script: gloo → nccl + move model to GPU**
```python
# Before (CPU)
dist.init_process_group(backend="gloo")
device = torch.device("cpu")

# After (GPU)
dist.init_process_group(backend="nccl")
device = torch.device(f"cuda:{local_rank}")
model = model.to(device)
```

**2. Container resources: add GPU request**
```yaml
resources:
  limits:
    nvidia.com/gpu: "2"   # uncomment this line
```

**3. ClusterQueue: add GPU quota** (`00-kueue-resources.yaml`):
```yaml
coveredResources: ["cpu", "memory", "nvidia.com/gpu"]
# add under flavors:
- name: nvidia.com/gpu
  nominalQuota: "4"
```

**4. Optional: Pod anti-affinity** to ensure the 2 Pods land on different GPU nodes.
Uncomment the `affinity` section in the Job YAML.

## Environment Variables Explained

| Variable | Set by | Description |
|----------|--------|-------------|
| `JOB_COMPLETION_INDEX` | Kubernetes (Indexed Job) | Pod's node index (0 or 1) |
| `RANK` | torchrun | Process's global rank (0–3) |
| `LOCAL_RANK` | torchrun | Process's rank within the current node (0 or 1) |
| `WORLD_SIZE` | torchrun | Total number of processes (4) |
| `GROUP_RANK` | torchrun | Node rank (same as `NODE_RANK`) |
| `MASTER_ADDR` | torchrun (from CLI args) | Master's address (Headless Service DNS) |

## How Kueue Manages the Multi-Node Job

Kueue treats the entire `batch/v1 Job` — both Pods — as a single **Workload**. This provides:

- **Gang scheduling**: both Pods are admitted together; neither runs if there isn't quota for both
- **Quota enforcement**: `2 CPU + 1Gi` × 2 Pods = `4 CPU + 2Gi` total is reserved atomically
- **Preemption**: if a higher-priority job needs resources, Kueue can preempt the whole multi-node job at once

```
Job submitted (2 Pods)
       │
       ▼
Kueue creates Workload
       │
       ▼
QuotaReserved (4 CPU, 2Gi) → Admitted → Both Pods run → Finished
```

## Comparison

| | kueue-pytorch-ddp-demo | This demo |
|--|------------------------|-----------|
| Pods | 1 | **2** |
| Processes (world_size) | 2 | **4** |
| Cross-Pod communication | None | **Yes, via Headless Service** |
| Extra resources needed | None | 1 Headless Service |
| Best for | Single-node multi-GPU | **Multi-node multi-GPU production** |
| GPU equivalent | 1 node × N GPU | **2 nodes × 2 GPU = 4 GPU total** |
