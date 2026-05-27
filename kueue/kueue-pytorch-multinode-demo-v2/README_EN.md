# Kueue + PyTorch Multi-Node DDP Training Demo (kind Multi-Node Cluster)

> **Goal**: Two training Pods run on two different kind Worker nodes, admitted together by Kueue gang scheduling.

## Overview

This demo runs on a **local kind multi-node cluster** and demonstrates:

- **Multi-node kind cluster**: 1 control-plane + 2 worker nodes
- **Kueue gang scheduling**: 2 Pods treated as one Workload — admitted together or not at all
- **Pod anti-affinity**: enforces Pod-0 → worker-1 and Pod-1 → worker-2 (different nodes)
- **PyTorch DDP across nodes**: 2 Pods × 2 processes = world_size 4, gloo backend (CPU mode)
- **Headless Service**: stable DNS for the master Pod, solving multi-node rendezvous

## Architecture

```
Local Docker
└── kind cluster (kueue-demo)
    ├── control-plane      ← system components only (NoSchedule taint)
    ├── worker-1           ← runs Pod-0 (node_rank=0, master)
    └── worker-2           ← runs Pod-1 (node_rank=1, worker)

                    Kueue ClusterQueue
                    (quota + gang scheduling)
                           │
              Workload: job-pytorch-multinode-training
                    (both Pods admitted together)
                           │
          ┌────────────────┴────────────────┐
          │                                 │
    Pod-0 (worker-1)               Pod-1 (worker-2)
    node_rank=0                    node_rank=1
    ┌──────────────────┐           ┌──────────────────┐
    │ torchrun         │           │ torchrun         │
    │  Rank 0 (proc 0) │           │  Rank 2 (proc 0) │
    │  Rank 1 (proc 1) │           │  Rank 3 (proc 1) │
    └────────┬─────────┘           └────────┬─────────┘
             │                              │
             └──── gloo all-reduce (gradient sync) ────┘

    pytorch-master-svc (Headless Service)
      → selects Pod with index=0 (Pod-0)
      → DNS: pytorch-master-svc.default.svc.cluster.local
      → all Pods use this as --master_addr
```

## Files

| File | Description |
|------|-------------|
| `kind-cluster.yaml` | kind cluster config: 1 control-plane + 2 workers |
| `00-kueue-resources.yaml` | ResourceFlavor, ClusterQueue, LocalQueue |
| `01-master-service.yaml` | Headless Service selecting index=0 Pod |
| `02-pytorch-multinode-job.yaml` | Indexed Job with anti-affinity enabled, 2 Pods |

---

## Step 1: Install Prerequisites

Verify that the required tools are installed:

```bash
kind version        # needs v0.20+
kubectl version --client
docker info         # Docker Desktop or Docker Engine must be running
```

Install kind if needed:

```bash
# macOS with Homebrew
brew install kind

# Or download binary directly (Apple Silicon)
curl -Lo /usr/local/bin/kind \
  https://kind.sigs.k8s.io/dl/v0.31.0/kind-darwin-arm64
chmod +x /usr/local/bin/kind
```

---

## Step 2: Create the kind Multi-Node Cluster

### 2.1 Create the cluster

```bash
kind create cluster --config kind-cluster.yaml
```

The cluster is named `kueue-demo` with 3 nodes. Creation takes about 1–2 minutes:

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

### 2.2 Verify the cluster nodes

```bash
kubectl get nodes -o wide
```

Expected output (3 nodes, all Ready):

```
NAME                       STATUS   ROLES           AGE   VERSION
kueue-demo-control-plane   Ready    control-plane   60s   v1.32.0
kueue-demo-worker          Ready    <none>          45s   v1.32.0
kueue-demo-worker2         Ready    <none>          45s   v1.32.0
```

> The `control-plane` node has a `node-role.kubernetes.io/control-plane:NoSchedule` taint. Ordinary Pods without matching tolerations are never scheduled there.

### 2.3 Check node labels (used by anti-affinity)

```bash
kubectl get nodes --show-labels | grep -v control-plane
```

---

## Step 3: Install Kueue

### 3.1 Install Kueue v0.11.4

```bash
kubectl apply --server-side \
  -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.11.4/manifests.yaml
```

### 3.2 Wait for Kueue to become ready

```bash
kubectl -n kueue-system wait deployment/kueue-controller-manager \
  --for=condition=Available --timeout=120s
```

Output:
```
deployment.apps/kueue-controller-manager condition met
```

### 3.3 Verify Kueue components

```bash
kubectl get pods -n kueue-system
```

Expected (all Pods Running):

```
NAME                                        READY   STATUS    AGE
kueue-controller-manager-xxxxxxxxx-xxxxx   2/2     Running   30s
```

### 3.4 Verify CRDs are registered

