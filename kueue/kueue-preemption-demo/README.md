# Kueue Gang Scheduling + 优先级抢占演示

本文档完整演示 Kueue 对两个 gang job 执行优先级抢占的全过程，包含所有命令的**真实执行输出**和 **Kueue controller 内部日志**。

## 场景设计

```
ClusterQueue: demo-cq  ─── CPU quota: 4 核（故意与单个 gang job 请求完全匹配）
                                │
                                │  preemption.withinClusterQueue: LowerPriority
                                │  ↑ 核心配置：允许同队列内高优先级抢占低优先级
                                │
                        LocalQueue: demo-lq
                       ┌────────┴────────┐
              low-priority-gang      high-priority-gang
              parallelism=4          parallelism=4
              4×1CPU = 4核           4×1CPU = 4核
              PriorityClass=100      PriorityClass=1000
              sleep 300s             sleep 60s
```

**预期时间线：**

```
T+0s   │ low-priority-gang 提交 → 立即 Admitted（4 pods Running，占满 4 CPU）
T+23s  │ high-priority-gang 提交 → 触发抢占
T+23s  │ Kueue 决策：low-priority 被 Evicted，high-priority 被 Admitted
T+83s  │ high-priority-gang 完成（sleep 60s）
T+84s  │ Kueue 重新调度 low-priority-gang → 自动 Resumed（新建 4 pods）
```

---

## 前提条件

| 资源 | 要求 |
|---|---|
| kind 集群 | 已运行，`kubectl` 已配置 |
| Kueue controller | `kueue-system` namespace 中 Running |
| ResourceFlavor `default-flavor` | 已存在 |

---

## 文件清单

```
01-priority-classes.yaml   PriorityClass: low-priority(100) / high-priority(1000)
02-namespace.yaml          Namespace: preemption-demo
03-clusterqueue.yaml       ClusterQueue: demo-cq，4 CPU 配额，withinClusterQueue: LowerPriority
04-localqueue.yaml         LocalQueue: demo-lq
05-low-priority-job.yaml   Gang Job: parallelism=4, 4×1CPU, sleep 300s, low-priority
06-high-priority-job.yaml  Gang Job: parallelism=4, 4×1CPU, sleep 60s,  high-priority
```

---

## 完整执行步骤与真实输出

### Step 0 — 确认环境

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

### Step 1 — 部署基础资源

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

**验证 PriorityClass：**

```bash
kubectl get priorityclass low-priority high-priority
```

```
NAME            VALUE   GLOBAL-DEFAULT   AGE   PREEMPTIONPOLICY
low-priority    100     false            5s    PreemptLowerPriority
high-priority   1000    false            5s    PreemptLowerPriority
```

**验证 ClusterQueue preemption 配置（关键）：**

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

**验证 ClusterQueue 资源配额：**

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

**验证 LocalQueue：**

```bash
kubectl get localqueue -n preemption-demo
```

```
NAME      CLUSTERQUEUE   PENDING WORKLOADS   ADMITTED WORKLOADS
demo-lq   demo-cq        0                   0
```

---

### Step 2 — 提交 low-priority gang job（T=0s）

```bash
kubectl apply -f 05-low-priority-job.yaml
# 提交时间: 2026-05-21T15:49:58Z
```

```
job.batch/low-priority-gang created
```

**等待 8 秒后检查（busybox 镜像本地已缓存，pods 几乎立即启动）：**

```bash
kubectl get workloads -n preemption-demo
```

```
NAME                          QUEUE     RESERVED IN   ADMITTED   FINISHED   AGE
job-low-priority-gang-238f2   demo-lq   demo-cq       True                  13s
```

> `ADMITTED=True`、`RESERVED IN=demo-cq` 表示 Kueue 已为该 workload 预留配额并解除 suspend。

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

> 4 个 pod 全部 Running，这是 gang scheduling 的原子性保证：4 个 pod **同时**被 admit，不会只调度部分。

```bash
kubectl get job low-priority-gang -n preemption-demo -o wide
```

```
NAME                STATUS    COMPLETIONS   DURATION   AGE   CONTAINERS   IMAGES
low-priority-gang   Running   0/4           13s        13s   worker       busybox:1.36
```

**确认 ClusterQueue CPU 已满（4/4 核）：**

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

> `total: 4` CPU，`borrowed: 0`（未借用 cohort 配额）。队列已满，下一个 4 CPU 请求必然触发抢占。

**Kueue controller log — low-priority 准入过程：**

