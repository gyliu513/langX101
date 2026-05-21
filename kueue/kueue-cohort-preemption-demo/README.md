# Kueue Cohort 跨队列抢占演示

本文档演示 Kueue **跨 ClusterQueue 的优先级抢占**（`reclaimWithinCohort`）。
与基础抢占（`withinClusterQueue`）不同，本场景的抢占跨越两个不同的 ClusterQueue：
高优先级队列的 job 回收了被低优先级队列借走的配额。
包含所有命令的**真实执行输出**和 **Kueue controller 内部日志**。

---

## 与基础抢占 Demo 的对比

| 维度 | 基础抢占 | Cohort 跨队列抢占 |
|---|---|---|
| 配置项 | `withinClusterQueue: LowerPriority` | `reclaimWithinCohort: LowerPriority` |
| 抢占范围 | **同一 ClusterQueue 内** | **Cohort 内跨 ClusterQueue** |
| 触发条件 | 高优先级 job 在同队列内资源不足 | 高优先级队列的配额被**其他队列借走**，提交 job 时触发回收 |
| 核心概念 | 队列内优先级排序 | 跨队列配额借用与回收 |

---

## 场景设计

```
Cohort: preemption-cohort（总容量 6 CPU = cq-high 3 + cq-low 3）
│
├── ClusterQueue: cq-high  ── nominalQuota=3 CPU
│   └── LocalQueue: lq-high（namespace: cohort-preemption-demo）
│       └── high-priority-gang: 3 pods × 1CPU，PriorityClass=1000，sleep 60s
│
└── ClusterQueue: cq-low   ── nominalQuota=3 CPU
    └── LocalQueue: lq-low（namespace: cohort-preemption-demo）
        └── low-priority-gang:  6 pods × 1CPU，PriorityClass=100，sleep 300s
```

**时间线：**
```
T+0s   │ low-priority-gang 提交（需要 6 CPU）
T+0s   │ cq-high 空闲 → cq-low 借用 3 CPU → low-priority 以 6 pods 运行
T+20s  │ high-priority-gang 提交（需要 3 CPU）
T+20s  │ 触发 reclaimWithinCohort：cq-high 回收被 cq-low 借走的 3 CPU
T+20s  │ low-priority-gang 被 evict（整个 gang 挂起）
T+20s  │ high-priority-gang 以 3 pods 运行（使用 cq-high 的 3 CPU）
T+20s  │ low-priority-gang 在队列等待（cq-low 只有 3 CPU，不满足 gang 需要的 6 CPU）
T+80s  │ high-priority-gang 完成（sleep 60s）
T+81s  │ cq-high 3 CPU 释放，low-priority-gang 重新以 6 pods 运行
```

---

## 前提条件

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

## 文件清单

```
01-namespace.yaml           Namespace: cohort-preemption-demo
02-priority-classes.yaml    PriorityClass: low-priority(100) / high-priority(1000)
03-clusterqueue-high.yaml   CQ: cq-high，nominalQuota=3 CPU，reclaimWithinCohort: LowerPriority
04-clusterqueue-low.yaml    CQ: cq-low，nominalQuota=3 CPU，reclaimWithinCohort: LowerPriority
05-localqueues.yaml         LocalQueue: lq-high / lq-low
06-low-priority-gang-job.yaml   Gang Job: 6 pods，low-priority，sleep 300s
07-high-priority-gang-job.yaml  Gang Job: 3 pods，high-priority，sleep 60s
```

---

## 完整执行步骤与真实输出

### Step 1 — 部署基础资源

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

**验证：**

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

> 两个 CQ 在同一 cohort `preemption-cohort`，每个 nominalQuota=3 CPU，`reclaimWithinCohort: LowerPriority` 允许跨 CQ 回收被低优先级借走的配额。

```bash
kubectl get localqueue -n cohort-preemption-demo
```
```
NAME      CLUSTERQUEUE   PENDING WORKLOADS   ADMITTED WORKLOADS
lq-high   cq-high        0                   0
lq-low    cq-low         0                   0
```

---

### Step 2 — 提交 low-priority gang job（T=0s）

```bash
kubectl apply -f 06-low-priority-gang-job.yaml
# 提交时间: 2026-05-21T17:02:38Z
```
```
job.batch/low-priority-gang created
```

**等待 8 秒后检查：**

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

> **6 个 pod 全部 Running**，超过 cq-low 的 nominalQuota（3 CPU）。额外 3 CPU 来自借用 cq-high 的空闲配额。

