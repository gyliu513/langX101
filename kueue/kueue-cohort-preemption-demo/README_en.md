# Kueue Cohort Cross-Queue Preemption Demo

This document demonstrates **cross-ClusterQueue preemption** in Kueue (`reclaimWithinCohort`). Unlike basic preemption (`withinClusterQueue`), the preemption here spans two different ClusterQueues: a high-priority queue reclaims quota that a low-priority queue had borrowed. All commands include their **actual output** from a live kind cluster plus annotated **Kueue controller logs**.

---

## Comparison with the Basic Preemption Demo

| Dimension | Basic Preemption | Cohort Cross-Queue Preemption |
|---|---|---|
| Config field | `withinClusterQueue: LowerPriority` | `reclaimWithinCohort: LowerPriority` |
| Preemption scope | **Within a single ClusterQueue** | **Across ClusterQueues in a cohort** |
| Trigger | High-priority job needs resources already held by a lower-priority job *in the same CQ* | High-priority CQ's quota was **borrowed by another CQ**; submitting a job triggers reclamation |
| Core concept | In-queue priority ordering | Cross-queue quota borrowing and reclamation |

---

## Scenario Design

```
Cohort: preemption-cohort  (total 6 CPUs = cq-high 3 + cq-low 3)
│
├── ClusterQueue: cq-high  ── nominalQuota=3 CPU
│   └── LocalQueue: lq-high  (namespace: cohort-preemption-demo)
│       └── high-priority-gang: 3 pods × 1CPU, PriorityClass=1000, sleep 60s
│
└── ClusterQueue: cq-low   ── nominalQuota=3 CPU
    └── LocalQueue: lq-low   (namespace: cohort-preemption-demo)
        └── low-priority-gang:  6 pods × 1CPU, PriorityClass=100,  sleep 300s
```

**Timeline:**
```
T+0s   │ low-priority-gang submitted (needs 6 CPUs)
T+0s   │ cq-high is idle → cq-low borrows 3 CPUs → low-priority runs with 6 pods
T+20s  │ high-priority-gang submitted (needs 3 CPUs)
T+20s  │ reclaimWithinCohort fires: cq-high reclaims the 3 CPUs borrowed by cq-low
T+20s  │ low-priority-gang evicted (entire gang suspended)
T+20s  │ high-priority-gang admitted with 3 pods (using cq-high's 3 CPUs)
T+20s  │ low-priority-gang waits in queue (cq-low only has 3 CPUs, gang needs 6)
T+80s  │ high-priority-gang completes (sleep 60s)
T+81s  │ cq-high's 3 CPUs freed; low-priority-gang resumes with 6 pods
```

---

## Prerequisites

```bash
kubectl get nodes
kubectl get pods -n kueue-system
kubectl get resourceflavor
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
01-namespace.yaml           Namespace: cohort-preemption-demo
02-priority-classes.yaml    PriorityClass: low-priority(100) / high-priority(1000)
03-clusterqueue-high.yaml   CQ: cq-high, nominalQuota=3 CPU, reclaimWithinCohort: LowerPriority
04-clusterqueue-low.yaml    CQ: cq-low,  nominalQuota=3 CPU, reclaimWithinCohort: LowerPriority
05-localqueues.yaml         LocalQueue: lq-high / lq-low
06-low-priority-gang-job.yaml   Gang Job: 6 pods, low-priority, sleep 300s
07-high-priority-gang-job.yaml  Gang Job: 3 pods, high-priority, sleep 60s
```

---

## Step-by-Step Walkthrough with Real Output

### Step 1 — Deploy base resources

```bash
kubectl apply -f 01-namespace.yaml
kubectl apply -f 02-priority-classes.yaml
kubectl apply -f 03-clusterqueue-high.yaml
kubectl apply -f 04-clusterqueue-low.yaml
kubectl apply -f 05-localqueues.yaml
```