```bash
kubectl get crd | grep kueue
```

You should see `clusterqueues.kueue.x-k8s.io`, `localqueues.kueue.x-k8s.io`, `workloads.kueue.x-k8s.io`, and others.

---

## Step 4: Deploy the Demo

### 4.1 Create Kueue resources

```bash
kubectl apply -f 00-kueue-resources.yaml
```

Verify:

```bash
kubectl get clusterqueue multinode-cluster-queue -o wide
kubectl get localqueue multinode-user-queue -n default
```

Expected:

```
NAME                     COHORT   PENDING WORKLOADS
multinode-cluster-queue           0

NAME                   CLUSTERQUEUE             PENDING WORKLOADS
multinode-user-queue   multinode-cluster-queue  0
```

### 4.2 Create the Master Headless Service

```bash
kubectl apply -f 01-master-service.yaml
```

Verify:

```bash
kubectl get svc pytorch-master-svc -n default
```

Expected (CLUSTER-IP = None confirms it is a Headless Service):

```
NAME                 TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)     AGE
pytorch-master-svc   ClusterIP   None         <none>        29500/TCP   5s
```

### 4.3 Submit the training Job

```bash
kubectl apply -f 02-pytorch-multinode-job.yaml
```

---

## Step 5: Verify Scheduling Results

### 5.1 Check Kueue Workload status

```bash
kubectl get workloads -n default
```

Expected (ADMITTED=True means Kueue has approved the Workload):

```
NAME                                         QUEUE                  ADMITTED   AGE
job-pytorch-multinode-training-xxxxxxxxxx   multinode-user-queue   True       10s
```

### 5.2 Check Job status

```bash
kubectl get jobs -n default
```

Expected:

```
NAME                         STATUS    COMPLETIONS   DURATION   AGE
pytorch-multinode-training   Running   0/2           10s        15s
```

### 5.3 Verify both Pods run on different worker nodes (key check)

```bash
kubectl get pods -n default -o wide
```

**Expected output**:

```
NAME                                 READY   STATUS    NODE                  AGE
pytorch-multinode-training-0-xxxxx   1/1     Running   kueue-demo-worker     30s
pytorch-multinode-training-1-xxxxx   1/1     Running   kueue-demo-worker2    30s
```

> Key validation: `pytorch-multinode-training-0-*` is on `kueue-demo-worker` and `pytorch-multinode-training-1-*` is on `kueue-demo-worker2`. The Pods are on **different nodes**. This is enforced by `podAntiAffinity`.

### 5.4 Detailed Pod-to-node mapping

```bash
kubectl get pods -n default \
  -o custom-columns="POD:.metadata.name,STATUS:.status.phase,NODE:.spec.nodeName,INDEX:.metadata.labels['batch\.kubernetes\.io/job-completion-index']"
```

Expected:

```
POD                                  STATUS    NODE                   INDEX
pytorch-multinode-training-0-xxxxx   Running   kueue-demo-worker      0
pytorch-multinode-training-1-xxxxx   Running   kueue-demo-worker2     1
```

---

## Step 6: View Training Logs

### 6.1 Stream all Pod logs in real time

```bash
kubectl logs -f -l job-name=pytorch-multinode-training \
  -n default --prefix --max-log-requests=2
```

### 6.2 View individual Pod logs

```bash
# Master Pod (index=0)
kubectl logs -f -l batch.kubernetes.io/job-completion-index=0 \
  -n default -c trainer

# Worker Pod (index=1)
kubectl logs -f -l batch.kubernetes.io/job-completion-index=1 \
  -n default -c trainer
```

### 6.3 Expected log output

Training startup:
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

During training (identical `w`/`b` across all Ranks each epoch proves all-reduce is correct):
```
[pod/.../trainer] [Rank 0/4] Epoch  1/10  loss=4.0374  w=2.1221  b=1.2110
[pod/.../trainer] [Rank 1/4] Epoch  1/10  loss=3.7041  w=2.1221  b=1.2110
[pod/.../trainer] [Rank 2/4] Epoch  1/10  loss=3.8912  w=2.1221  b=1.2110
[pod/.../trainer] [Rank 3/4] Epoch  1/10  loss=3.9203  w=2.1221  b=1.2110
```

Training completion (Rank 0 prints final result):
```
[pod/.../trainer] ===================================================
[pod/.../trainer]   Multi-node DDP training complete
[pod/.../trainer]   world_size=4 (2 nodes x 2 processes/node)
[pod/.../trainer]   Learned : w=3.0028  b=2.0004
[pod/.../trainer]   Target  : w=3.0000  b=2.0000
[pod/.../trainer]   Error   : dw=0.0028  db=0.0004
[pod/.../trainer] ===================================================
```