```json
// [1] Job 提交，Kueue 创建对应 Workload 对象
{"ts":"2026-05-21T15:49:58.554260Z","logger":"workload-reconciler",
 "msg":"Workload create event",
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "queue":"demo-lq","status":"pending"}

// [2] Scheduler 调度循环 #13 尝试调度
{"ts":"2026-05-21T15:49:58.554518Z","logger":"scheduler",
 "msg":"Attempting to schedule workload","schedulingCycle":13,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"}}

// [3] 配额预留成功（cache 中标记为 assumed）
{"ts":"2026-05-21T15:49:58.554557Z","logger":"scheduler",
 "msg":"Workload assumed in the cache","schedulingCycle":13,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"}}

// [4] Admit 完成，输出资源分配详情
{"ts":"2026-05-21T15:49:58.559768Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":13,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"},
 "assignments":[{"name":"main",
   "flavors":{"cpu":"default-flavor","memory":"default-flavor"},
   "resourceUsage":{"cpu":"4","memory":"1Gi"},
   "count":4}]}

// [5] 发送 QuotaReserved 事件（等待时间 1 秒）
{"ts":"2026-05-21T15:49:58.559794Z","logger":"events",
 "msg":"Quota reserved in ClusterQueue demo-cq, wait time since queued was 1s",
 "reason":"QuotaReserved"}

// [6] 发送 Admitted 事件
{"ts":"2026-05-21T15:49:58.559804Z","logger":"events",
 "msg":"Admitted by ClusterQueue demo-cq, wait time since reservation was 0s",
 "reason":"Admitted"}

// [7] Workload reconciler 通知 Job controller 解除 suspend
{"ts":"2026-05-21T15:49:58.559992Z","logger":"job",
 "msg":"Job admitted, unsuspending",
 "job":"preemption-demo/low-priority-gang"}
```

---

### Step 3 — 提交 high-priority gang job，触发抢占（T=+23s）

```bash
kubectl apply -f 06-high-priority-job.yaml
# 提交时间: 2026-05-21T15:50:21Z
```

```
job.batch/high-priority-gang created
```

**等待 8 秒后检查：**

```bash
kubectl get workloads -n preemption-demo
```

```
NAME                           QUEUE     RESERVED IN   ADMITTED   FINISHED   AGE
job-high-priority-gang-91d4a   demo-lq   demo-cq       True                  15s
job-low-priority-gang-238f2    demo-lq                 False                 38s
```

> - `high-priority`: `ADMITTED=True`，`RESERVED IN=demo-cq` ← **抢占成功，正在运行**
> - `low-priority`: `ADMITTED=False`，`RESERVED IN=（空）` ← **被抢占，等待重新调度**

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

> high-priority 4 pods Running，low-priority 4 pods Terminating——两批 pod 命名后缀完全不同，确认是两次独立的 gang admit。

```bash
kubectl get jobs -n preemption-demo \
  -o custom-columns="NAME:.metadata.name,SUSPEND:.spec.suspend,ACTIVE:.status.active,READY:.status.ready,SUCCEEDED:.status.succeeded"
```

```
NAME                 SUSPEND   ACTIVE   READY   SUCCEEDED
high-priority-gang   false     4        4       <none>
low-priority-gang    true      <none>   0       <none>
```

> `low-priority-gang` 的 `SUSPEND=true` 是 Kueue 写回 Job spec 的，Job controller 看到这个字段变化后会删除所有运行中的 pod。

**Kubernetes Events — 抢占决策的完整事件链：**

```
# ─── 抢占触发 ──────────────────────────────────────────────────────────────────

Warning  Pending   workload/job-high-priority-gang-91d4a
  couldn't assign flavors to pod set main: insufficient unused quota for cpu
  in flavor default-flavor, 4 more needed.
  Pending the preemption of 1 workload(s)
  ↑ 关键：Kueue 检测到需要抢占 1 个 workload 才能满足高优先级请求

Normal   EvictedDueToPreempted  workload/job-low-priority-gang-238f2
  Preempted to accommodate a workload
  (UID: 16739dd5-3342-4f5e-8bc5-20833d49b3ff, JobUID: 60a0290d-...)
  due to prioritization in the ClusterQueue;
  preemptor path: /demo-cq; preemptee path: /demo-cq
  ↑ low-priority workload 被驱逐，记录了 preemptor/preemptee 的 UID

Normal   Preempted   workload/job-low-priority-gang-238f2   （同上消息）
Normal   Stopped     job/low-priority-gang                  （同上消息）

# ─── low-priority Job 被暂停 ──────────────────────────────────────────────────

Normal   Suspended   job/low-priority-gang
  Job suspended
  ↑ Job spec.suspend 被置为 true，触发 Job controller 删除所有 pod

Normal   Killing     pod/low-priority-gang-b7qld   Stopping container worker
Normal   Killing     pod/low-priority-gang-m4mg7   Stopping container worker
Normal   Killing     pod/low-priority-gang-qm6pj   Stopping container worker
Normal   Killing     pod/low-priority-gang-wbdkq   Stopping container worker

# ─── high-priority 获得配额并启动 ────────────────────────────────────────────

Normal   QuotaReserved  workload/job-high-priority-gang-91d4a
  Quota reserved in ClusterQueue demo-cq, wait time since queued was 1s

Normal   Admitted    workload/job-high-priority-gang-91d4a
  Admitted by ClusterQueue demo-cq, wait time since reservation was 0s

Normal   Resumed     job/high-priority-gang
  Job resumed
  ↑ Job spec.suspend 被置为 false，Job controller 创建 4 个新 pod

Normal   Started     job/high-priority-gang
  Admitted by clusterQueue demo-cq
```