```
namespace/cohort-preemption-demo created
priorityclass.scheduling.k8s.io/low-priority created
priorityclass.scheduling.k8s.io/high-priority created
clusterqueue.kueue.x-k8s.io/cq-high created
clusterqueue.kueue.x-k8s.io/cq-low created
localqueue.kueue.x-k8s.io/lq-high created
localqueue.kueue.x-k8s.io/lq-low created
```

**Verify:**

```bash
kubectl get priorityclass low-priority high-priority
```
```
NAME            VALUE   GLOBAL-DEFAULT   AGE   PREEMPTIONPOLICY
low-priority    100     false            5s    PreemptLowerPriority
high-priority   1000    false            5s    PreemptLowerPriority
```

```bash
kubectl get clusterqueue cq-high cq-low \
  -o custom-columns="NAME:.metadata.name,COHORT:.spec.cohortName,CPU:.spec.resourceGroups[0].flavors[0].resources[0].nominalQuota,RECLAIM:.spec.preemption.reclaimWithinCohort"
```
```
NAME      COHORT              CPU   RECLAIM
cq-high   preemption-cohort   3     LowerPriority
cq-low    preemption-cohort   3     LowerPriority
```

> Both CQs share the cohort `preemption-cohort`, each with a nominalQuota of 3 CPUs. `reclaimWithinCohort: LowerPriority` allows cross-CQ reclamation of borrowed quota from lower-priority workloads.

```bash
kubectl get localqueue -n cohort-preemption-demo
```
```
NAME      CLUSTERQUEUE   PENDING WORKLOADS   ADMITTED WORKLOADS
lq-high   cq-high        0                   0
lq-low    cq-low         0                   0
```

---

### Step 2 — Submit the low-priority gang job (T=0s)

```bash
kubectl apply -f 06-low-priority-gang-job.yaml
# Submitted at: 2026-05-21T17:02:38Z
```
```
job.batch/low-priority-gang created
```

**Check after ~8 seconds:**

```bash
kubectl get workloads -n cohort-preemption-demo
```
```
NAME                          QUEUE    RESERVED IN   ADMITTED   FINISHED   AGE
job-low-priority-gang-44684   lq-low   cq-low        True                  15s
```

```bash
kubectl get pods -n cohort-preemption-demo
```
```
NAME                      READY   STATUS    RESTARTS   AGE
low-priority-gang-jjq5n   1/1     Running   0          15s
low-priority-gang-mp26p   1/1     Running   0          15s
low-priority-gang-nnsft   1/1     Running   0          15s
low-priority-gang-psvk8   1/1     Running   0          15s
low-priority-gang-q6k8k   1/1     Running   0          15s
low-priority-gang-vvx9m   1/1     Running   0          15s
```

> **All 6 pods Running** — this exceeds cq-low's nominalQuota (3 CPUs). The extra 3 CPUs were borrowed from cq-high's idle quota.

```bash
kubectl get clusterqueue cq-high cq-low \
  -o custom-columns="NAME:.metadata.name,NOMINAL:.spec.resourceGroups[0].flavors[0].resources[0].nominalQuota,USED:.status.flavorsUsage[0].resources[0].total,BORROWED:.status.flavorsUsage[0].resources[0].borrowed"
```
```
NAME      NOMINAL   USED   BORROWED
cq-high   3         0      0          ← idle; its 3 CPUs were lent to cq-low
cq-low    3         6      3          ← using 6 CPUs, of which 3 are borrowed
```

> `cq-low BORROWED=3` confirms that the low-priority job has borrowed cq-high's full 3-CPU quota.

**Kubernetes Event (Step 2):**

```
Normal   QuotaReserved   workload/job-low-priority-gang-44684
  Quota reserved in ClusterQueue cq-low, wait time since queued was 0s;
  Flavors considered: main: default-flavor(Fit;borrow=1)
  ↑ "borrow=1" indicates this admission used borrowed quota from the cohort
```

**Kueue controller log (Step 2 — low-priority borrows all cohort resources):**

