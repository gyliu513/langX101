# Kueue + PyTorch DDP Data-Parallel Training Demo

> **Dependencies**: Kueue only — no Kubeflow, no JobSet, no KubeRay required

## Overview

This demo shows the **simplest possible** way to schedule a PyTorch Distributed Data Parallel (DDP) training job through Kueue:

- Uses a plain `batch/v1 Job` — adding a single `kueue.x-k8s.io/queue-name` label hands control to Kueue
- `torchrun --nproc_per_node=2` launches 2 training processes inside one Pod, simulating data parallelism
- Uses the `gloo` communication backend — **runs on CPU only**, no GPU required
- Training task: linear regression on a synthetic dataset (`y = 3x + 2`), verifying that DDP gradient synchronization works correctly

## Architecture

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
│  │           (all-reduce gradients)         │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
         ↑ Kueue Workload manages scheduling
```

## Files

| File | Description |
|------|-------------|
| `00-kueue-resources.yaml` | ResourceFlavor, ClusterQueue, LocalQueue |
| `01-pytorch-ddp-job.yaml` | PyTorch DDP training Job (with inline training script) |

## Prerequisites

- A Kubernetes cluster (kind, minikube, etc.)
- Kueue installed (`kueue.x-k8s.io/v1beta2`)

Install Kueue:
```bash
kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.11.4/manifests.yaml
```

## Steps

### 1. Create Kueue Queue Resources

```bash
kubectl apply -f 00-kueue-resources.yaml
```

Verify:
```bash
kubectl get clusterqueue pytorch-cluster-queue
kubectl get localqueue pytorch-user-queue -n default
```

### 2. Submit the Training Job

```bash
kubectl apply -f 01-pytorch-ddp-job.yaml
```

### 3. Observe Kueue Scheduling

```bash
# View the Workload (Kueue's scheduling unit)
kubectl get workloads -n default

# Check Job status
kubectl get jobs -n default

# Check Pod status
kubectl get pods -n default
```

### 4. Stream Training Logs

```bash
kubectl logs -f -l job-name=pytorch-ddp-training -n default
```

### 5. Expected Output

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

Key observations:
- **Both ranks show identical `w` and `b` at the end of each epoch** → DDP all-reduce gradient sync is working correctly
- Each rank sees only 500 samples (data parallel sharding)
- Loss drops from 6.0 to ~0.01 in just a few epochs → model successfully learned `y = 3x + 2`

### 6. Cleanup

```bash
kubectl delete -f 01-pytorch-ddp-job.yaml
kubectl delete -f 00-kueue-resources.yaml
```

## How DDP Works Here

| Concept | Description |
|---------|-------------|
| `DistributedSampler` | Splits the dataset evenly across ranks to avoid duplicate data |
| `DistributedDataParallel` | Wraps the model; automatically all-reduces gradients during backward pass |
| `gloo` backend | CPU communication backend; works without GPU or NCCL |
| `torchrun` | Automatically sets `RANK`, `WORLD_SIZE`, `MASTER_ADDR`, etc. |

## How Kueue Manages the Job

When the Job is submitted:
1. Kueue intercepts it via the `kueue.x-k8s.io/queue-name` label and creates a **Workload** object
2. The Workload is queued in `pytorch-user-queue` (LocalQueue) → `pytorch-cluster-queue` (ClusterQueue)
3. Kueue checks available quota (2 CPU, 1Gi memory in this case) and **admits** the Workload
4. The underlying Job's pods are allowed to run
5. On completion, Kueue marks the Workload as **Finished** and releases the quota

```
Job submitted
     │
     ▼
Kueue creates Workload
     │
     ▼
QuotaReserved → Admitted → Pod running → Finished
```

## Extending to GPU

If your cluster has GPUs, two changes are needed:

1. Change `dist.init_process_group(backend="gloo")` to `backend="nccl"`
2. Add GPU resource requests to the Job spec:
   ```yaml
   resources:
     limits:
       nvidia.com/gpu: "2"
   ```
   Also add `nvidia.com/gpu` to the ClusterQueue's `coveredResources` and set a quota.

## Comparison: This Demo vs Kubeflow TrainJob

| | This Demo | kueue-trainjob-demo |
|--|-----------|---------------------|
| Dependencies | **Kueue only** | Kueue + Kubeflow Training Operator v2 + JobSet |
| Job type | `batch/v1 Job` | `trainer.kubeflow.org/v1alpha1 TrainJob` |
| Multi-node | Single-node, multi-process | Multi-node, multi-process |
| Best for | Quick validation, single-node multi-GPU | Production multi-node distributed training |

## Why This Approach

The `batch/v1 Job` is natively supported by Kueue with **zero additional operators**. Adding a single label is all it takes to get:

- **Fair scheduling** across multiple teams/namespaces
- **Quota enforcement** (jobs wait in queue if resources are exhausted)
- **Gang scheduling** (via `parallelism`/`completions`)
- **Priority and preemption** support

This makes it the ideal starting point before introducing more complex operators like Kubeflow or KubeRay.