**Kueue controller log — 抢占决策核心日志：**

```json
// [1] high-priority workload 进入调度，发现配额不足，进入抢占评估
{"ts":"2026-05-21T15:50:21.974Z","logger":"events",
 "msg":"couldn't assign flavors to pod set main: insufficient unused quota for cpu
        in flavor default-flavor, 4 more needed",
 "type":"Warning","reason":"Pending",
 "object":{"name":"job-low-priority-gang-238f2",...}}
 // ↑ 注意：此消息出现在 low-priority workload 的事件上，
 //   因为 low-priority 此时已被移出 admitted 状态，正试图重新入队

// [2] 调度器发现 low-priority workload 需要重新调度，但此时 high-priority 已占满配额
{"ts":"2026-05-21T15:50:22.954Z","logger":"scheduler",
 "msg":"Workload requires preemption, but there are no candidate workloads allowed for preemption",
 "schedulingCycle":22,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"},
 "preemption":{"reclaimWithinCohort":"Never",
               "borrowWithinCohort":{"policy":"Never"},
               "withinClusterQueue":"LowerPriority"}}
 // ↑ low-priority 自身无法抢占任何人（它的优先级最低）

// [3] 进入 inadmissible 等待队列，等待资源释放
{"ts":"2026-05-21T15:50:22.954Z","logger":"scheduler",
 "msg":"Workload re-queued",
 "schedulingCycle":22,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"},
 "queue":{"name":"demo-lq","namespace":"preemption-demo"}}
```

---

### Step 4 — 等待 high-priority 完成，观察 low-priority 自动恢复（T=+83s）

可以用以下命令持续观察（每 3 秒刷新）：

```bash
watch -n 3 "
  kubectl get workloads -n preemption-demo && echo && \
  kubectl get pods -n preemption-demo && echo && \
  kubectl get jobs -n preemption-demo \
    -o custom-columns='NAME:.metadata.name,SUSPEND:.spec.suspend,ACTIVE:.status.active,SUCCEEDED:.status.succeeded'
"
```

或者使用轮询脚本等待完成信号：

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

**实际输出（真实运行观测）：**

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

> high-priority 在 T+83s 完成，Kueue 立刻重新调度 low-priority（`suspend=false, active=4`）。

**Kubernetes Events — high-priority 完成 + low-priority 恢复：**

```
Normal   Completed         job/high-priority-gang
  Job completed

Normal   FinishedWorkload  job/high-priority-gang
  Workload 'preemption-demo/job-high-priority-gang-91d4a' is declared finished

Normal   QuotaReserved     workload/job-low-priority-gang-238f2
  Quota reserved in ClusterQueue demo-cq, wait time since queued was 65s
  ↑ low-priority 在 inadmissible 队列中等待了 65 秒后重新获得配额

Normal   Admitted          workload/job-low-priority-gang-238f2
  Admitted by ClusterQueue demo-cq, wait time since reservation was 0s

Normal   Resumed           job/low-priority-gang
  Job resumed

Normal   Started           job/low-priority-gang
  Admitted by clusterQueue demo-cq
```

**Kueue controller log — high-priority 完成 → low-priority 恢复：**