```bash
kubectl get clusterqueue cq-high cq-low \
  -o custom-columns="NAME:.metadata.name,NOMINAL:.spec.resourceGroups[0].flavors[0].resources[0].nominalQuota,USED:.status.flavorsUsage[0].resources[0].total,BORROWED:.status.flavorsUsage[0].resources[0].borrowed"
```
```
NAME      NOMINAL   USED   BORROWED
cq-high   3         0      0          ← 空闲，3 CPU 被 cq-low 借走
cq-low    3         6      3          ← 使用 6 CPU，其中 3 CPU 是借来的
```

> `cq-low BORROWED=3`：低优先级 job 跨 CQ 借用了 cq-high 的全部 3 CPU。

**Kubernetes Events（Step 2）：**

```
Normal   QuotaReserved   workload/job-low-priority-gang-44684
  Quota reserved in ClusterQueue cq-low, wait time since queued was 0s;
  Flavors considered: main: default-flavor(Fit;borrow=1)
  ↑ "borrow=1" 表示此次 admit 使用了借用配额
```

**Kueue log（Step 2，low-priority 以 6 pods 借用全部资源）：**

```json
// 调度循环成功，resourceUsage=6 CPU，count=6（3 nominal + 3 borrowed）
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

### Step 3 — 提交 high-priority gang job，触发跨 CQ 抢占（T=+20s）

```bash
kubectl apply -f 07-high-priority-gang-job.yaml
# 提交时间: 2026-05-21T17:02:58Z
```
```
job.batch/high-priority-gang created
```

**等待 8 秒后检查（抢占已发生）：**

```bash
kubectl get workloads -n cohort-preemption-demo
```
```
NAME                           QUEUE     RESERVED IN   ADMITTED   FINISHED   AGE
job-high-priority-gang-e2828   lq-high   cq-high       True                  13s
job-low-priority-gang-44684    lq-low                  False                 33s
```

> - `high-priority`: `ADMITTED=True`，`RESERVED IN=cq-high` ← **跨 CQ 回收成功，正在运行**
> - `low-priority`: `ADMITTED=False`，`RESERVED IN=(空)` ← **被跨 CQ 抢占，等待重新调度**

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

> cq-high: `USED=3, BORROWED=0`，cq-low: `USED=0`——高优先级 job 正在使用自己的 nominalQuota，借用的配额已被回收。

**Kubernetes Events — 跨 CQ 抢占完整事件链：**

```
# ─── high-priority 提交时，配额不足，触发抢占评估 ──────────────────────────────

Warning  Pending   workload/job-high-priority-gang-e2828
  couldn't assign flavors to pod set main: insufficient unused quota for cpu
  in flavor default-flavor, 3 more needed. Pending the preemption of 1 workload(s)
  ↑ Kueue 检测到需要抢占 1 个 workload 才能满足 cq-high 的配额请求

# ─── low-priority 被驱逐 ──────────────────────────────────────────────────────

Normal   EvictedDueToPreempted  workload/job-low-priority-gang-44684
  Preempted to accommodate a workload (UID: 2daed6fd-..., JobUID: 5e63deb5-...)
  due to reclamation within the cohort;
  preemptor path: /preemption-cohort/cq-high;   ← 抢占方：cq-high 队列
  preemptee path: /preemption-cohort/cq-low     ← 被抢占方：cq-low 队列
  ↑ 注意：preemptor 和 preemptee 在不同 CQ，这是跨 CQ 抢占的标志

Normal   Preempted   workload/job-low-priority-gang-44684  （同上消息）
Normal   Stopped     job/low-priority-gang                 （同上消息）

Normal   Suspended   job/low-priority-gang
  Job suspended
  ↑ Kueue 将 spec.suspend=true，Job controller 删除所有 6 个 pod

# ─── high-priority 获得配额并启动 ────────────────────────────────────────────

Normal   QuotaReserved  workload/job-high-priority-gang-e2828
  Quota reserved in ClusterQueue cq-high, wait time since queued was 1s

Normal   Admitted    workload/job-high-priority-gang-e2828
  Admitted by ClusterQueue cq-high, wait time since reservation was 0s

Normal   Resumed     job/high-priority-gang
  Job resumed  ↑ spec.suspend=false，3 个新 pod 创建

# ─── low-priority 等待（需要 6 CPU，但只有 cq-low 的 3 CPU 可用）──────────────

Warning  Pending     workload/job-low-priority-gang-44684
  couldn't assign flavors to pod set main: insufficient unused quota for cpu
  in flavor default-flavor, 3 more needed
  ↑ gang job 需要 6 CPU，cq-low 只有 3 CPU，cq-high 被 high-priority 占用，无法借用
