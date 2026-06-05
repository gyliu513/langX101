# Kueue + JobSet: Multi-Node PyTorch Training on CPU

A self-contained demo that runs a **multi-node PyTorch DDP** training job on a
local **kind** cluster — **no GPU required, everything runs on CPU**.

It shows how three pieces fit together:

| Piece | Role |
|-------|------|
| **kind** | A local Kubernetes cluster with **multiple worker nodes** |
| **JobSet** | Groups the training Pods into one gang and gives them stable DNS names for `torchrun` rendezvous |
| **Kueue** | Queues and **gang-admits** the JobSet against a CPU/memory quota |

The training job is a tiny linear-regression (`y = 3x + 2`) trained with
PyTorch `DistributedDataParallel` over the **gloo** (CPU) backend across
**2 nodes × 2 processes = world_size 4**.

---

## Topology

```
kind cluster (kueue-jobset-demo)
 ├─ control-plane
 ├─ worker-1   ──►  Pod pytorch-workers-0-0  (node_rank 0, MASTER)  ┐
 ├─ worker-2   ──►  Pod pytorch-workers-0-1  (node_rank 1)          │  JobSet "pytorch"
 └─ worker-3        (spare capacity)                                ┘  gang-admitted by Kueue

  2 nodes × --nproc_per_node=2  =>  world_size = 4   (gloo / CPU)
```

`podAntiAffinity` forces the two Pods onto **different nodes**, so this is a
genuine multi-node run rather than two Pods on one machine.

JobSet auto-creates a headless Service named after the JobSet, giving every Pod
a stable DNS name:

```
<jobset>-<replicatedJob>-<jobIndex>-<podIndex>.<jobset>
pytorch-workers-0-0.pytorch        # the master / node_rank 0
```

All workers point `torchrun --master_addr` at that name to rendezvous.

---

## Prerequisites

- `docker` (running)
- `kind`
- `kubectl`

Versions pinned by the scripts: **JobSet v0.12.0**, **Kueue v0.18.0**.
(Kueue v0.18 ships with the `jobset.x-k8s.io/jobset` integration **enabled by
default**, so no ConfigMap patching is needed.)

---

## Quick start

```bash
./setup.sh     # create the multi-node kind cluster, install JobSet + Kueue, create the quota
./run.sh       # submit the PyTorch JobSet and stream the master pod's logs
./cleanup.sh   # delete the whole kind cluster
```

The first run is slow: each Pod `pip install`s the CPU build of PyTorch before
training starts. Subsequent re-runs reuse the cached image layers in the kind
nodes only if the image is the same; the `pip install` itself repeats per Pod.

---

## What each file does

| File | Purpose |
|------|---------|
| `kind-cluster.yaml` | 1 control-plane + 3 worker nodes |
| `00-kueue-resources.yaml` | `ResourceFlavor`, `ClusterQueue` (8 CPU / 8Gi), `LocalQueue` |
| `01-pytorch-jobset.yaml` | The `JobSet` running multi-node `torchrun` DDP on CPU |
| `setup.sh` | Cluster + JobSet + Kueue + quota |
| `run.sh` | Submit the JobSet, show admission + placement, tail logs |
| `cleanup.sh` | `kind delete cluster` |

---

## Watching it work

```bash
# Kueue admitted the JobSet (ADMITTED=True means its quota was reserved as a gang)
kubectl get workloads -o wide

# The two trainer pods, on two different nodes
kubectl get pods -l app=pytorch-jobset -o wide

# Logs from each rank. The Pod's DNS hostname is fixed (pytorch-workers-0-0),
# but the Pod object name has a random suffix, so select by completion index:
kubectl logs -f -l app=pytorch-jobset,batch.kubernetes.io/job-completion-index=0  # node_rank 0 (master)
kubectl logs -f -l app=pytorch-jobset,batch.kubernetes.io/job-completion-index=1  # node_rank 1
```

Expected tail of the master log:

```
===================================================
  Multi-node DDP training complete
  world_size=4 (2 nodes x 2 processes/node)
  Learned : w=3.0xxx  b=2.0xxx
  Target  : w=3.0000  b=2.0000
===================================================
```

When the JobSet finishes, its Workload is marked Finished and the reserved
quota is returned to the `ClusterQueue`.

---

## How Kueue gates the JobSet

1. The JobSet carries the label `kueue.x-k8s.io/queue-name: jobset-user-queue`.
   Kueue intercepts it and creates a **Workload** object describing the total
   resource ask (2 Pods × 1 CPU + 1Gi = **2 CPU + 2Gi**).
2. Kueue checks the `jobset-cluster-queue` quota (8 CPU / 8Gi). If the *whole*
   ask fits, it **admits the JobSet as a unit** (gang scheduling) and unsuspends
   it; otherwise the JobSet waits in the queue.
3. Only after admission does JobSet create the Jobs/Pods, which then run
   `torchrun` and train.

To see queuing in action, shrink the `ClusterQueue` quota below 2 CPU and submit
two JobSets — the second stays `Pending` until the first finishes.

---

## Moving to real GPUs

The manifests are annotated inline. The four changes:

1. `backend="gloo"` → `backend="nccl"`
2. `device = torch.device("cpu")` → `device = torch.device(f"cuda:{local_rank}")`
3. Uncomment `nvidia.com/gpu` under `resources.limits`
4. Add an `nvidia.com/gpu` quota in `00-kueue-resources.yaml` and label the GPU
   nodes on the `ResourceFlavor`