```json
// [1] high-priority Job 所有 pod 完成，FinishedWorkload 事件
{"ts":"2026-05-21T15:51:25.424Z","logger":"events",
 "msg":"Workload 'preemption-demo/job-high-priority-gang-91d4a' is declared finished",
 "type":"Normal","reason":"FinishedWorkload"}

// [2] workload-reconciler 感知 finished 状态，更新 ClusterQueue 配额（释放 4 CPU）
{"ts":"2026-05-21T15:51:25.424Z","logger":"workload-reconciler",
 "msg":"Workload update event",
 "workload":{"name":"job-high-priority-gang-91d4a","namespace":"preemption-demo"},
 "status":"finished","prevStatus":"admitted","clusterQueue":"demo-cq"}

// [3] inadmissible_workload_requeue_worker 周期触发，将等待中的 low-priority 移回调度队列
{"ts":"2026-05-21T15:51:26.429Z","logger":"inadmissible_workload_requeue_worker",
 "msg":"Resetting the head of the ClusterQueue","clusterQueue":"demo-cq"}
{"ts":"2026-05-21T15:51:26.429Z","logger":"inadmissible_workload_requeue_worker",
 "msg":"Moved workloads","clusterqueue":"demo-cq","count":1}
 // ↑ count=1：1 个 workload（low-priority）被移回可调度队列

// [4] Scheduler 调度循环 #23 成功调度 low-priority（等待了 63.5 秒）
{"ts":"2026-05-21T15:51:26.430Z","logger":"scheduler",
 "msg":"Obtained heads","schedulingCycle":23,"headCount":1,
 "waitDuration":63.476080737}
 // ↑ waitDuration: low-priority 在队头等待的时长（秒）

{"ts":"2026-05-21T15:51:26.430Z","logger":"scheduler",
 "msg":"Workload assumed in the cache","schedulingCycle":23,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"}}

// [5] Admit 成功，输出资源分配
{"ts":"2026-05-21T15:51:26.446Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":23,
 "workload":{"name":"job-low-priority-gang-238f2","namespace":"preemption-demo"},
 "clusterQueue":{"name":"demo-cq"},
 "assignments":[{"name":"main",
   "flavors":{"cpu":"default-flavor","memory":"default-flavor"},
   "resourceUsage":{"cpu":"4","memory":"1Gi"},
   "count":4}]}

// [6] QuotaReserved（等待了 65 秒）
{"ts":"2026-05-21T15:51:26.446Z","logger":"events",
 "msg":"Quota reserved in ClusterQueue demo-cq, wait time since queued was 65s",
 "reason":"QuotaReserved"}

// [7] Admitted
{"ts":"2026-05-21T15:51:26.446Z","logger":"events",
 "msg":"Admitted by ClusterQueue demo-cq, wait time since reservation was 0s",
 "reason":"Admitted"}

// [8] Job controller 解除 suspend，重建 pod
{"ts":"2026-05-21T15:51:26.447Z","logger":"job",
 "msg":"Job admitted, unsuspending",
 "job":"preemption-demo/low-priority-gang"}
```

---

### Step 5 — 最终状态确认

```bash
kubectl get workloads -n preemption-demo
```

```
NAME                           QUEUE     RESERVED IN   ADMITTED   FINISHED   AGE
job-high-priority-gang-91d4a   demo-lq   demo-cq       True       True       4m9s
job-low-priority-gang-238f2    demo-lq   demo-cq       True                  4m32s
```

> `FINISHED=True`（high-priority）和 `ADMITTED=True`（low-priority）同时出现，场景完整收尾。

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

> 注意 pod 名称后缀：low-priority 恢复后是**全新的 4 个 pod**（`9z7zh, bx42n, kfccb, v5b9v`），与最初运行的 pod（`b7qld, m4mg7, qm6pj, wbdkq`）完全不同。这是 suspend→unsuspend 重建 pod 的正常行为。

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

## 实际时间线（本次真实运行）

| 绝对时间 (UTC) | 相对时间 | 事件 |
|---|---|---|
| 15:49:58 | T+0s | `low-priority-gang` 提交，Kueue 创建 Workload |
| 15:49:58 | T+0s | Scheduler cycle #13：Admitted，分配 4 CPU |
| 15:49:58 | T+0s | `low-priority-gang` unsuspended，4 pods 创建 |
| 15:49:59 | T+1s | 4 pods Running（镜像本地已缓存） |
| 15:50:21 | T+23s | `high-priority-gang` 提交 |
| 15:50:21 | T+23s | Kueue 抢占决策：evict `low-priority-gang`，admit `high-priority-gang` |
| 15:50:21 | T+23s | `low-priority-gang` suspended，4 pods Terminating |
| 15:50:21 | T+23s | `high-priority-gang` unsuspended，4 pods 创建 |
| 15:50:22 | T+24s | high-priority 4 pods Running |
| 15:51:25 | T+87s | `high-priority-gang` 完成（sleep 60s） |
| 15:51:25 | T+87s | workload-reconciler 检测到 finished，释放 4 CPU |
| 15:51:26 | T+88s | inadmissible_requeue_worker 将 `low-priority-gang` 移回调度队列 |
| 15:51:26 | T+88s | Scheduler cycle #23：`low-priority-gang` 重新 Admitted（等待了 65 秒） |
| 15:51:26 | T+88s | `low-priority-gang` unsuspended，4 个新 pods 创建 |
| 15:51:27 | T+89s | low-priority 4 pods Running |

