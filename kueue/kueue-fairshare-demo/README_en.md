# Kueue Fair Share Demo: 2:3 Ratio with Elastic Jobs

This document demonstrates how Kueue distributes resources between two teams in a **2:3** ratio using Fair Sharing. Both jobs are elastic — they request up to 10 CPUs but can run with fewer. All commands below include their **actual output** from a live kind cluster along with annotated **Kueue controller logs**.

---

## Scenario Design

```
Cohort: fairshare-cohort  (total capacity = 10 CPUs, sum of two CQ nominal quotas)
│
├── ClusterQueue: cq-team-a  ── nominalQuota=4 CPU, weight=2  (2/5 = 40%)
│   └── LocalQueue: lq-team-a  (namespace: fairshare-team-a)
│       └── elastic-job-team-a: up to 10 pods × 1CPU, min 2 pods
│
└── ClusterQueue: cq-team-b  ── nominalQuota=6 CPU, weight=3  (3/5 = 60%)
    └── LocalQueue: lq-team-b  (namespace: fairshare-team-b)
        └── elastic-job-team-b: up to 10 pods × 1CPU, min 2 pods
```

### Key Configuration

| Setting | Value | Purpose |
|---|---|---|
| `fairSharing.weight` | 2 / 3 | Weight used by the Kueue FairSharing algorithm to set the proportional entitlement |
| `nominalQuota` | 4 / 6 | Guaranteed minimum resource for each CQ, embodying the 2:3 ratio |
| `borrowingLimit: "0"` | Phase 2 | Prevents borrowing, enforcing strict nominalQuota allocation |
| `kueue.x-k8s.io/job-min-parallelism` | 2 | PartialAdmission: Kueue may scale parallelism down from 10 to as few as 2 |
| `fairSharing.preemptionStrategies` | `[LessThanOrEqualToFinalShare, LessThanInitialShare]` | Global Kueue config enabling fair-share preemption |

### Two-Phase Demo

```
Phase 1 (Borrowing)   ── CQs without borrowingLimit; only team-b runs
                         Job-B borrows team-a's idle 4 CPUs
                         → Job-B runs with 10 pods (6 nominal + 4 borrowed)

Phase 2 (Fair Share)  ── CQs set borrowingLimit=0; both jobs submitted simultaneously
                         Kueue PartialAdmission elastically adjusts parallelism
                         → Job-A runs with 4 pods  (requested=10 → admitted=4)
                         → Job-B runs with 6 pods  (requested=10 → admitted=6)
                         → 4:6 = 2:3 ✓
```

---

## Prerequisites

```bash
kubectl get nodes                       # kind cluster is running
kubectl get pods -n kueue-system        # Kueue controller is Running
kubectl get resourceflavor              # default-flavor exists
```

```
NAME                    STATUS   ROLES           AGE   VERSION
mykueue-control-plane   Ready    control-plane   20h   v1.35.0

NAME                                        READY   STATUS    RESTARTS   AGE
kueue-controller-manager-795b49676b-6zgcb   1/1     Running   0          20h

NAME             AGE
default-flavor   20h
```

---

## File Overview

```
01-namespaces.yaml              Namespace: fairshare-team-a / fairshare-team-b
02-clusterqueue-team-a.yaml     CQ: cq-team-a, nominalQuota=4, weight=2, borrowingLimit=0
03-clusterqueue-team-b.yaml     CQ: cq-team-b, nominalQuota=6, weight=3, borrowingLimit=0
04-localqueues.yaml             LocalQueue: lq-team-a / lq-team-b
05-elastic-job-team-b.yaml      Elastic Job: max 10 pods, min 2, sleep 300s
06-elastic-job-team-a.yaml      Elastic Job: max 10 pods, min 2, sleep 300s
```

---

## Enable Kueue FairSharing

FairSharing is disabled by default; it requires a ConfigMap change and controller restart.

```bash
# Export the current config
kubectl get configmap kueue-manager-config -n kueue-system \
  -o jsonpath='{.data.controller_manager_config\.yaml}' > /tmp/kueue-config.yaml

# Uncomment the fairSharing section
sed -i '' 's|#fairSharing:|fairSharing:|' /tmp/kueue-config.yaml
sed -i '' 's|#  preemptionStrategies: \[LessThan.*\]|  preemptionStrategies: [LessThanOrEqualToFinalShare, LessThanInitialShare]|' /tmp/kueue-config.yaml

# Apply the updated ConfigMap
kubectl create configmap kueue-manager-config \
  -n kueue-system \
  --from-file=controller_manager_config.yaml=/tmp/kueue-config.yaml \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart the controller to pick up the new config
kubectl rollout restart deployment/kueue-controller-manager -n kueue-system
kubectl rollout status deployment/kueue-controller-manager -n kueue-system --timeout=60s
```

