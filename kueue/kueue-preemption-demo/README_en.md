# Kueue Gang Scheduling + Priority-Based Preemption Demo

This document walks through a complete end-to-end demonstration of Kueue preempting one gang job in favour of a higher-priority gang job. Every command shown below includes its **actual output** captured from a live kind cluster, along with annotated **Kueue controller logs**.

## Scenario Design

```
ClusterQueue: demo-cq  ─── CPU quota: 4 cores (intentionally matches a single gang job's request)
                                │
                                │  preemption.withinClusterQueue: LowerPriority
                                │  ↑ key setting: allows higher-priority workloads to preempt
                                │    lower-priority ones within the same ClusterQueue
                                │
                        LocalQueue: demo-lq
                       ┌────────┴────────┐
              low-priority-gang      high-priority-gang
              parallelism=4          parallelism=4
              4×1 CPU = 4 cores      4×1 CPU = 4 cores
              PriorityClass=100      PriorityClass=1000
              sleep 300s             sleep 60s
```

**Expected timeline:**

```
T+0s   │ low-priority-gang submitted → immediately Admitted (4 pods Running, queue full)
T+23s  │ high-priority-gang submitted → preemption triggered
T+23s  │ Kueue decision: low-priority Evicted, high-priority Admitted
T+83s  │ high-priority-gang completes (sleep 60s done)
T+84s  │ Kueue reschedules low-priority-gang → automatically Resumed (4 new pods created)
```

---

## Prerequisites

| Resource | Requirement |
|---|---|
| kind cluster | Running with `kubectl` configured |
| Kueue controller | Pod Running in `kueue-system` namespace |
| ResourceFlavor `default-flavor` | Already exists |

---

## File Overview

```
01-priority-classes.yaml   PriorityClass: low-priority(100) / high-priority(1000)
02-namespace.yaml          Namespace: preemption-demo
03-clusterqueue.yaml       ClusterQueue: demo-cq, 4-CPU quota, withinClusterQueue: LowerPriority
04-localqueue.yaml         LocalQueue: demo-lq
05-low-priority-job.yaml   Gang Job: parallelism=4, 4×1CPU, sleep 300s, low-priority
06-high-priority-job.yaml  Gang Job: parallelism=4, 4×1CPU, sleep 60s,  high-priority
```

---

## Step-by-Step Walkthrough with Real Output

### Step 0 — Verify the environment

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

### Step 1 — Deploy base resources

```bash
kubectl apply -f 01-priority-classes.yaml
kubectl apply -f 02-namespace.yaml
kubectl apply -f 03-clusterqueue.yaml
kubectl apply -f 04-localqueue.yaml
```

```
priorityclass.scheduling.k8s.io/low-priority created
priorityclass.scheduling.k8s.io/high-priority created
namespace/preemption-demo created
clusterqueue.kueue.x-k8s.io/demo-cq created
localqueue.kueue.x-k8s.io/demo-lq created
```

**Verify PriorityClasses:**

```bash
kubectl get priorityclass low-priority high-priority
```

```
NAME            VALUE   GLOBAL-DEFAULT   AGE   PREEMPTIONPOLICY
low-priority    100     false            5s    PreemptLowerPriority
high-priority   1000    false            5s    PreemptLowerPriority
```

**Verify ClusterQueue preemption config (critical):**

```bash
kubectl get clusterqueue demo-cq -o jsonpath='{.spec.preemption}' | python3 -m json.tool
```

```json
{
    "borrowWithinCohort": {
        "policy": "Never"
    },
    "reclaimWithinCohort": "Never",
    "withinClusterQueue": "LowerPriority"
}
```

**Verify ClusterQueue resource quota:**

```bash
kubectl get clusterqueue demo-cq -o jsonpath='{.spec.resourceGroups}' | python3 -m json.tool
```

```json
[
    {
        "coveredResources": ["cpu", "memory"],
        "flavors": [
            {
                "name": "default-flavor",
                "resources": [
                    {"name": "cpu",    "nominalQuota": "4"},
                    {"name": "memory", "nominalQuota": "4Gi"}
                ]
            }
        ]
    }
]
```

**Verify LocalQueue:**