```json
// Scheduler admits the workload with count=6 (3 nominal + 3 borrowed)
{"ts":"2026-05-21T17:02:38Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors",
 "workload":{"name":"job-low-priority-gang-44684","namespace":"cohort-preemption-demo"},
 "clusterQueue":{"name":"cq-low"},
 "parentCohort":{"name":"preemption-cohort"},
 "assignments":[{"name":"main",
   "resourceUsage":{"cpu":"6","memory":"1536Mi"},
   "count":6}]}
```

---

### Step 3 — Submit the high-priority gang job; trigger cross-CQ preemption (T=+20s)

```bash
kubectl apply -f 07-high-priority-gang-job.yaml
# Submitted at: 2026-05-21T17:02:58Z
```
```
job.batch/high-priority-gang created
```

**Check after ~8 seconds (preemption already occurred):**

```bash
kubectl get workloads -n cohort-preemption-demo
```
```
NAME                           QUEUE     RESERVED IN   ADMITTED   FINISHED   AGE
job-high-priority-gang-e2828   lq-high   cq-high       True                  13s
job-low-priority-gang-44684    lq-low                  False                 33s
```

> - `high-priority`: `ADMITTED=True`, `RESERVED IN=cq-high` ← **cross-CQ reclamation succeeded, now running**
> - `low-priority`: `ADMITTED=False`, `RESERVED IN=(empty)` ← **preempted across CQs, waiting in queue**

```bash
kubectl get pods -n cohort-preemption-demo
```
```
NAME                       READY   STATUS        RESTARTS   AGE
high-priority-gang-cwzzd   1/1     Running       0          13s
high-priority-gang-mqk5j   1/1     Running       0          13s
high-priority-gang-pnvz7   1/1     Running       0          13s
low-priority-gang-jjq5n    1/1     Terminating   0          33s
low-priority-gang-mp26p    1/1     Terminating   0          33s
low-priority-gang-nnsft    1/1     Terminating   0          33s
low-priority-gang-psvk8    1/1     Terminating   0          33s
low-priority-gang-q6k8k    1/1     Terminating   0          33s
low-priority-gang-vvx9m    1/1     Terminating   0          33s
```

```bash
kubectl get jobs -n cohort-preemption-demo \
  -o custom-columns="NAME:.metadata.name,SUSPEND:.spec.suspend,ACTIVE:.status.active,SUCCEEDED:.status.succeeded"
```
```
NAME                 SUSPEND   ACTIVE   SUCCEEDED
high-priority-gang   false     3        <none>
low-priority-gang    true      <none>   <none>
```

```bash
kubectl get clusterqueue cq-high cq-low \
  -o custom-columns="NAME:.metadata.name,NOMINAL:.spec.resourceGroups[0].flavors[0].resources[0].nominalQuota,USED:.status.flavorsUsage[0].resources[0].total,BORROWED:.status.flavorsUsage[0].resources[0].borrowed,ADMITTED:.status.admittedWorkloads"
```
```
NAME      NOMINAL   USED   BORROWED   ADMITTED
cq-high   3         3      0          1
cq-low    3         0      0          0
```

> cq-high `USED=3, BORROWED=0`: high-priority is running on its own nominalQuota. cq-low `USED=0`: all of low-priority's borrowed usage has been reclaimed.

**Kubernetes Events — complete cross-CQ preemption audit chain:**