```
deployment.apps/kueue-controller-manager restarted
deployment "kueue-controller-manager" successfully rolled out
```

---

## Step-by-Step Walkthrough with Real Output

### Step 1 — Deploy base resources

```bash
kubectl apply -f 01-namespaces.yaml
kubectl apply -f 02-clusterqueue-team-a.yaml
kubectl apply -f 03-clusterqueue-team-b.yaml
kubectl apply -f 04-localqueues.yaml
```

```
namespace/fairshare-team-a created
namespace/fairshare-team-b created
clusterqueue.kueue.x-k8s.io/cq-team-a created
clusterqueue.kueue.x-k8s.io/cq-team-b created
localqueue.kueue.x-k8s.io/lq-team-a created
localqueue.kueue.x-k8s.io/lq-team-b created
```

**Verify ClusterQueue configuration:**

```bash
kubectl get clusterqueue cq-team-a cq-team-b \
  -o custom-columns="NAME:.metadata.name,COHORT:.spec.cohortName,WEIGHT:.spec.fairSharing.weight,CPU_QUOTA:.spec.resourceGroups[0].flavors[0].resources[0].nominalQuota,BORROW_LIMIT:.spec.resourceGroups[0].flavors[0].resources[0].borrowingLimit"
```

```
NAME        COHORT             WEIGHT   CPU_QUOTA   BORROW_LIMIT
cq-team-a   fairshare-cohort   2        4           0
cq-team-b   fairshare-cohort   3        6           0
```

> `WEIGHT 2:3` sets the proportional entitlement; `BORROW_LIMIT=0` enforces strict nominalQuota allocation in Phase 2.

---

### Phase 1 — Borrowing: team-b uses all available resources alone

> **Note:** Phase 1 uses CQs *without* `borrowingLimit` (comment out `borrowingLimit: "0"` and recreate the CQs). It demonstrates that when team-a is idle, team-b may borrow its full 4 CPUs. Phase 2 uses `borrowingLimit=0` to disable borrowing and enforce the 2:3 split.

```bash
kubectl apply -f 05-elastic-job-team-b.yaml
# Submitted at: 2026-05-21T16:42:37Z
```

```
job.batch/elastic-job-team-b created
```

**Check after ~10 seconds:**

```bash
kubectl get workloads -n fairshare-team-b
```

```
NAME                           QUEUE       RESERVED IN   ADMITTED   FINISHED   AGE
job-elastic-job-team-b-e7175   lq-team-b   cq-team-b     True                  17s
```

```bash
kubectl get pods -n fairshare-team-b
```

```
NAME                       READY   STATUS    RESTARTS   AGE
elastic-job-team-b-46dv9   1/1     Running   0          17s
elastic-job-team-b-8gm4n   1/1     Running   0          17s
elastic-job-team-b-dhzrt   1/1     Running   0          17s
elastic-job-team-b-g58pb   1/1     Running   0          17s
elastic-job-team-b-g6692   1/1     Running   0          17s
elastic-job-team-b-h542v   1/1     Running   0          17s
elastic-job-team-b-kcvk4   1/1     Running   0          17s
elastic-job-team-b-lrxb4   1/1     Running   0          17s
elastic-job-team-b-rgqph   1/1     Running   0          17s
elastic-job-team-b-rpkkx   1/1     Running   0          17s
```

> **All 10 pods Running** — this exceeds cq-team-b's nominalQuota of 6 CPUs. The extra 4 CPUs were borrowed from cq-team-a.

```bash
kubectl get clusterqueue cq-team-a cq-team-b \
  -o custom-columns="NAME:.metadata.name,NOMINAL:.spec.resourceGroups[0].flavors[0].resources[0].nominalQuota,USED:.status.flavorsUsage[0].resources[0].total,BORROWED:.status.flavorsUsage[0].resources[0].borrowed"
```

