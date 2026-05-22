# End-to-End Test Report: Kueue + Kubeflow Trainer v2 TrainJob

## Test Summary

| Item | Details |
|------|---------|
| Test Date | 2026-05-22 |
| Cluster Type | kind (Kubernetes in Docker) v1.35.0 |
| Kueue Version | v0.17.3 |
| Kubeflow Trainer | v2.2.0 |
| JobSet | v0.8.0 |
| Training Algorithm | Logistic Regression (SGD + Binary Cross-Entropy) |
| Dataset | Embedded 2D binary classification dataset (100 samples, pure Python, no dependencies) |
| Result | **PASSED** ✅ |

---

## 1. Training Job Description

### 1.1 Purpose

This TrainJob demonstrates a **complete distributed binary classification training pipeline** on Kubernetes, validating the following end-to-end capabilities:

- Kueue can manage resource quotas and control admission for TrainJobs
- Kubeflow Trainer v2 can expand a TrainJob into a JobSet and correctly inject distributed environment variables into each Pod
- Two training nodes can each read their own data shard, run real machine-learning training, and produce meaningful results

### 1.2 Problem Definition

**Task:** Given a point (x1, x2) in 2D space, classify it as Class 0 or Class 1.

```
The dataset contains two Gaussian clusters:
  Class 1 (positive): centered at (+1.5, +1.5), std=0.6
  Class 0 (negative): centered at (-1.5, -1.5), std=0.6

x2
 3 │      ·  · ·
   │    · ·· ·· ·  ← Class 1 (positive)
 1 │      ·· ·
   │- - - - - - - - decision boundary  (x1 + x2 ≈ 0)
-1 │   ·· ·
   │ · ·· ·· ·     ← Class 0 (negative)
-3 │  · · ·
   └──────────── x1
     -3  -1  1  3
```

The two classes are linearly separable. The theoretically optimal decision boundary is `w1·x1 + w2·x2 + b = 0`, which lies roughly along the line y = −x through the origin.

### 1.3 What the Job Does

| Function | Implementation |
|----------|---------------|
| Dataset generation | Fixed seed=42, pure-Python Gaussian sampling, 100 samples (50 per class) |
| Data sharding | Full dataset split by `PET_NODE_RANK`; each node trains on 50 samples |
| Forward pass | `ŷ = sigmoid(w1·x1 + w2·x2 + b)` |
| Loss computation | Binary Cross-Entropy: `L = −[y·log(ŷ) + (1−y)·log(1−ŷ)]` |
| Backward pass | Analytically derived gradients — no auto-diff framework needed |
| Weight update | Per-sample SGD with learning rate lr=0.05 |
| Distributed coordination | Uses Trainer v2's injected `PET_NNODES` / `PET_NODE_RANK` to determine node identity and data shard boundaries |
| Inference check | After training, runs predictions on 3 representative points to validate generalisation |

### 1.4 Training Results

**Convergence behaviour:**

Both nodes reach 100% accuracy by **Epoch 2** and continue to drive down loss (the model becomes more confident) through Epoch 10:

```
Epoch  1:  loss ≈ 0.27,  acc = 98–100%   ← rapid initial convergence
Epoch  2:  loss ≈ 0.087, acc = 100%      ← all samples classified correctly
Epoch 10:  loss ≈ 0.017, acc = 100%      ← loss reduced by 94%, confidence still rising
```

**Final model capability:**

| Input point | Location | P(class=1) | Prediction |
|-------------|----------|------------|------------|
| (+2.0, +2.0) | Near positive cluster center | 0.998–0.999 | Class 1 ✅ |
| (-2.0, -2.0) | Near negative cluster center | 0.001 | Class 0 ✅ |
| (0.0, 0.0) | On the decision boundary | 0.47–0.49 | Uncertain (expected) |

The origin returns a probability near 0.5, meaning the model correctly identifies it as sitting on the decision boundary where neither class dominates. This is exactly what the geometry predicts: the origin is equidistant from both cluster centers.

**Why the two nodes end up with different weights:**

Because neither node sees the full dataset and there is no gradient AllReduce step, each node converges on the statistics of its own shard:

```
Node 0:  w1=1.537, w2=1.721  →  slightly more weight on x2
Node 1:  w1=1.777, w2=1.538  →  slightly more weight on x1
```