```
# ─── Preemption triggered ──────────────────────────────────────────────────────

Warning  Pending   workload/job-high-priority-gang-e2828
  couldn't assign flavors to pod set main: insufficient unused quota for cpu
  in flavor default-flavor, 3 more needed. Pending the preemption of 1 workload(s)
  ↑ Kueue found 1 preemption candidate needed to satisfy cq-high's quota request

# ─── low-priority evicted from a different CQ ─────────────────────────────────

Normal   EvictedDueToPreempted  workload/job-low-priority-gang-44684
  Preempted to accommodate a workload (UID: 2daed6fd-..., JobUID: 5e63deb5-...)
  due to reclamation within the cohort;
  preemptor path: /preemption-cohort/cq-high;   ← preemptor: cq-high queue
  preemptee path: /preemption-cohort/cq-low     ← preemptee: cq-low queue
  ↑ CRITICAL: preemptor and preemptee are in DIFFERENT CQs — this is the
    signature of cross-CQ cohort preemption

Normal   Preempted   workload/job-low-priority-gang-44684  (same message)
Normal   Stopped     job/low-priority-gang                 (same message)

Normal   Suspended   job/low-priority-gang
  Job suspended  ↑ Kueue sets spec.suspend=true; Job controller deletes all 6 pods

# ─── high-priority gains quota and starts ─────────────────────────────────────

Normal   QuotaReserved  workload/job-high-priority-gang-e2828
  Quota reserved in ClusterQueue cq-high, wait time since queued was 1s

Normal   Admitted    workload/job-high-priority-gang-e2828
  Admitted by ClusterQueue cq-high, wait time since reservation was 0s

Normal   Resumed     job/high-priority-gang
  Job resumed  ↑ spec.suspend=false; 3 new pods created

# ─── low-priority waits (needs 6 CPUs, only 3 available in cq-low) ───────────

Warning  Pending     workload/job-low-priority-gang-44684
  couldn't assign flavors to pod set main: insufficient unused quota for cpu
  in flavor default-flavor, 3 more needed
  ↑ The gang job needs 6 CPUs; cq-low has only 3, and cq-high is occupied
```

**Kueue controller log — cross-CQ preemption core entries:**

```json
// [1] Scheduling cycle #6752: high-priority submitted; both workloads processed
// high-priority assumed in cache; low-priority gets FailedAfterNomination
{"ts":"2026-05-21T17:02:58.757Z","logger":"scheduler",
 "msg":"Workload assumed in the cache","schedulingCycle":6752,
 "workload":{"name":"job-high-priority-gang-e2828","namespace":"cohort-preemption-demo"},
 "clusterQueue":{"name":"cq-high"},
 "parentCohort":{"name":"preemption-cohort"},
 "rootCohort":{"name":"preemption-cohort"}}
 // ↑ parentCohort/rootCohort show this is a cohort-scoped scheduling decision

// [2] low-priority re-queued with reason FailedAfterNomination
{"ts":"2026-05-21T17:02:58.757Z","logger":"scheduler",
 "msg":"Workload re-queued","schedulingCycle":6752,
 "workload":{"name":"job-low-priority-gang-44684","namespace":"cohort-preemption-demo"},
 "clusterQueue":{"name":"cq-low"},
 "requeueReason":"FailedAfterNomination"}
 // ↑ FailedAfterNomination: cq-high reclaimed its quota; low-priority's borrow
 //   entitlement is revoked atomically in the same scheduling cycle

// [3] high-priority admitted with count=3 (exactly cq-high's nominalQuota)
{"ts":"2026-05-21T17:02:58.761Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":6752,
 "workload":{"name":"job-high-priority-gang-e2828","namespace":"cohort-preemption-demo"},
 "clusterQueue":{"name":"cq-high"},
 "parentCohort":{"name":"preemption-cohort"},
 "assignments":[{"name":"main",
   "resourceUsage":{"cpu":"3","memory":"768Mi"},
   "count":3}]}

// [4] Scheduling cycle #6753: low-priority tries to reschedule — no candidates
// (low-priority cannot preempt high-priority because 100 < 1000)
{"ts":"2026-05-21T17:02:58.767Z","logger":"scheduler",
 "msg":"Workload requires preemption, but there are no candidate workloads allowed for preemption",
 "schedulingCycle":6753,
 "workload":{"name":"job-low-priority-gang-44684","namespace":"cohort-preemption-demo"},
 "clusterQueue":{"name":"cq-low"},
 "preemption":{"reclaimWithinCohort":"LowerPriority",
               "borrowWithinCohort":{"policy":"Never"},
               "withinClusterQueue":"Never"}}
 // ↑ low-priority has no preemption candidates — it enters the inadmissible queue
```

---

### Step 4 — Wait for high-priority to complete; observe low-priority resume (T=+80s)