```
NAME        NOMINAL   USED   BORROWED
cq-team-a   4         0      0          ← idle; its 4 CPUs were lent to team-b
cq-team-b   6         10     4          ← using 10 CPUs, of which 4 are borrowed
```

> `cq-team-b BORROWED=4` confirms that team-b successfully borrowed team-a's idle 4 CPUs.

**Kueue controller log — Phase 1 admission (Job-B borrows all resources):**

```json
// [1] Scheduler picks up Job-B; cq-team-a is completely idle, borrowing is possible
{"ts":"2026-05-21T16:42:37Z","logger":"scheduler",
 "msg":"Attempting to schedule workload",
 "workload":{"name":"job-elastic-job-team-b-e7175","namespace":"fairshare-team-b"},
 "clusterQueue":{"name":"cq-team-b"},
 "parentCohort":{"name":"fairshare-cohort"}}

// [2] QuotaReserved event; "borrow=1" indicates cohort borrowing was used
// Flavors considered: main: default-flavor(Fit;borrow=1)
{"ts":"2026-05-21T16:42:37Z","logger":"events",
 "msg":"Quota reserved in ClusterQueue cq-team-b, wait time since queued was 0s;
        Flavors considered: main: default-flavor(Fit;borrow=1)",
 "reason":"QuotaReserved"}

// [3] PartialAdmission sets parallelism=10 (enough cohort capacity for all 10 pods)
{"ts":"2026-05-21T16:42:37Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors",
 "assignments":[{"name":"main",
   "resourceUsage":{"cpu":"10","memory":"2560Mi"},
   "count":10}]}
```

---

### Phase 2 — Fair Share: submit both elastic jobs simultaneously

```bash
kubectl apply -f 06-elastic-job-team-a.yaml
kubectl apply -f 05-elastic-job-team-b.yaml
# Submitted at: 2026-05-21T16:45:50Z
```

```
job.batch/elastic-job-team-a created
job.batch/elastic-job-team-b created
```

**Check after ~12 seconds:**

```bash
kubectl get workloads -n fairshare-team-a
kubectl get workloads -n fairshare-team-b
```

```
NAME                           QUEUE       RESERVED IN   ADMITTED   FINISHED   AGE
job-elastic-job-team-a-dbd47   lq-team-a   cq-team-a     True                  21s

NAME                           QUEUE       RESERVED IN   ADMITTED   FINISHED   AGE
job-elastic-job-team-b-cd21b   lq-team-b   cq-team-b     True                  21s
```

> Both workloads are `ADMITTED=True`, scheduled within the same second.

```bash
kubectl get pods -n fairshare-team-a
```

```
NAME                       READY   STATUS    RESTARTS   AGE
elastic-job-team-a-7gphg   1/1     Running   0          21s
elastic-job-team-a-8d52h   1/1     Running   0          21s
elastic-job-team-a-pflh6   1/1     Running   0          21s
elastic-job-team-a-w8khp   1/1     Running   0          21s
```

```bash
kubectl get pods -n fairshare-team-b
```

```
NAME                       READY   STATUS    RESTARTS   AGE
elastic-job-team-b-282vr   1/1     Running   0          21s
elastic-job-team-b-5ckgt   1/1     Running   0          21s
elastic-job-team-b-5dnnm   1/1     Running   0          21s
elastic-job-team-b-6k986   1/1     Running   0          21s
elastic-job-team-b-8j4s6   1/1     Running   0          21s
elastic-job-team-b-rxdbc   1/1     Running   0          21s
```

> **team-a: 4 pods (2 shares), team-b: 6 pods (3 shares) → 4:6 = 2:3 ✓**

```bash
kubectl get job elastic-job-team-a -n fairshare-team-a \
  -o custom-columns="TEAM:.metadata.name,PARALLELISM:.spec.parallelism,ACTIVE:.status.active,SUSPEND:.spec.suspend"
kubectl get job elastic-job-team-b -n fairshare-team-b \
  -o custom-columns="TEAM:.metadata.name,PARALLELISM:.spec.parallelism,ACTIVE:.status.active,SUSPEND:.spec.suspend"
```

```
TEAM                 PARALLELISM   ACTIVE   SUSPEND
elastic-job-team-a   4             4        false

TEAM                 PARALLELISM   ACTIVE   SUSPEND
elastic-job-team-b   6             6        false
```