---

## 内部机制详解

### Kueue 抢占决策流程

```
1. high-priority-gang 提交
   → Job controller 在 Kueue 管理下创建 Workload 对象（spec.suspend=true）

2. Scheduler 调度循环拾取 high-priority Workload
   → 检查 demo-cq 可用配额：cpu=0（全被 low-priority 占用）
   → 检查 withinClusterQueue=LowerPriority：
      high-priority(1000) > low-priority(100) ✓
      low-priority 释放后恰好满足 4 CPU 需求 ✓
   → 决策：发起抢占

3. Kueue 将 low-priority-gang Job 的 spec.suspend 置为 true
   → Job controller 删除所有运行中的 pod（4 个 Terminating）
   → Workload 状态：EvictedDueToPreempted → 进入 inadmissible 队列

4. Kueue 为 high-priority-gang 预留配额
   → Workload 状态：QuotaReserved → Admitted
   → Job spec.suspend 置为 false
   → Job controller 创建 4 个新 pod

5. high-priority pod 执行 sleep 60，完成
   → workload-reconciler 检测 Job Completed 状态，标记 Workload 为 finished
   → ClusterQueue 释放 4 CPU

6. inadmissible_workload_requeue_worker（后台 goroutine）
   → 周期性检查 inadmissible 队列
   → 将 low-priority Workload 移回 head-of-queue

7. Scheduler 下一个 cycle 成功调度 low-priority
   → 同 Step 2 流程：Admitted → unsuspend → 新建 4 pods
```

### Gang Scheduling 原子性保证

Kueue 将 `parallelism=4` 的 Job 视为单原子 workload：
- 要么 4 个 pod **同时**获得配额（gang admit），要么全部等待
- 避免部分 pod 运行、部分等待时的死锁（Deadlock-free scheduling）
- 抢占时也是整个 gang 同时被驱逐，不会只终止部分 pod

### suspend/unsuspend 机制

```
Kueue 不直接管理 pod 的生命周期，而是通过 Job.spec.suspend 字段与 Job controller 协作：

  admit   → Kueue 写 spec.suspend=false → Job controller 创建 pod
  preempt → Kueue 写 spec.suspend=true  → Job controller 删除所有 pod

这个设计使 Kueue 可以支持任何实现了 suspend/resume 语义的 Job 类型
（batch/v1 Job、JobSet、PyTorchJob、RayJob 等）。
```

---

## 清理

```bash
kubectl delete namespace preemption-demo
kubectl delete clusterqueue demo-cq
kubectl delete priorityclass low-priority high-priority
```

验证：
```bash
kubectl get ns preemption-demo 2>&1          # Error from server (NotFound)
kubectl get clusterqueue demo-cq 2>&1        # Error from server (NotFound)
kubectl get priorityclass low-priority 2>&1  # Error from server (NotFound)
```

---

## 附录：完整 YAML 文件

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
    withinClusterQueue: LowerPriority   # 允许高优先级抢占同队列中低优先级的 workload
    reclaimWithinCohort: Never
    borrowWithinCohort:
      policy: Never
  resourceGroups:
    - coveredResources: ["cpu", "memory"]
      flavors:
        - name: default-flavor
          resources:
            - name: cpu
              nominalQuota: "4"       # 故意设置 4 CPU，与 job 请求刚好匹配
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
    kueue.x-k8s.io/queue-name: demo-lq   # 告诉 Kueue 用哪个 LocalQueue
spec:
  parallelism: 4          # gang: 4 个 pod 必须同时被 admit
  completions: 4
  suspend: true           # Kueue 要求 job 以 suspend=true 提交
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
    kueue.x-k8s.io/queue-name: demo-lq   # 告诉 Kueue 用哪个 LocalQueue
spec:
  parallelism: 4          # gang: 4 个 pod 必须同时被 admit
  completions: 4
  suspend: true           # Kueue 要求 job 以 suspend=true 提交
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