```bash
for i in $(seq 1 18); do
  sleep 5
  HIGH=$(kubectl get job high-priority-gang -n cohort-preemption-demo \
    -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null)
  LOW_SUSPEND=$(kubectl get job low-priority-gang -n cohort-preemption-demo \
    -o jsonpath='{.spec.suspend}' 2>/dev/null)
  LOW_ACTIVE=$(kubectl get job low-priority-gang -n cohort-preemption-demo \
    -o jsonpath='{.status.active}' 2>/dev/null)
  BORROWED=$(kubectl get clusterqueue cq-low \
    -o jsonpath='{.status.flavorsUsage[0].resources[0].borrowed}' 2>/dev/null)
  echo "[$(date +%H:%M:%S)] high=complete:$HIGH | low=suspend:$LOW_SUSPEND,active:$LOW_ACTIVE | cq-low borrowed:$BORROWED"
  [ "$HIGH" = "True" ] && [ "$LOW_ACTIVE" = "6" ] && \
    echo ">>> DONE: high completed, low resumed with 6 pods!" && break
done
```

**Actual polling output:**

```
[13:03:27] high=complete:   | low=suspend:true,active:  | cq-low borrowed:0
[13:03:32] high=complete:   | low=suspend:true,active:  | cq-low borrowed:0
[13:03:38] high=complete:   | low=suspend:true,active:  | cq-low borrowed:0
[13:03:43] high=complete:   | low=suspend:true,active:  | cq-low borrowed:0
[13:03:48] high=complete:   | low=suspend:true,active:  | cq-low borrowed:0
[13:03:53] high=complete:   | low=suspend:true,active:  | cq-low borrowed:0
[13:03:58] high=complete:   | low=suspend:true,active:  | cq-low borrowed:0
[13:04:03] high=complete:True | low=suspend:false,active:6 | cq-low borrowed:3
>>> DONE: high completed, low resumed with 6 pods!
```

> high-priority completes at T+65s. Kueue immediately re-admits low-priority with **6 pods** — it borrows cq-high's 3 CPUs again.

**Kubernetes Events — high-priority completion + low-priority resume:**

```
Normal   Completed         job/high-priority-gang
  Job completed

Normal   FinishedWorkload  job/high-priority-gang
  Workload 'cohort-preemption-demo/job-high-priority-gang-e2828' is declared finished

Normal   QuotaReserved     workload/job-low-priority-gang-44684
  Quota reserved in ClusterQueue cq-low, wait time since queued was 65s;
  Flavors considered: main: default-flavor(Fit;borrow=1)
  ↑ wait time=65s: low-priority spent 65 seconds in the inadmissible queue
  ↑ borrow=1: borrows cq-high's 3 CPUs again

Normal   Admitted          workload/job-low-priority-gang-44684
  Admitted by ClusterQueue cq-low, wait time since reservation was 0s

Normal   Resumed           job/low-priority-gang
  Job resumed
```

**Kueue controller log — high-priority completes → low-priority resumes:**

```json
// [1] high-priority completes; FinishedWorkload event fired
{"ts":"2026-05-21T17:04:01.790Z","logger":"events",
 "msg":"Workload 'cohort-preemption-demo/job-high-priority-gang-e2828' is declared finished",
 "reason":"FinishedWorkload"}

// [2] workload-reconciler detects finished; cq-high's 3 CPUs are released
{"ts":"2026-05-21T17:04:01.790Z","logger":"workload-reconciler",
 "msg":"Workload update event",
 "workload":{"name":"job-high-priority-gang-e2828"},
 "status":"finished","prevStatus":"admitted","clusterQueue":"cq-high"}

// [3] inadmissible_workload_requeue_worker scans the entire cohort tree
{"ts":"2026-05-21T17:04:02.792Z","logger":"inadmissible_workload_requeue_worker",
 "msg":"Attempting to move workloads","rootCohort":"preemption-cohort"}
{"ts":"2026-05-21T17:04:02.792Z","logger":"inadmissible_workload_requeue_worker",
 "msg":"Moved inadmissible workloads in tree",
 "rootCohort":"preemption-cohort","count":1}
 // ↑ rootCohort="preemption-cohort": scans the whole cohort, not just one CQ

// [4] Scheduling cycle #6755: low-priority re-admitted with 6 pods (borrows 3 again)
{"ts":"2026-05-21T17:04:02.810Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":6755,
 "workload":{"name":"job-low-priority-gang-44684"},
 "clusterQueue":{"name":"cq-low"},
 "parentCohort":{"name":"preemption-cohort"},
 "assignments":[{"name":"main",
   "resourceUsage":{"cpu":"6","memory":"1536Mi"},
   "count":6}]}
 // ↑ count=6: back to full 6 pods, borrowing cq-high's 3 CPUs again
```