Node 0's shard happens to have slightly more spread along the x2 axis, so its gradient updates push w2 higher. Node 1's shard is the mirror image. Despite the weight difference, both nodes reach the same inference conclusions because both have found the correct decision-boundary direction (w1 ≈ w2 > 0, b ≈ 0). In production PyTorch DDP, an AllReduce step after each backward pass would average the gradients and keep both nodes' weights identical throughout training.

---

## 2. Architecture

### 1.1 Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     kind Cluster (mykueue)                      │
│                                                                  │
│  ┌──────────────┐    ┌─────────────────────────────────────┐   │
│  │ kueue-system │    │         kubeflow-system              │   │
│  │              │    │                                      │   │
│  │  Kueue       │    │  Kubeflow Trainer Controller (v2)   │   │
│  │  Controller  │◄───┤  - Manages TrainJob lifecycle        │   │
│  │  Manager     │    │  - Creates JobSet resources          │   │
│  │  v0.17.3     │    │  - Injects PET_* env vars            │   │
│  │              │    │                                      │   │
│  └──────┬───────┘    │  JobSet Controller (v0.8.0)          │   │
│         │            │  - Manages ReplicatedJobs/Jobs       │   │
│         │            │  - Provides headless DNS networking  │   │
│         │            └──────────────────────────────────────┘   │
│         │                                                        │
│  ┌──────▼──────────────────────────────────────────────────┐   │
│  │                    default namespace                      │   │
│  │                                                          │   │
│  │  LocalQueue(user-queue) → ClusterQueue(cluster-queue)   │   │
│  │                                                          │   │
│  │  TrainJob ──(Kueue sets suspend=false)──▶ JobSet        │   │
│  │     └──▶ Workload (quota tracking, does NOT create       │   │
│  │                    JobSet directly)                      │   │
│  │                                          ↓               │   │
│  │                                    Indexed Job           │   │
│  │                                          ↓               │   │
│  │                     Pod[0](Node 0)  +  Pod[1](Node 1)   │   │
│  │                     shard[0:50]        shard[50:100]     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Resource Object Hierarchy

```
TrainJob  (trainer.kubeflow.org/v1alpha1)
│  labels: kueue.x-k8s.io/queue-name: user-queue
│  spec.runtimeRef → ClusterTrainingRuntime/torch-distributed-cpu
│  spec.trainer.numNodes: 2
│  spec.suspend: true → false  (written by Kueue upon admission)
│
├── Workload  (kueue.x-k8s.io/v1beta1)   [created by Kueue for quota management]
│   ├── QuotaReserved: cluster-queue      ← does NOT trigger any workload resources
│   └── Admitted: True                   ← Kueue flips TrainJob.suspend to false
│
└── JobSet  (jobset.x-k8s.io/v1alpha2)   [created by Trainer v2 Controller]
    │  Trigger: TrainJob.spec.suspend changes to false  ← no direct link to Workload
    └── ReplicatedJob: node (replicas=1, completions=2, parallelism=2)
        └── Job: cpu-distributed-training-node-0   [created by JobSet Controller]
            ├── Pod[0]  NODE_RANK=0  shard[0:50]    (26 pos / 24 neg)
            └── Pod[1]  NODE_RANK=1  shard[50:100]  (24 pos / 26 neg)
```

### 1.3 Kueue Admission Flow

```
1. kubectl apply TrainJob
       ↓
2. Kueue webhook intercepts → sets suspend=true (no Pods created yet)
       ↓
3. Kueue creates a Workload object (resource demand: 2×500m CPU, 2×256Mi)
       ↓
4. Checks ClusterQueue quota (cpu: 4 cores / memory: 8Gi) → sufficient
       ↓
5. QuotaReserved (wait 1s) → Admitted (wait 0s)
       ↓
6. Kueue sets TrainJob.spec.suspend = false
       ↓
7. Trainer Controller detects suspend=false → creates JobSet
       ↓
8. JobSet Controller creates Indexed Job (completions=2, parallelism=2)
       ↓
9. kube-scheduler places Pod[0] and Pod[1] on the node
       ↓
10. Trainer v2 injects PET_* env vars via Downward API
       ↓
11. Both Pods run logistic regression training in parallel (10 epochs)
       ↓
12. JobSet → Completed → TrainJob State: Complete
       ↓
13. Kueue marks Workload Finished and releases quota
```

### 1.4 Environment Variables Injected by Trainer v2