```bash
kubectl get localqueue -n preemption-demo
```

```
NAME      CLUSTERQUEUE   PENDING WORKLOADS   ADMITTED WORKLOADS
demo-lq   demo-cq        0                   0
```

---

### Step 2 — Submit the low-priority gang job (T=0s)

```bash
kubectl apply -f 05-low-priority-job.yaml
# Submitted at: 2026-05-21T15:49:58Z
```

```
job.batch/low-priority-gang created
```

**Check state after ~8 seconds (busybox image is cached locally, pods start almost instantly):**

```bash
kubectl get workloads -n preemption-demo
```

```
NAME                          QUEUE     RESERVED IN   ADMITTED   FINISHED   AGE
job-low-priority-gang-238f2   demo-lq   demo-cq       True                  13s
```

> `ADMITTED=True` and `RESERVED IN=demo-cq` confirm that Kueue has reserved quota for this workload and unsuspended the Job.

```bash
kubectl get pods -n preemption-demo
```

```
NAME                      READY   STATUS    RESTARTS   AGE
low-priority-gang-b7qld   1/1     Running   0          13s
low-priority-gang-m4mg7   1/1     Running   0          13s
low-priority-gang-qm6pj   1/1     Running   0          13s
low-priority-gang-wbdkq   1/1     Running   0          13s
```

> All 4 pods are Running simultaneously — this is the gang scheduling atomicity guarantee: Kueue admits all 4 pods **at once** or none at all.

```bash
kubectl get job low-priority-gang -n preemption-demo -o wide
```

```
NAME                STATUS    COMPLETIONS   DURATION   AGE   CONTAINERS   IMAGES
low-priority-gang   Running   0/4           13s        13s   worker       busybox:1.36
```

**Confirm the ClusterQueue is now at full capacity (4/4 cores used):**

```bash
kubectl get clusterqueue demo-cq -o jsonpath='{.status.flavorsUsage}' | python3 -m json.tool
```

```json
[
    {
        "name": "default-flavor",
        "resources": [
            {"borrowed": "0", "name": "cpu",    "total": "4"},
            {"borrowed": "0", "name": "memory", "total": "1Gi"}
        ]
    }
]
```

> `total: 4` CPU used, `borrowed: 0` (no cohort borrowing). The queue is full — the next 4-CPU request will necessarily trigger preemption.

**Kueue controller log — low-priority admission sequence:**

```json
// [1] Job submitted; Kueue creates a corresponding Workload object
{"ts":"2026-05-21T15:49:58.554260Z","logger":"workload-reconciler",
 "msg":"Workload create event",
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "queue":"demo-lq","status":"pending"}

// [2] Scheduler picks it up in scheduling cycle #13
{"ts":"2026-05-21T15:49:58.554518Z","logger":"scheduler",
 "msg":"Attempting to schedule workload","schedulingCycle":13,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"}}

// [3] Quota successfully reserved in the scheduler's in-memory cache
{"ts":"2026-05-21T15:49:58.554557Z","logger":"scheduler",
 "msg":"Workload assumed in the cache","schedulingCycle":13,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"}}

// [4] Admission complete — flavor and resource assignments logged
{"ts":"2026-05-21T15:49:58.559768Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":13,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"},
 "assignments":[{"name":"main",
   "flavors":{"cpu":"default-flavor","memory":"default-flavor"},
   "resourceUsage":{"cpu":"4","memory":"1Gi"},
   "count":4}]}

// [5] QuotaReserved event emitted (queued for 1 second before admission)
{"ts":"2026-05-21T15:49:58.559794Z","logger":"events",
 "msg":"Quota reserved in ClusterQueue demo-cq, wait time since queued was 1s",
 "reason":"QuotaReserved"}

// [6] Admitted event emitted
{"ts":"2026-05-21T15:49:58.559804Z","logger":"events",
 "msg":"Admitted by ClusterQueue demo-cq, wait time since reservation was 0s",
 "reason":"Admitted"}

// [7] Workload reconciler instructs the Job controller to unsuspend the Job
{"ts":"2026-05-21T15:49:58.559992Z","logger":"job",
 "msg":"Job admitted, unsuspending",
 "job":"preemption-demo/low-priority-gang"}
```