---

### Step 5 — Final state

```bash
kubectl get workloads -n cohort-preemption-demo
```
```
NAME                           QUEUE     RESERVED IN   ADMITTED   FINISHED   AGE
job-high-priority-gang-e2828   lq-high   cq-high       True       True       71s
job-low-priority-gang-44684    lq-low    cq-low        True                  91s
```

```bash
kubectl get pods -n cohort-preemption-demo
```
```
NAME                       READY   STATUS      RESTARTS   AGE
high-priority-gang-cwzzd   0/1     Completed   0          72s
high-priority-gang-mqk5j   0/1     Completed   0          72s
high-priority-gang-pnvz7   0/1     Completed   0          72s
low-priority-gang-5ckcs    1/1     Running     0          8s
low-priority-gang-6xgjb    1/1     Running     0          8s
low-priority-gang-bn2qr    1/1     Running     0          8s
low-priority-gang-gqvsb    1/1     Running     0          8s
low-priority-gang-hsdpw    1/1     Running     0          8s
low-priority-gang-zh9w8    1/1     Running     0          8s
```

> The resumed low-priority job has **brand-new pods** (different name suffixes), and cq-low is borrowing 3 CPUs from cq-high again.

```bash
kubectl get jobs -n cohort-preemption-demo \
  -o custom-columns="NAME:.metadata.name,SUSPEND:.spec.suspend,ACTIVE:.status.active,SUCCEEDED:.status.succeeded"
```
```
NAME                 SUSPEND   ACTIVE   SUCCEEDED
high-priority-gang   false     <none>   3
low-priority-gang    false     6        <none>
```

---

## Actual Timeline (this run)

| Time (UTC) | Relative | Event |
|---|---|---|
| 17:02:38 | T+0s | `low-priority-gang` submitted; Workload created |
| 17:02:38 | T+0s | Scheduler: admitted (count=6, cq-low USED=6, BORROWED=3) |
| 17:02:38 | T+0s | 6 pods Running (includes 3 CPUs borrowed from cq-high) |
| 17:02:58 | T+20s | `high-priority-gang` submitted |
| 17:02:58 | T+20s | Cycle #6752: high-priority assumed; low-priority FailedAfterNomination |
| 17:02:58 | T+20s | `low-priority-gang` suspended; 6 pods Terminating |
| 17:02:58 | T+20s | `high-priority-gang` admitted (count=3, cq-high USED=3, BORROWED=0) |
| 17:02:58 | T+20s | low-priority enters inadmissible queue (needs 6 CPUs, only 3 available) |
| 17:04:01 | T+83s | `high-priority-gang` completes (sleep 60s) |
| 17:04:02 | T+84s | inadmissible_requeue_worker scans cohort; low-priority moved to scheduling queue |
| 17:04:02 | T+84s | Cycle #6755: low-priority re-admitted (count=6, borrows 3 CPUs again, wait=65s) |
| 17:04:02 | T+84s | 6 new pods Running |

---

## How It Works Internally

### `reclaimWithinCohort` trigger conditions

```
Kueue fires cross-CQ preemption (reclaimWithinCohort: LowerPriority) when ALL of:

  ① There is a pending workload W (high-priority-gang) in cq-high
  ② W fits within cq-high's nominalQuota (3 pods ≤ 3 CPUs)
  ③ cq-high's nominalQuota is currently borrowed by a workload in another CQ
     → cq-low's low-priority-gang is borrowing cq-high's 3 CPUs
  ④ The borrower (low-priority-gang) has LOWER priority than W (100 < 1000)

All four conditions met → Kueue evicts low-priority-gang and reclaims cq-high's quota
```