> **Key observation:** `spec.parallelism` was elastically reduced by Kueue PartialAdmission from the requested **10** down to **4** and **6** respectively. `SUSPEND=false` confirms both jobs are actively running.

```bash
kubectl get clusterqueue cq-team-a cq-team-b \
  -o custom-columns="NAME:.metadata.name,NOMINAL:.spec.resourceGroups[0].flavors[0].resources[0].nominalQuota,USED:.status.flavorsUsage[0].resources[0].total,BORROWED:.status.flavorsUsage[0].resources[0].borrowed,ADMITTED:.status.admittedWorkloads"
```

```
NAME        NOMINAL   USED   BORROWED   ADMITTED
cq-team-a   4         4      0          1
cq-team-b   6         6      0          1
```

> `USED=4` and `USED=6`, `BORROWED=0` — each CQ uses exactly its nominalQuota with no borrowing.

**Kubernetes Events — Phase 2 fair share admission:**

```
# ─── team-a: Job-A admitted ───────────────────────────────────────────────────

Normal   QuotaReserved   workload/job-elastic-job-team-a-dbd47
  Quota reserved in ClusterQueue cq-team-a, wait time since queued was 0s

Normal   Admitted        workload/job-elastic-job-team-a-dbd47
  Admitted by ClusterQueue cq-team-a, wait time since reservation was 0s

Normal   Resumed         job/elastic-job-team-a
  Job resumed
  ↑ Kueue set spec.parallelism=4 and unsuspended the Job

# ─── team-b: Job-B admitted (same second as Job-A) ───────────────────────────

Normal   QuotaReserved   workload/job-elastic-job-team-b-cd21b
  Quota reserved in ClusterQueue cq-team-b, wait time since queued was 0s

Normal   Admitted        workload/job-elastic-job-team-b-cd21b
  Admitted by ClusterQueue cq-team-b, wait time since reservation was 0s

Normal   Resumed         job/elastic-job-team-b
  Job resumed
  ↑ Kueue set spec.parallelism=6 and unsuspended the Job
```

**Kueue controller log — Phase 2: two consecutive scheduling cycles:**

```json
// ─── Scheduling Cycle #6742: Job-A ───────────────────────────────────────────

// [1] Scheduler picks up Job-A; both CQs are in cohort fairshare-cohort
{"ts":"2026-05-21T16:45:50.299671Z","logger":"scheduler",
 "msg":"Attempting to schedule workload","schedulingCycle":6742,
 "workload":{"name":"job-elastic-job-team-a-dbd47","namespace":"fairshare-team-a"},
 "clusterQueue":{"name":"cq-team-a"},
 "parentCohort":{"name":"fairshare-cohort"},
 "rootCohort":{"name":"fairshare-cohort"}}

// [2] PartialAdmission: cq-team-a has 4 CPUs → max 4 pods admitted (count=4)
{"ts":"2026-05-21T16:45:50.304092Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":6742,
 "workload":{"name":"job-elastic-job-team-a-dbd47","namespace":"fairshare-team-a"},
 "clusterQueue":{"name":"cq-team-a"},
 "assignments":[{"name":"main",
   "flavors":{"cpu":"default-flavor","memory":"default-flavor"},
   "resourceUsage":{"cpu":"4","memory":"1Gi"},
   "count":4}]}
 // ↑ count=4: parallelism elastically reduced from 10 to 4

// [3] Job controller receives unsuspend signal with spec.parallelism=4
{"ts":"2026-05-21T16:45:50.303717Z","logger":"job",
 "msg":"Job admitted, unsuspending",
 "job":"fairshare-team-a/elastic-job-team-a"}

// ─── Scheduling Cycle #6743: Job-B (only 41ms later) ─────────────────────────

// [4] Scheduler picks up Job-B in the very next cycle
{"ts":"2026-05-21T16:45:50.341108Z","logger":"scheduler",
 "msg":"Attempting to schedule workload","schedulingCycle":6743,
 "workload":{"name":"job-elastic-job-team-b-cd21b","namespace":"fairshare-team-b"},
 "clusterQueue":{"name":"cq-team-b"},
 "parentCohort":{"name":"fairshare-cohort"},
 "rootCohort":{"name":"fairshare-cohort"}}

// [5] PartialAdmission: cq-team-b has 6 CPUs → 6 pods admitted (count=6)
{"ts":"2026-05-21T16:45:50.344746Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":6743,
 "workload":{"name":"job-elastic-job-team-b-cd21b","namespace":"fairshare-team-b"},
 "clusterQueue":{"name":"cq-team-b"},
 "assignments":[{"name":"main",
   "flavors":{"cpu":"default-flavor","memory":"default-flavor"},
   "resourceUsage":{"cpu":"6","memory":"1536Mi"},
   "count":6}]}
 // ↑ count=6: parallelism elastically reduced from 10 to 6

// [6] Job controller receives unsuspend signal with spec.parallelism=6
{"ts":"2026-05-21T16:45:50.345021Z","logger":"job",
 "msg":"Job admitted, unsuspending",
 "job":"fairshare-team-b/elastic-job-team-b"}
```