```

**Kueue controller log — 跨 CQ 抢占核心日志：**

```json
// [1] Scheduling cycle #6752：high-priority 提交，同一 cycle 同时处理两个 workload
// high-priority 被 assume（预先分配），low-priority 被重排队
{"ts":"2026-05-21T17:02:58.757Z","logger":"scheduler",
 "msg":"Workload assumed in the cache","schedulingCycle":6752,
 "workload":{"name":"job-high-priority-gang-e2828","namespace":"cohort-preemption-demo"},
 "clusterQueue":{"name":"cq-high"},
 "parentCohort":{"name":"preemption-cohort"},
 "rootCohort":{"name":"preemption-cohort"}}
 // ↑ parentCohort/rootCohort 说明这是 cohort 范围内的调度决策

// [2] low-priority workload 在同一 cycle 被标记为 FailedAfterNomination
{"ts":"2026-05-21T17:02:58.757Z","logger":"scheduler",
 "msg":"Workload re-queued","schedulingCycle":6752,
 "workload":{"name":"job-low-priority-gang-44684","namespace":"cohort-preemption-demo"},
 "clusterQueue":{"name":"cq-low"},
 "requeueReason":"FailedAfterNomination"}
 // ↑ FailedAfterNomination：cq-high 回收了配额，low-priority 的借用资格被撤销

// [3] high-priority 以 3 pods 正式 admit（count=3，resourceUsage=3 CPU）
{"ts":"2026-05-21T17:02:58.761Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":6752,
 "workload":{"name":"job-high-priority-gang-e2828","namespace":"cohort-preemption-demo"},
 "clusterQueue":{"name":"cq-high"},
 "parentCohort":{"name":"preemption-cohort"},
 "assignments":[{"name":"main",
   "resourceUsage":{"cpu":"3","memory":"768Mi"},
   "count":3}]}

// [4] Scheduling cycle #6753：low-priority 尝试重新调度，但没有可抢占的候选
// （low-priority 的优先级=100，它不能抢占 high-priority=1000）
{"ts":"2026-05-21T17:02:58.767Z","logger":"scheduler",
 "msg":"Workload requires preemption, but there are no candidate workloads allowed for preemption",
 "schedulingCycle":6753,
 "workload":{"name":"job-low-priority-gang-44684","namespace":"cohort-preemption-demo"},
 "clusterQueue":{"name":"cq-low"},
 "preemption":{"reclaimWithinCohort":"LowerPriority",
               "borrowWithinCohort":{"policy":"Never"},
               "withinClusterQueue":"Never"}}
 // ↑ low-priority 自身没有可抢占的对象（cq-high 中的 high-priority > low-priority）
 // low-priority 进入 inadmissible 队列等待
```

---

### Step 4 — 等待 high-priority 完成，观察 low-priority 自动恢复（T=+80s）

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

**实际轮询输出：**
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

> high-priority 在 T+65s 完成，Kueue 立刻让 low-priority 以 **6 pods** 恢复运行（重新借用 cq-high 的 3 CPU）。

**Kubernetes Events — high-priority 完成 + low-priority 恢复：**

```
Normal   Completed         job/high-priority-gang
  Job completed

Normal   FinishedWorkload  job/high-priority-gang
  Workload 'cohort-preemption-demo/job-high-priority-gang-e2828' is declared finished

Normal   QuotaReserved     workload/job-low-priority-gang-44684
  Quota reserved in ClusterQueue cq-low, wait time since queued was 65s;
  Flavors considered: main: default-flavor(Fit;borrow=1)
  ↑ wait time=65s：low-priority 在 inadmissible 队列中等待了 65 秒
  ↑ borrow=1：再次借用 cq-high 的 3 CPU

Normal   Admitted          workload/job-low-priority-gang-44684
  Admitted by ClusterQueue cq-low, wait time since reservation was 0s

Normal   Resumed           job/low-priority-gang
  Job resumed
```

**Kueue log — high-priority 完成 → low-priority 恢复：**

```json
// [1] high-priority 完成，FinishedWorkload 事件
{"ts":"2026-05-21T17:04:01.790Z","logger":"events",
 "msg":"Workload 'cohort-preemption-demo/job-high-priority-gang-e2828' is declared finished",
 "reason":"FinishedWorkload"}

// [2] workload-reconciler 检测 finished，释放 cq-high 的 3 CPU
{"ts":"2026-05-21T17:04:01.790Z","logger":"workload-reconciler",
 "msg":"Workload update event",
 "workload":{"name":"job-high-priority-gang-e2828"},
 "status":"finished","prevStatus":"admitted","clusterQueue":"cq-high"}

// [3] inadmissible_workload_requeue_worker 将 low-priority 移回调度队列
{"ts":"2026-05-21T17:04:02.792Z","logger":"inadmissible_workload_requeue_worker",
 "msg":"Attempting to move workloads","rootCohort":"preemption-cohort"}
{"ts":"2026-05-21T17:04:02.792Z","logger":"inadmissible_workload_requeue_worker",
 "msg":"Moved inadmissible workloads in tree",
 "rootCohort":"preemption-cohort","count":1}
 // ↑ rootCohort="preemption-cohort"：跨整个 cohort 树扫描等待中的 workload