---

### Step 3 — Submit the high-priority gang job to trigger preemption (T=+23s)

```bash
kubectl apply -f 06-high-priority-job.yaml
# Submitted at: 2026-05-21T15:50:21Z
```

```
job.batch/high-priority-gang created
```

**Check state after ~8 seconds:**

```bash
kubectl get workloads -n preemption-demo
```

```
NAME                           QUEUE     RESERVED IN   ADMITTED   FINISHED   AGE
job-high-priority-gang-91d4a   demo-lq   demo-cq       True                  15s
job-low-priority-gang-238f2    demo-lq                 False                 38s
```

> - `high-priority`: `ADMITTED=True`, `RESERVED IN=demo-cq` ← **preemption succeeded, now running**
> - `low-priority`: `ADMITTED=False`, `RESERVED IN=(empty)` ← **preempted, waiting to be rescheduled**

```bash
kubectl get pods -n preemption-demo
```

```
NAME                       READY   STATUS        RESTARTS   AGE
high-priority-gang-67qgw   1/1     Running       0          15s
high-priority-gang-fdw5w   1/1     Running       0          15s
high-priority-gang-lsp2h   1/1     Running       0          15s
high-priority-gang-n5756   1/1     Running       0          15s
low-priority-gang-b7qld    1/1     Terminating   0          38s
low-priority-gang-m4mg7    1/1     Terminating   0          38s
low-priority-gang-qm6pj    1/1     Terminating   0          38s
low-priority-gang-wbdkq    1/1     Terminating   0          38s
```

> 4 high-priority pods are Running while the 4 low-priority pods are Terminating. The pod name suffixes are completely different, confirming two independent gang admit events.

```bash
kubectl get jobs -n preemption-demo \
  -o custom-columns="NAME:.metadata.name,SUSPEND:.spec.suspend,ACTIVE:.status.active,READY:.status.ready,SUCCEEDED:.status.succeeded"
```

```
NAME                 SUSPEND   ACTIVE   READY   SUCCEEDED
high-priority-gang   false     4        4       <none>
low-priority-gang    true      <none>   0       <none>
```

> Kueue set `low-priority-gang`'s `spec.suspend=true`. The Job controller detects this field change and deletes all running pods.

**Kubernetes Events — complete audit chain for the preemption decision:**

```
# ─── Preemption triggered ──────────────────────────────────────────────────────

Warning  Pending   workload/job-high-priority-gang-91d4a
  couldn't assign flavors to pod set main: insufficient unused quota for cpu
  in flavor default-flavor, 4 more needed.
  Pending the preemption of 1 workload(s)
  ↑ Kueue detected that 1 workload must be preempted to satisfy the high-priority request

Normal   EvictedDueToPreempted  workload/job-low-priority-gang-238f2
  Preempted to accommodate a workload
  (UID: 16739dd5-3342-4f5e-8bc5-20833d49b3ff, JobUID: 60a0290d-...)
  due to prioritization in the ClusterQueue;
  preemptor path: /demo-cq; preemptee path: /demo-cq
  ↑ The low-priority workload is evicted; preemptor and preemptee UIDs are recorded

Normal   Preempted   workload/job-low-priority-gang-238f2   (same message as above)
Normal   Stopped     job/low-priority-gang                  (same message as above)

# ─── low-priority Job suspended ───────────────────────────────────────────────

Normal   Suspended   job/low-priority-gang
  Job suspended
  ↑ spec.suspend set to true; Job controller responds by deleting all pods

Normal   Killing     pod/low-priority-gang-b7qld   Stopping container worker
Normal   Killing     pod/low-priority-gang-m4mg7   Stopping container worker
Normal   Killing     pod/low-priority-gang-qm6pj   Stopping container worker
Normal   Killing     pod/low-priority-gang-wbdkq   Stopping container worker

# ─── high-priority gains quota and starts ─────────────────────────────────────

Normal   QuotaReserved  workload/job-high-priority-gang-91d4a
  Quota reserved in ClusterQueue demo-cq, wait time since queued was 1s

Normal   Admitted    workload/job-high-priority-gang-91d4a
  Admitted by ClusterQueue demo-cq, wait time since reservation was 0s

Normal   Resumed     job/high-priority-gang
  Job resumed
  ↑ spec.suspend set to false; Job controller creates 4 new pods

Normal   Started     job/high-priority-gang
  Admitted by clusterQueue demo-cq
```