> **Key observation:** Cycles 6742 and 6743 are separated by just **41ms** (`waitDuration: 0.041s`). Both jobs were admitted within the same second. Kueue's PartialAdmission independently computed the maximum affordable pod count for each workload: 4 and 6, delivering a perfect 2:3 split.

---

## Actual Timeline (this run)

| Time (UTC) | Relative | Event |
|---|---|---|
| 16:42:37 | Phase 1 T+0s | Job-B submitted (max=10, min=2) |
| 16:42:37 | Phase 1 T+0s | Kueue admits Job-B with 10 pods (borrows 4 CPUs from cq-team-a) |
| 16:42:38 | Phase 1 T+1s | 10 pods Running; cq-team-b USED=10 BORROWED=4 |
| — | Reset | Delete Job-B; recreate CQs with borrowingLimit=0 |
| 16:45:50 | Phase 2 T+0s | Job-A and Job-B submitted simultaneously (both max=10, min=2) |
| 16:45:50 | Phase 2 T+0s | Scheduling cycle #6742: Job-A admitted, count=4, cq-team-a USED=4 |
| 16:45:50 | Phase 2 T+0s | Scheduling cycle #6743 (+41ms): Job-B admitted, count=6, cq-team-b USED=6 |
| 16:45:51 | Phase 2 T+1s | team-a: 4 pods Running, team-b: 6 pods Running → **2:3 ✓** |

---

## How It Works Internally

### PartialAdmission — the key to elastic jobs

```
By default, a batch/v1 Job is all-or-nothing: if parallelism=10, all 10 CPUs
must be available or the job waits indefinitely.

PartialAdmission breaks this constraint:
  annotation: kueue.x-k8s.io/job-min-parallelism: "2"
  meaning: the job needs at least 2 pods to make progress; Kueue may choose
           any count in the range [2, parallelism].

Kueue's decision (simplified):
  admitted_count = min(requested_parallelism, available_quota_in_cpu)
  if admitted_count >= min_parallelism:
      admit the job with spec.parallelism = admitted_count
  else:
      job stays in queue (pending)

This run's result:
  Job-A: min(10, 4) = 4  → spec.parallelism set to 4
  Job-B: min(10, 6) = 6  → spec.parallelism set to 6
```

### FairSharing Weight vs NominalQuota

```
NominalQuota (4 and 6) is the resource guarantee for each CQ:
  - Always available regardless of what other CQs are doing
  - The ratio 4:6 = 2:3 directly matches weight 2:3 (they reinforce each other)

FairSharing Weight (2 and 3) influences scheduling priority under competition:
  - Kueue uses Dominant Resource Fairness (DRF) principles
  - Share = resource_used / weight
  - Kueue prefers scheduling workloads from the CQ with the lowest share
  - This ensures the 2:3 ratio is maintained over time

With borrowingLimit=0 (Phase 2):
  - Each CQ is hard-capped at its nominalQuota
  - Fair share is enforced directly by the quota limit
  - Weight primarily serves as a semantic confirmation of intent

With borrowingLimit=null (Phase 1, default):
  - CQs may borrow idle quota from the cohort
  - Weight influences the priority of competing borrowers
```

### The suspend/unsuspend + PartialAdmission contract

```
Kueue adjusts Job.spec.parallelism to implement elastic scaling:

  When job is submitted:
    spec.parallelism = 10  (user's requested maximum)
    spec.suspend    = true  (required by Kueue)
    annotation: job-min-parallelism = "2"  (user's minimum)

  When Kueue admits the job (e.g., Job-A):
    computes admitted_count = min(10, 4) = 4
    writes: spec.parallelism = 4  ← elastic scale-down
    writes: spec.suspend    = false  ← start the job
    Job controller creates exactly 4 pods

  If quota later increases (e.g., team-b releases resources):
    re-admission computes admitted_count = min(10, available)
    spec.parallelism may be increased (elastic scale-up)
```