### Key differences from basic preemption

```
Basic preemption (withinClusterQueue):
  Same CQ: high-priority job directly evicts low-priority job
  cq-A { high-job evicts low-job }

Cross-CQ preemption (reclaimWithinCohort):
  cq-high { high-job pending } + cq-low { low-job borrowing cq-high's quota }
  → cq-high reclaims what cq-low borrowed

  Critical distinctions:
  ① The evicted job is in a DIFFERENT CQ (cq-low)
  ② Eviction reason is "occupying borrowed resources", not "competing in the same queue"
  ③ Preemption paths are explicitly recorded in events:
     preemptor path: /preemption-cohort/cq-high
     preemptee path: /preemption-cohort/cq-low
```

### Why low-priority cannot be admitted during the wait period

```
After being evicted, low-priority-gang needs 6 CPUs (gang job: all-or-nothing):
  - cq-low has 3 CPUs (its nominalQuota)
  - cq-high's 3 CPUs are occupied by high-priority-gang (cannot be borrowed)
  - 3 + 0 = 3 CPUs available < 6 CPUs needed

→ Gang scheduling atomicity: the job waits entirely rather than running with 3 pods
→ Kueue's scheduler marks it inadmissible:
  "Workload requires preemption, but there are no candidate workloads allowed"
  (low-priority cannot preempt high-priority since 100 < 1000)
```

---

## Cleanup

```bash
kubectl delete namespace cohort-preemption-demo
kubectl delete clusterqueue cq-high cq-low
kubectl delete priorityclass low-priority high-priority
```

---

## Appendix: Complete YAML Files

### 03-clusterqueue-high.yaml

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
kind: ClusterQueue
metadata:
  name: cq-high
spec:
  cohortName: preemption-cohort
  namespaceSelector: {}
  queueingStrategy: BestEffortFIFO
  preemption:
    reclaimWithinCohort: LowerPriority   # reclaim quota borrowed by lower-priority workloads
    withinClusterQueue: Never
  resourceGroups:
    - coveredResources: ["cpu", "memory"]
      flavors:
        - name: default-flavor
          resources:
            - name: cpu
              nominalQuota: "3"
            - name: memory
              nominalQuota: "3Gi"
```

### 04-clusterqueue-low.yaml

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
kind: ClusterQueue
metadata:
  name: cq-low
spec:
  cohortName: preemption-cohort
  namespaceSelector: {}
  queueingStrategy: BestEffortFIFO
  preemption:
    reclaimWithinCohort: LowerPriority
    withinClusterQueue: Never
  resourceGroups:
    - coveredResources: ["cpu", "memory"]
      flavors:
        - name: default-flavor
          resources:
            - name: cpu
              nominalQuota: "3"
            - name: memory
              nominalQuota: "3Gi"
```

### 06-low-priority-gang-job.yaml

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: low-priority-gang
  namespace: cohort-preemption-demo
  labels:
    kueue.x-k8s.io/queue-name: lq-low
spec:
  parallelism: 6
  completions: 6
  suspend: true
  template:
    spec:
      priorityClassName: low-priority
      restartPolicy: Never
      containers:
        - name: worker
          image: busybox:1.36
          command: ["sh", "-c", "echo 'LOW-PRIORITY pod $(hostname) started'; sleep 300"]
          resources:
            requests:
              cpu: "1"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "256Mi"
```

### 07-high-priority-gang-job.yaml

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: high-priority-gang
  namespace: cohort-preemption-demo
  labels:
    kueue.x-k8s.io/queue-name: lq-high
spec:
  parallelism: 3
  completions: 3
  suspend: true
  template:
    spec:
      priorityClassName: high-priority
      restartPolicy: Never
      containers:
        - name: worker
          image: busybox:1.36
          command: ["sh", "-c", "echo 'HIGH-PRIORITY pod $(hostname) started'; sleep 60"]
          resources:
            requests:
              cpu: "1"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "256Mi"
```