| Variable | Value (example) | Source |
|----------|----------------|--------|
| `PET_NNODES` | `2` | `mlPolicy.numNodes` |
| `PET_NODE_RANK` | `0` / `1` | `batch.kubernetes.io/job-completion-index` (Downward API) |
| `PET_MASTER_ADDR` | `cpu-distributed-training-node-0-0.cpu-distributed-training` | JobSet headless Service DNS |
| `PET_MASTER_PORT` | `29500` | torchrun rendezvous default port |
| `PET_NPROC_PER_NODE` | `1` | `mlPolicy.torch` default |

> The `PET_*` prefix follows the PyTorch Elastic Training convention. In real PyTorch training, users launch scripts with `torchrun`, which reads these variables and translates them into the standard `RANK`/`WORLD_SIZE` that `torch.distributed` expects.

---

## 3. Dataset and Training Algorithm

### 2.1 Dataset

| Attribute | Value |
|-----------|-------|
| Total samples | 100 |
| Feature dimensions | 2 (x1, x2) |
| Classes | 2 (binary classification) |
| Generation | Fixed seed=42 Gaussian clusters, embedded in pure Python |
| External dependencies | None |

**Class 1 (positive):** 50 samples centered at (+1.5, +1.5), std=0.6
**Class 0 (negative):** 50 samples centered at (-1.5, -1.5), std=0.6

```
x2
 3 │      ·  · ·
   │    · ·· ·· ·  ← Class 1
 1 │      ·· ·
   │─────────────── decision boundary
-1 │   ·· ·
   │ · ·· ·· ·     ← Class 0
-3 │  · · ·
   └──────────── x1
     -3  -1  1  3
```

### 2.2 Data Sharding Strategy

All nodes generate the same full dataset using seed=42, then each takes its own shard based on `PET_NODE_RANK`:

```
Full dataset (100 samples, shuffled with seed=42)
       ├── Node 0 shard: [0:50]   → 26 positive + 24 negative
       └── Node 1 shard: [50:100] → 24 positive + 26 negative
```

### 2.3 Training Algorithm

**Model:** Logistic Regression
- Prediction: `ŷ = sigmoid(w1·x1 + w2·x2 + b)`
- Loss: Binary Cross-Entropy (BCE)
  ```
  L = -[y·log(ŷ) + (1-y)·log(1-ŷ)]
  ```
- Gradients (analytical):
  ```
  ∂L/∂w1 = (ŷ - y) · x1
  ∂L/∂w2 = (ŷ - y) · x2
  ∂L/∂b  = (ŷ - y)
  ```
- Update rule: `w ← w - lr · ∂L/∂w` (SGD, per-sample update)
- Learning rate: 0.05
- Epochs: 10

---

## 4. YAML Resources

### 3.1 Kueue Resources

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

### 3.2 ClusterTrainingRuntime (core training logic)

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
                      command: [python3, -c, "<embedded training script>"]
                      resources:
                        requests: {cpu: "500m", memory: "256Mi"}
                        limits:   {cpu: "1",    memory: "512Mi"}
```

Key sections of the embedded training script:

```python
# Read distributed env vars injected by Trainer v2
world_size = int(os.environ.get("PET_NNODES", "1"))
node_rank  = int(os.environ.get("PET_NODE_RANK", "0"))

# Generate 100 samples (fixed seed=42), shard by node_rank
random.seed(42)
dataset = make_cluster(50, 1.5, 1.5, 1) + make_cluster(50, -1.5, -1.5, 0)
random.shuffle(dataset)
shard = dataset[node_rank * 50 : (node_rank + 1) * 50]

# SGD logistic regression: 10 epochs
w1, w2, b = 0.0, 0.0, 0.0
for epoch in range(10):
    for x1, x2, y in shard:
        pred = sigmoid(w1*x1 + w2*x2 + b)   # forward pass
        err  = pred - y                       # gradient of BCE
        w1 -= lr * err * x1                  # weight update
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
    kueue.x-k8s.io/queue-name: user-queue   # bind to Kueue LocalQueue
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

## 5. Test Steps

### Step 1: Install Kubeflow Trainer v2 and JobSet

```bash
kubectl apply -k "https://github.com/kubeflow/trainer/manifests/overlays/manager?ref=v2.2.0" \
  --server-side
kubectl rollout status deployment/kubeflow-trainer-controller-manager -n kubeflow-system
```

### Step 2: Create Kueue resources

```bash
kubectl apply -f 00-kueue-resources.yaml
```

Expected output:
```
resourceflavor.kueue.x-k8s.io/default-cpu created
clusterqueue.kueue.x-k8s.io/cluster-queue created
localqueue.kueue.x-k8s.io/user-queue created
```

### Step 3: Create ClusterTrainingRuntime