---

## Cleanup

```bash
kubectl delete namespace fairshare-team-a fairshare-team-b
kubectl delete clusterqueue cq-team-a cq-team-b
```

Verify:
```bash
kubectl get ns fairshare-team-a 2>&1      # Error from server (NotFound)
kubectl get clusterqueue cq-team-a 2>&1   # Error from server (NotFound)
```

---

## Appendix: Complete YAML Files

### 01-namespaces.yaml

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: fairshare-team-a
---
apiVersion: v1
kind: Namespace
metadata:
  name: fairshare-team-b
```

### 02-clusterqueue-team-a.yaml

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
kind: ClusterQueue
metadata:
  name: cq-team-a
spec:
  cohortName: fairshare-cohort
  namespaceSelector: {}
  queueingStrategy: BestEffortFIFO
  fairSharing:
    weight: "2"               # team-a holds 2/(2+3) = 40% of the fair share
  preemption:
    reclaimWithinCohort: Any
    withinClusterQueue: Never
  resourceGroups:
    - coveredResources: ["cpu", "memory"]
      flavors:
        - name: default-flavor
          resources:
            - name: cpu
              nominalQuota: "4"
              borrowingLimit: "0"   # no borrowing; strict fair share enforcement
            - name: memory
              nominalQuota: "4Gi"
              borrowingLimit: "0"
```

### 03-clusterqueue-team-b.yaml

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
kind: ClusterQueue
metadata:
  name: cq-team-b
spec:
  cohortName: fairshare-cohort
  namespaceSelector: {}
  queueingStrategy: BestEffortFIFO
  fairSharing:
    weight: "3"               # team-b holds 3/(2+3) = 60% of the fair share
  preemption:
    reclaimWithinCohort: Any
    withinClusterQueue: Never
  resourceGroups:
    - coveredResources: ["cpu", "memory"]
      flavors:
        - name: default-flavor
          resources:
            - name: cpu
              nominalQuota: "6"
              borrowingLimit: "0"
            - name: memory
              nominalQuota: "4Gi"
              borrowingLimit: "0"
```

### 04-localqueues.yaml

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
kind: LocalQueue
metadata:
  name: lq-team-a
  namespace: fairshare-team-a
spec:
  clusterQueue: cq-team-a
---
apiVersion: kueue.x-k8s.io/v1beta2
kind: LocalQueue
metadata:
  name: lq-team-b
  namespace: fairshare-team-b
spec:
  clusterQueue: cq-team-b
```

### 05-elastic-job-team-b.yaml

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: elastic-job-team-b
  namespace: fairshare-team-b
  labels:
    kueue.x-k8s.io/queue-name: lq-team-b
  annotations:
    kueue.x-k8s.io/job-min-parallelism: "2"  # PartialAdmission: minimum pod count
spec:
  parallelism: 10         # elastic upper bound: up to 10 pods requested
  completions: 10
  suspend: true
  template:
    metadata:
      labels:
        app: elastic-job-team-b
    spec:
      restartPolicy: Never
      containers:
        - name: worker
          image: busybox:1.36
          command:
            - sh
            - -c
            - |
              echo "TEAM-B worker started, pod=$(hostname)"
              sleep 300
              echo "TEAM-B worker done"
          resources:
            requests:
              cpu: "1"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "256Mi"
```

### 06-elastic-job-team-a.yaml

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: elastic-job-team-a
  namespace: fairshare-team-a
  labels:
    kueue.x-k8s.io/queue-name: lq-team-a
  annotations:
    kueue.x-k8s.io/job-min-parallelism: "2"  # PartialAdmission: minimum pod count
spec:
  parallelism: 10         # elastic upper bound: up to 10 pods requested
  completions: 10
  suspend: true
  template:
    metadata:
      labels:
        app: elastic-job-team-a
    spec:
      restartPolicy: Never
      containers:
        - name: worker
          image: busybox:1.36
          command:
            - sh
            - -c
            - |
              echo "TEAM-A worker started, pod=$(hostname)"
              sleep 300
              echo "TEAM-A worker done"
          resources:
            requests:
              cpu: "1"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "256Mi"
```