**Kueue controller log — key entries for the preemption cycle:**

```json
// [1] After preemption: low-priority workload tries to reschedule but quota is taken
{"ts":"2026-05-21T15:50:21.974Z","logger":"events",
 "msg":"couldn't assign flavors to pod set main: insufficient unused quota for cpu
        in flavor default-flavor, 4 more needed",
 "type":"Warning","reason":"Pending",
 "object":{"name":"job-low-priority-gang-238f2",...}}
 // ↑ This warning appears on the low-priority workload because it has been evicted
 //   from admitted state and is now trying to re-enter the scheduling queue

// [2] Scheduler finds low-priority cannot preempt anyone (it has the lowest priority)
{"ts":"2026-05-21T15:50:22.954Z","logger":"scheduler",
 "msg":"Workload requires preemption, but there are no candidate workloads allowed for preemption",
 "schedulingCycle":22,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"},
 "preemption":{"reclaimWithinCohort":"Never",
               "borrowWithinCohort":{"policy":"Never"},
               "withinClusterQueue":"LowerPriority"}}
 // ↑ withinClusterQueue=LowerPriority means only higher-priority workloads can preempt —
 //   low-priority has no one below it to preempt

// [3] Workload moves into the inadmissible queue and waits for resources to free up
{"ts":"2026-05-21T15:50:22.954Z","logger":"scheduler",
 "msg":"Workload re-queued",
 "schedulingCycle":22,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"},
 "queue":{"name":"demo-lq","namespace":"preemption-demo"}}
```

---

### Step 4 — Wait for high-priority to complete; observe low-priority auto-resume (T=+83s)

Live watch (refreshes every 3 seconds):

```bash
watch -n 3 "
  kubectl get workloads -n preemption-demo && echo && \
  kubectl get pods -n preemption-demo && echo && \
  kubectl get jobs -n preemption-demo \
    -o custom-columns='NAME:.metadata.name,SUSPEND:.spec.suspend,ACTIVE:.status.active,SUCCEEDED:.status.succeeded'
"
```

Or poll with a script until the completion signal arrives:

```bash
for i in $(seq 1 20); do
  sleep 5
  HIGH=$(kubectl get job high-priority-gang -n preemption-demo \
    -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null)
  LOW_ACTIVE=$(kubectl get job low-priority-gang -n preemption-demo \
    -o jsonpath='{.status.active}' 2>/dev/null)
  LOW_SUSPEND=$(kubectl get job low-priority-gang -n preemption-demo \
    -o jsonpath='{.spec.suspend}' 2>/dev/null)
  echo "[$(date +%H:%M:%S)] high complete=$HIGH | low suspend=$LOW_SUSPEND active=$LOW_ACTIVE"
  [ "$HIGH" = "True" ] && echo ">>> High-priority DONE!" && break
done
```

**Actual output (captured from the live run):**

```
[11:50:30] high complete=  | low suspend=true  active=
[11:50:35] high complete=  | low suspend=true  active=
[11:50:40] high complete=  | low suspend=true  active=
[11:50:45] high complete=  | low suspend=true  active=
[11:50:50] high complete=  | low suspend=true  active=
[11:50:55] high complete=  | low suspend=true  active=
[11:51:00] high complete=  | low suspend=true  active=
[11:51:05] high complete=  | low suspend=true  active=
[11:51:10] high complete=  | low suspend=true  active=
[11:51:15] high complete=  | low suspend=true  active=
[11:51:20] high complete=  | low suspend=true  active=
[11:51:25] high complete=True | low suspend=false active=4
>>> High-priority DONE!
```

> high-priority finishes at T+83s. Kueue immediately reschedules low-priority (`suspend=false, active=4`).

**Kubernetes Events — high-priority completion and low-priority resume:**