> **What to look for**: All 4 Ranks show the **same `w` and `b` values** at the end of each epoch — this confirms cross-Pod gradient all-reduce is working correctly.

### 6.4 Wait for Job completion

```bash
kubectl wait job/pytorch-multinode-training \
  --for=condition=Complete --timeout=600s -n default
```

---

## Step 7: Cleanup

### 7.1 Delete Demo resources

```bash
kubectl delete -f 02-pytorch-multinode-job.yaml
kubectl delete -f 01-master-service.yaml
kubectl delete -f 00-kueue-resources.yaml
```

### 7.2 Delete the kind cluster (optional)

```bash
kind delete cluster --name kueue-demo
```

---

## Key Design Decisions

### Why a Headless Service?

For multi-node training, Pod-1 needs Pod-0's address as `--master_addr`. Pod IPs are dynamic and Pod names have random suffixes, so neither is stable enough to hardcode.

**Solution: Indexed Job + Headless Service**

| Mechanism | Purpose |
|-----------|---------|
| `completionMode: Indexed` | Each Pod gets a stable `JOB_COMPLETION_INDEX` env var (0 or 1) |
| Headless Service with `selector: batch.kubernetes.io/job-completion-index: "0"` | Kubernetes automatically labels Indexed Job Pods; the Service always resolves to Pod-0's IP |
| `--node_rank=${JOB_COMPLETION_INDEX}` | Tells `torchrun` which node this process group runs on |

### Why Pod Anti-Affinity?

`podAntiAffinity: requiredDuringSchedulingIgnoredDuringExecution` with `topologyKey: kubernetes.io/hostname` **forces the scheduler to place the two Pods on different physical/virtual nodes**.

Without anti-affinity, both Pods can land on the same worker node in a kind cluster — DDP would still work, but it would not be true multi-node distributed training. Anti-affinity is the single setting that makes this demo a genuine two-node test.

### How Kueue Gang Scheduling Works

```
Job submitted (2 Pods)
       │
       ▼
Kueue creates Workload
       │
       ▼
Check quota: 2 × (500m CPU + 512Mi) = 1 CPU + 1 Gi needed
       │
  Quota available?
  ├── Yes → QuotaReserved → Admitted → both Pods start simultaneously
  └── No  → Pending (wait for quota to free up)
```

Gang scheduling is the key Kueue benefit: either **both** Pods start, or **neither** does. There is no partial start that could leave one Pod waiting forever for a peer that never arrives.

---

## Switching to Real GPUs (2 nodes × 2 GPUs = 4 GPUs total)

Two changes in `02-pytorch-multinode-job.yaml`:

**1. Training script: gloo → nccl + move tensors to GPU**
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

**3. ClusterQueue: add GPU quota** in `00-kueue-resources.yaml`:
```yaml
coveredResources: ["cpu", "memory", "nvidia.com/gpu"]
flavors:
  - name: default-flavor
    resources:
      - name: nvidia.com/gpu
        nominalQuota: "4"
```

---

## Troubleshooting

### Pods stuck in Pending

```bash
kubectl describe pod <pod-name> -n default
```

**Cause 1**: Kueue Workload not yet Admitted (quota insufficient)
```bash
kubectl get workloads -n default
kubectl describe workload <workload-name> -n default
```

**Cause 2**: Anti-affinity cannot be satisfied (not enough worker nodes)
- Confirm the kind cluster has 2 worker nodes: `kubectl get nodes`
- If only 1 worker node exists, either remove anti-affinity or add more nodes

**Cause 3**: Insufficient resources on worker nodes
```bash
kubectl describe node kueue-demo-worker
kubectl describe node kueue-demo-worker2
```

### Both Pods scheduled on the same node

Verify that the `podAntiAffinity` block in `02-pytorch-multinode-job.yaml` is present and correctly indented under `spec.template.spec`.

### Kueue CRD version mismatch

```bash
kubectl get crd clusterqueues.kueue.x-k8s.io \
  -o jsonpath='{.spec.versions[*].name}'
```

Ensure the API version is `v1beta1`. Kueue v0.11.4 uses `kueue.x-k8s.io/v1beta1`, which matches the YAML in this demo.

### PyTorch install is slow

The default `python:3.11-slim` image downloads PyTorch (~200 MB) on every Pod start. To speed up iteration, build a custom image with PyTorch pre-installed.

---

## Comparison

| | kueue-pytorch-ddp-demo | This demo |
|--|------------------------|-----------|
| kind worker nodes needed | 1 | **2** |
| Number of Pods | 1 | **2** |
| Processes (world_size) | 2 | **4** |
| Cross-Pod communication | None | **Yes, via Headless Service** |
| Pod anti-affinity | Not needed | **Required (ensures cross-node)** |
| Best for | Single-node multi-GPU | **Multi-node multi-GPU simulation** |