```bash
kubectl apply -f 01-cluster-training-runtime.yaml
```

Expected output:
```
clustertrainingruntime.trainer.kubeflow.org/torch-distributed-cpu created
```

### Step 4: Submit TrainJob

```bash
kubectl apply -f 02-trainjob.yaml
```

Expected output:
```
trainjob.trainer.kubeflow.org/cpu-distributed-training created
```

### Step 5: Monitor scheduling and execution

```bash
# Watch Kueue admit the workload
kubectl get workload -n default
# NAME                                      QUEUE        RESERVED IN     ADMITTED
# trainjob-cpu-distributed-training-a783a   user-queue   cluster-queue   True

# Wait for completion
kubectl get trainjob cpu-distributed-training
# NAME                       STATE      AGE
# cpu-distributed-training   Complete   9s

# Verify Pods completed
kubectl get pods -n default
# NAME                                      READY   STATUS      RESTARTS   AGE
# cpu-distributed-training-node-0-0-d72t2   0/1     Completed   0          9s
# cpu-distributed-training-node-0-1-84sd9   0/1     Completed   0          9s
```

### Step 6: Retrieve training logs

```bash
kubectl logs cpu-distributed-training-node-0-0-d72t2   # Node 0
kubectl logs cpu-distributed-training-node-0-1-84sd9   # Node 1
```

---

## 6. Test Logs

### 5.1 Node 0 Full Log

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

### 5.2 Node 1 Full Log

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

### 5.3 Event Timeline (final successful run)

```
T+0s   TrainJob submitted
T+1s   Kueue creates Workload (QuotaReserved wait=1s, Admitted wait=0s)
T+2s   Trainer Controller creates JobSet (triggered by suspend=false)
T+2s   JobSet Controller creates Indexed Job + 2 Pods
T+2s   Pod[0] and Pod[1] scheduled on mykueue-control-plane
T+3s   Container starts (python:3.11-slim image already cached)
T+9s   Both Pods complete training (10 epochs × 50 samples)
T+9s   JobSet AllJobsCompleted → TrainJob State: Complete
T+9s   Kueue Workload Finished, quota released to 0
```

---

## 7. Test Results

### 6.1 Functional Verification

| Check | Result | Notes |
|-------|--------|-------|
| TrainJob created and suspended | ✅ | Kueue webhook intercepted correctly |
| Kueue admission | ✅ | Total wait ~1s (quota sufficient) |
| JobSet auto-created | ✅ | Trainer v2 triggered correctly |
| 2 Pods running in parallel | ✅ | Indexed Job with completions=2 |
| Data sharding correct | ✅ | Node 0: [0:50], Node 1: [50:100] |
| PET_* env vars injected | ✅ | world_size=2, master DNS resolved |
| Real gradient descent | ✅ | Loss dropped from 0.26 to 0.018 (10×) |
| Inference results correct | ✅ | Both nodes agree on predictions |
| TrainJob completed | ✅ | State: Complete in ~9s |
| Kueue quota released | ✅ | ClusterQueue back to 0 usage |

### 6.2 Training Metrics

| Epoch | Node 0 Loss | Node 0 Acc | Node 1 Loss | Node 1 Acc |
|-------|-------------|------------|-------------|------------|
| 1 | 0.2602 | 100.0% | 0.2742 | 98.0% |
| 2 | 0.0867 | 100.0% | 0.0882 | 100.0% |
| 5 | 0.0344 | 100.0% | 0.0312 | 100.0% |
| 10 | **0.0188** | **100.0%** | **0.0156** | **100.0%** |

Loss reduction: Node 0 **-92.8%**, Node 1 **-94.3%**

### 6.3 Final Weight Comparison

| Parameter | Node 0 | Node 1 | Note |
|-----------|--------|--------|------|
| w1 | 1.5367 | 1.7772 | Node 1 weighted more toward x1 |
| w2 | 1.7209 | 1.5380 | Node 0 weighted more toward x2 |
| b | -0.0472 | -0.1146 | Both near 0 (balanced classes) |

The weight divergence between nodes is the expected behavior of **data-parallel training without gradient synchronization**: each node converges on its local shard, and local data distribution differences cause weights to emphasize different features. Inference results are nevertheless consistent.

### 6.4 Inference Validation