```
Normal   Completed         job/high-priority-gang
  Job completed

Normal   FinishedWorkload  job/high-priority-gang
  Workload 'preemption-demo/job-high-priority-gang-91d4a' is declared finished

Normal   QuotaReserved     workload/job-low-priority-gang-238f2
  Quota reserved in ClusterQueue demo-cq, wait time since queued was 65s
  ↑ low-priority waited 65 seconds in the inadmissible queue before regaining quota

Normal   Admitted          workload/job-low-priority-gang-238f2
  Admitted by ClusterQueue demo-cq, wait time since reservation was 0s

Normal   Resumed           job/low-priority-gang
  Job resumed

Normal   Started           job/low-priority-gang
  Admitted by clusterQueue demo-cq
```

**Kueue controller log — high-priority finishes, low-priority resumes:**

```json
// [1] All high-priority pods complete; FinishedWorkload event fired
{"ts":"2026-05-21T15:51:25.424Z","logger":"events",
 "msg":"Workload 'preemption-demo/job-high-priority-gang-91d4a' is declared finished",
 "type":"Normal","reason":"FinishedWorkload"}

// [2] workload-reconciler detects the finished status and releases 4 CPUs back to demo-cq
{"ts":"2026-05-21T15:51:25.424Z","logger":"workload-reconciler",
 "msg":"Workload update event",
 "workload":{"name":"job-high-priority-gang-91d4a","namespace":"preemption-demo"},
 "status":"finished","prevStatus":"admitted","clusterQueue":"demo-cq"}

// [3] inadmissible_workload_requeue_worker background goroutine fires,
//     moving the waiting low-priority workload back into the scheduling queue
{"ts":"2026-05-21T15:51:26.429Z","logger":"inadmissible_workload_requeue_worker",
 "msg":"Resetting the head of the ClusterQueue","clusterQueue":"demo-cq"}
{"ts":"2026-05-21T15:51:26.429Z","logger":"inadmissible_workload_requeue_worker",
 "msg":"Moved workloads","clusterqueue":"demo-cq","count":1}
 // ↑ count=1: one workload (low-priority) moved back into the schedulable queue

// [4] Scheduling cycle #23 successfully schedules low-priority (waited 63.5 s at head)
{"ts":"2026-05-21T15:51:26.430Z","logger":"scheduler",
 "msg":"Obtained heads","schedulingCycle":23,"headCount":1,
 "waitDuration":63.476080737}
 // ↑ waitDuration: how long (seconds) the workload spent at the head of the queue

{"ts":"2026-05-21T15:51:26.430Z","logger":"scheduler",
 "msg":"Workload assumed in the cache","schedulingCycle":23,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"}}

// [5] Admission complete with resource assignments
{"ts":"2026-05-21T15:51:26.446Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":23,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"},
 "assignments":[{"name":"main",
   "flavors":{"cpu":"default-flavor","memory":"default-flavor"},
   "resourceUsage":{"cpu":"4","memory":"1Gi"},
   "count":4}]}

// [6] QuotaReserved (had been waiting 65 seconds since being preempted)
{"ts":"2026-05-21T15:51:26.446Z","logger":"events",
 "msg":"Quota reserved in ClusterQueue demo-cq, wait time since queued was 65s",
 "reason":"QuotaReserved"}

// [7] Admitted
{"ts":"2026-05-21T15:51:26.446Z","logger":"events",
 "msg":"Admitted by ClusterQueue demo-cq, wait time since reservation was 0s",
 "reason":"Admitted"}

// [8] Job controller unsuspends the Job and recreates pods
{"ts":"2026-05-21T15:51:26.447Z","logger":"job",
 "msg":"Job admitted, unsuspending",
 "job":"preemption-demo/low-priority-gang"}
```

---

### Step 5 — Confirm final state

```bash
kubectl get workloads -n preemption-demo
```

```
NAME                           QUEUE     RESERVED IN   ADMITTED   FINISHED   AGE
job-high-priority-gang-91d4a   demo-lq   demo-cq       True       True       4m9s
job-low-priority-gang-238f2    demo-lq   demo-cq       True                  4m32s
```

> `FINISHED=True` (high-priority) and `ADMITTED=True` (low-priority) appear simultaneously — the scenario has completed cleanly.

```bash
kubectl get pods -n preemption-demo
```