// [4] Scheduling cycle #6755：low-priority 重新以 6 pods admit（借用 cq-high 3 CPU）
{"ts":"2026-05-21T17:04:02.810Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":6755,
 "workload":{"name":"job-low-priority-gang-44684"},
 "clusterQueue":{"name":"cq-low"},
 "parentCohort":{"name":"preemption-cohort"},
 "assignments":[{"name":"main",
   "resourceUsage":{"cpu":"6","memory":"1536Mi"},
   "count":6}]}
 // ↑ count=6, resourceUsage=6 CPU：再次借用 cq-high 的 3 CPU 运行
```

---

### Step 5 — 最终状态

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

> low-priority 恢复后是**全新的 6 个 pod**（pod 名称后缀不同），cq-low 再次借用 3 CPU。

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

## 实际时间线（本次真实运行）

| 绝对时间 (UTC) | 相对 | 事件 |
|---|---|---|
| 17:02:38 | T+0s | `low-priority-gang` 提交，Kueue 创建 Workload |
| 17:02:38 | T+0s | Scheduler：admitted（count=6，cq-low USED=6，BORROWED=3） |
| 17:02:38 | T+0s | 6 pods Running（含借用 cq-high 3 CPU） |
| 17:02:58 | T+20s | `high-priority-gang` 提交 |
| 17:02:58 | T+20s | Cycle #6752：high-priority assumed，low-priority FailedAfterNomination |
| 17:02:58 | T+20s | `low-priority-gang` suspended，6 pods Terminating |
| 17:02:58 | T+20s | `high-priority-gang` admitted（count=3，cq-high USED=3，BORROWED=0） |
| 17:02:58 | T+20s | low-priority 进入 inadmissible 队列（需要 6 CPU，只有 3 可用） |
| 17:04:01 | T+83s | `high-priority-gang` 完成（sleep 60s） |
| 17:04:02 | T+84s | inadmissible_requeue_worker 将 low-priority 移回调度队列（cohort 级别扫描） |
| 17:04:02 | T+84s | Cycle #6755：low-priority 重新 admitted（count=6，再次借用 3 CPU，wait=65s） |
| 17:04:02 | T+84s | 6 个新 pods Running |

---

## 内部机制详解

### reclaimWithinCohort 触发条件（核心）

```
Kueue 触发跨 CQ 抢占（reclaimWithinCohort: LowerPriority）的完整条件：

  ① 有待调度的 workload W（high-priority-gang）在 cq-high
  ② W 能适配在 cq-high 的 nominalQuota 内（3 pods ≤ 3 CPU）
  ③ cq-high 的 nominalQuota 被 cohort 内其他 CQ 的 workload 借走
     → cq-low 的 low-priority-gang 借了 cq-high 的 3 CPU
  ④ 借用者（low-priority-gang）的优先级低于 W（100 < 1000）

满足所有条件 → Kueue 驱逐 low-priority-gang，为 W 回收 cq-high 的配额
```

### 与基础抢占的核心区别

```
基础抢占（withinClusterQueue）：
  同一 CQ 内，高优先级 job 直接挤走低优先级 job
  cq-A { high-job, low-job } → high 挤 low

跨 CQ 抢占（reclaimWithinCohort）：
  cq-high { high-job 待调度 } + cq-low { low-job 借用 cq-high 的资源 }
  → cq-high 回收被 cq-low 借走的资源
  
  关键点：
  ① 被抢占的 job 在不同的 CQ 中（cq-low）
  ② 被抢占的原因是"占用了借来的资源"，而非"在同队列内竞争"
  ③ 抢占路径在 event 中明确标出：
     preemptor path: /preemption-cohort/cq-high
     preemptee path: /preemption-cohort/cq-low
```

### low-priority 等待期间为何无法调度

```
被抢占后，low-priority-gang 需要 6 CPU（gang job，all-or-nothing）：
  - cq-low 有 3 CPU（nominalQuota）
  - cq-high 的 3 CPU 被 high-priority-gang 占用（无法借用）
  - 3 + 0 = 3 CPU < 6 CPU 需求

→ gang 调度的原子性保证：宁可全部等待，也不会以 3 pods 运行
→ Kueue 的 Scheduler 将其标记为 inadmissible：
  "Workload requires preemption, but there are no candidate workloads allowed"
  （low-priority 无法抢占 high-priority）
```

---

## 清理

```bash
kubectl delete namespace cohort-preemption-demo
kubectl delete clusterqueue cq-high cq-low
kubectl delete priorityclass low-priority high-priority
```

---

## 附录：完整 YAML 文件

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
    reclaimWithinCohort: LowerPriority   # 可回收被低优先级借走的配额
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