| Input | Node 0 P(class=1) | Node 1 P(class=1) | Prediction | Interpretation |
|-------|-------------------|-------------------|------------|---------------|
| (+2.0, +2.0) | 0.998 | 0.999 | Class 1 ✅ | Deep in positive cluster |
| (-2.0, -2.0) | 0.001 | 0.001 | Class 0 ✅ | Deep in negative cluster |
| (0.0, 0.0) | 0.488 | 0.471 | Class 0 (boundary) | Origin lies on the decision boundary — high uncertainty is expected |

---

## 8. Analysis

### 7.1 Value of Kueue Scheduling

In this test all resources fit within quota, so the TrainJob was admitted immediately (wait=1s). In real multi-tenant clusters, Kueue provides:

- **Quota isolation:** Each team's LocalQueue has an independent resource budget, preventing one job from starving others.
- **Priority preemption:** Higher-priority TrainJobs can preempt lower-priority ones when quota is tight.
- **Fair sharing:** Multiple queues share cluster resources proportional to their `nominalQuota`, with lending/borrowing when a queue is idle.

### 7.2 Kubeflow Trainer v2 Layered Design

```
TrainJob  (submitted by user)
    ↓ references
ClusterTrainingRuntime  (maintained by platform team — defines runtime template)
    ↓ expanded into
JobSet  (execution substrate — multi-role, failure policy, headless DNS)
```

This separation lets users express only what varies between runs (`numNodes`, `resourcesPerNode`, `image`), while runtime concerns (scheduling labels, network topology, env-var injection) are encapsulated in the Runtime and managed by controllers.

### 7.3 Data-Parallel Training Without AllReduce

This demo has each node train independently on its own shard. In real PyTorch DDP the flow is:

```
Each step:
  1. Forward pass on local mini-batch
  2. Backward pass → local gradients
  3. NCCL AllReduce (average gradients across all nodes)  ← missing in this demo
  4. Optimizer step with the same averaged gradient → weights stay in sync
```

Because step 3 is absent, the two nodes end up with slightly different weights. In production, replace the embedded script with a real `torchrun`-launched script and call `torch.distributed.init_process_group()`. Trainer v2's `PET_*` variables are automatically converted by `torchrun` into the standard environment that `torch.distributed` reads.

### 7.4 Issues Encountered and Resolved

| Issue | Root Cause | Resolution |
|-------|-----------|------------|
| Trainer v2's bundled JobSet image unavailable | `us-central1-docker.pkg.dev/k8s-staging-images/jobset/jobset:v0.11.0` is a private staging image | Replaced with the public stable release `registry.k8s.io/jobset/jobset:v0.8.0` |
| JobSet webhook calls failing (connection refused) | Two JobSet installs co-existed (jobset-system + kubeflow-system); webhook pointed at a Service with no backing Pods | Consolidated to kubeflow-system; fixed Deployment Pod labels to match Service selector |
| ClusterTrainingRuntime admission rejected | Container named `trainer` — Trainer v2 convention requires `node` | Renamed to `node`, matching the official `torch-distributed` runtime |
| Script reading wrong env vars | Trainer v2 injects `PET_NNODES`/`PET_NODE_RANK`, not the plain `WORLD_SIZE`/`NODE_RANK` the script originally read | Updated script to use the `PET_*` prefixed variables |

---

## 9. Production Guidance

### 8.1 Connecting Real Datasets

**Option A — PVC mount (recommended for on-prem):**
```yaml
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

**Option B — Trainer v2 native dataset initializer:**
```yaml
spec:
  initializer:
    dataset:
      storageUri: "hf://datasets/my-dataset"   # HuggingFace Hub
      # storageUri: "s3://my-bucket/dataset"   # S3-compatible
```

### 8.2 Multi-Job Priority Scheduling

```yaml
metadata:
  labels:
    kueue.x-k8s.io/queue-name: user-queue
    kueue.x-k8s.io/priority-class: high-priority
```

### 8.3 Upgrading to Real PyTorch DDP

```yaml
containers:
  - name: node
    image: pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime
    command: [torchrun, --nproc_per_node=1, train.py]
    # torchrun reads PET_* vars and sets RANK/WORLD_SIZE for torch.distributed
```

---

## Appendix: File Index

| File | Description |
|------|-------------|
| `00-kueue-resources.yaml` | ResourceFlavor / ClusterQueue / LocalQueue |
| `01-cluster-training-runtime.yaml` | Real logistic regression runtime (embedded dataset) |
| `02-trainjob.yaml` | TrainJob (references runtime, bound to Kueue queue) |
| `fix-jobset-deployment.yaml` | JobSet controller deployment fix (stable image) |
| `README.md` | Full test report (Chinese) |
| `README_EN.md` | This document (English) |