```
NAME                       READY   STATUS      RESTARTS   AGE
high-priority-gang-67qgw   0/1     Completed   0          4m9s
high-priority-gang-fdw5w   0/1     Completed   0          4m9s
high-priority-gang-lsp2h   0/1     Completed   0          4m9s
high-priority-gang-n5756   0/1     Completed   0          4m9s
low-priority-gang-9z7zh    1/1     Running     0          3m4s
low-priority-gang-bx42n    1/1     Running     0          3m4s
low-priority-gang-kfccb    1/1     Running     0          3m4s
low-priority-gang-v5b9v    1/1     Running     0          3m4s
```

> Note the pod name suffixes: after resuming, low-priority has **brand-new pods** (`9z7zh, bx42n, kfccb, v5b9v`), completely different from the original set (`b7qld, m4mg7, qm6pj, wbdkq`). This is expected — the Job controller creates fresh pods each time a Job is unsuspended.

```bash
kubectl get jobs -n preemption-demo \
  -o custom-columns="NAME:.metadata.name,SUSPEND:.spec.suspend,ACTIVE:.status.active,SUCCEEDED:.status.succeeded"
```

```
NAME                 SUSPEND   ACTIVE   SUCCEEDED
high-priority-gang   false     <none>   4
low-priority-gang    false     4        <none>
```

---

## Actual Timeline (this run)

| Time (UTC) | Relative | Event |
|---|---|---|
| 15:49:58 | T+0s | `low-priority-gang` submitted; Kueue creates Workload |
| 15:49:58 | T+0s | Scheduler cycle #13: Admitted, 4 CPUs allocated |
| 15:49:58 | T+0s | `low-priority-gang` unsuspended; 4 pods created |
| 15:49:59 | T+1s | 4 pods Running (image already cached locally) |
| 15:50:21 | T+23s | `high-priority-gang` submitted |
| 15:50:21 | T+23s | Kueue preemption decision: evict `low-priority-gang`, admit `high-priority-gang` |
| 15:50:21 | T+23s | `low-priority-gang` suspended; 4 pods Terminating |
| 15:50:21 | T+23s | `high-priority-gang` unsuspended; 4 pods created |
| 15:50:22 | T+24s | high-priority 4 pods Running |
| 15:51:25 | T+87s | `high-priority-gang` completes (sleep 60s) |
| 15:51:25 | T+87s | workload-reconciler detects finished; 4 CPUs released |
| 15:51:26 | T+88s | inadmissible_requeue_worker moves `low-priority-gang` back into scheduling queue |
| 15:51:26 | T+88s | Scheduler cycle #23: `low-priority-gang` re-Admitted (waited 65 seconds) |
| 15:51:26 | T+88s | `low-priority-gang` unsuspended; 4 new pods created |
| 15:51:27 | T+89s | low-priority 4 pods Running |

---

## How It Works Internally

### Kueue preemption decision flow

```
1. high-priority-gang submitted
   → Job controller creates a Workload object under Kueue management (spec.suspend=true)

2. Scheduler scheduling loop picks up the high-priority Workload
   → Checks demo-cq available quota: cpu=0 (all consumed by low-priority)
   → Evaluates withinClusterQueue=LowerPriority:
        high-priority(1000) > low-priority(100) ✓
        releasing low-priority would free exactly 4 CPUs ✓
   → Decision: initiate preemption

3. Kueue sets low-priority-gang Job spec.suspend=true
   → Job controller deletes all running pods (4 pods → Terminating)
   → Workload status: EvictedDueToPreempted → enters inadmissible queue

4. Kueue reserves quota for high-priority-gang
   → Workload status: QuotaReserved → Admitted
   → Job spec.suspend set to false
   → Job controller creates 4 new pods

5. high-priority pods finish sleep 60, complete
   → workload-reconciler detects Job Completed, marks Workload as finished
   → ClusterQueue releases 4 CPUs

6. inadmissible_workload_requeue_worker (background goroutine)
   → Periodically checks the inadmissible queue
   → Moves low-priority Workload back to head-of-queue

7. Next scheduler cycle successfully schedules low-priority
   → Same flow as Step 2: Admitted → unsuspend → 4 new pods created
```

### Gang scheduling atomicity guarantee

Kueue treats a Job with `parallelism=4` as a single atomic workload unit:
- Either all 4 pods receive quota simultaneously (gang admit), or none do
- Prevents deadlocks caused by partial admission (some pods running, others waiting indefinitely)
- Preemption also evicts the entire gang at once — no partial termination

### The suspend/unsuspend mechanism

```
Kueue does not manage pod lifecycles directly. Instead it cooperates with the
Job controller through the Job.spec.suspend field:

  admit   → Kueue writes spec.suspend=false → Job controller creates pods
  preempt → Kueue writes spec.suspend=true  → Job controller deletes all pods

This design lets Kueue support any job type that implements suspend/resume semantics:
batch/v1 Job, JobSet, PyTorchJob, RayJob, etc.
```

---

## Cleanup

```bash
kubectl delete namespace preemption-demo
kubectl delete clusterqueue demo-cq
kubectl delete priorityclass low-priority high-priority
```

Verify cleanup:
```bash
kubectl get ns preemption-demo 2>&1          # Error from server (NotFound)
kubectl get clusterqueue demo-cq 2>&1        # Error from server (NotFound)
kubectl get priorityclass low-priority 2>&1  # Error from server (NotFound)
```

---

## Appendix: Complete YAML Files

### 01-priority-classes.yaml

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: low-priority
value: 100
globalDefault: false
description: "Low priority workloads — can be preempted by high-priority jobs"
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000
globalDefault: false
description: "High priority workloads — can preempt low-priority jobs"
```

### 02-namespace.yaml

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: preemption-demo
  labels:
    kueue.x-k8s.io/managed: "true"
```

### 03-clusterqueue.yaml

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
kind: ClusterQueue
metadata:
  name: demo-cq
spec:
  namespaceSelector: {}
  queueingStrategy: BestEffortFIFO
  preemption:
    withinClusterQueue: LowerPriority   # allow higher-priority workloads to preempt lower-priority ones
    reclaimWithinCohort: Never
    borrowWithinCohort:
      policy: Never
  resourceGroups:
    - coveredResources: ["cpu", "memory"]
      flavors:
        - name: default-flavor
          resources:
            - name: cpu
              nominalQuota: "4"       # intentionally set to 4 to exactly match a single gang job's request
            - name: memory
              nominalQuota: "4Gi"
```

### 04-localqueue.yaml

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
kind: LocalQueue
metadata:
  name: demo-lq
  namespace: preemption-demo
spec:
  clusterQueue: demo-cq
```

### 05-low-priority-job.yaml

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: low-priority-gang
  namespace: preemption-demo
  labels:
    kueue.x-k8s.io/queue-name: demo-lq   # tells Kueue which LocalQueue to use
spec:
  parallelism: 4          # gang: all 4 pods must be admitted together
  completions: 4
  suspend: true           # Kueue requires jobs to be submitted in suspended state
  template:
    metadata:
      labels:
        app: low-priority-gang
    spec:
      priorityClassName: low-priority
      restartPolicy: Never
      containers:
        - name: worker
          image: busybox:1.36
          command: ["sh", "-c", "echo 'LOW-PRIORITY pod started'; sleep 300; echo 'LOW-PRIORITY pod done'"]
          resources:
            requests:
              cpu: "1"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "256Mi"
```

### 06-high-priority-job.yaml

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: high-priority-gang
  namespace: preemption-demo
  labels:
    kueue.x-k8s.io/queue-name: demo-lq   # tells Kueue which LocalQueue to use
spec:
  parallelism: 4          # gang: all 4 pods must be admitted together
  completions: 4
  suspend: true           # Kueue requires jobs to be submitted in suspended state
  template:
    metadata:
      labels:
        app: high-priority-gang
    spec:
      priorityClassName: high-priority
      restartPolicy: Never
      containers:
        - name: worker
          image: busybox:1.36
          command: ["sh", "-c", "echo 'HIGH-PRIORITY pod started'; sleep 60; echo 'HIGH-PRIORITY pod done'"]
          resources:
            requests:
              cpu: "1"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "256Mi"
```
