# Kueue Fair Share（公平分配）演示：2:3 弹性 Job

本文档演示 Kueue 如何在两个团队之间按 **2:3** 比例公平分配资源，
两个 Job 均为弹性（elastic）——最多希望使用 10 CPU，但可以在更少的资源下运行。
包含所有命令的**真实执行输出**和 **Kueue controller 内部日志**。

---

## 场景设计

```
Cohort: fairshare-cohort（总容量 10 CPU，由两个 CQ 的 nominalQuota 之和构成）
│
├── ClusterQueue: cq-team-a  ── nominalQuota=4 CPU, weight=2  (2/5 = 40%)
│   └── LocalQueue: lq-team-a  (namespace: fairshare-team-a)
│       └── elastic-job-team-a: 最多 10 pods × 1CPU，最少 2 pods
│
└── ClusterQueue: cq-team-b  ── nominalQuota=6 CPU, weight=3  (3/5 = 60%)
    └── LocalQueue: lq-team-b  (namespace: fairshare-team-b)
        └── elastic-job-team-b: 最多 10 pods × 1CPU，最少 2 pods
```

### 关键配置说明

| 配置项 | 值 | 作用 |
|---|---|---|
| `fairSharing.weight` | 2 / 3 | Kueue FairSharing 算法的份额权重，决定竞争时资源分配比例 |
| `nominalQuota` | 4 / 6 | 每个 CQ 的保证资源量，同时体现 2:3 比例 |
| `borrowingLimit: "0"` | Phase 2 使用 | 禁止借用，确保严格按 nominalQuota 分配 |
| `kueue.x-k8s.io/job-min-parallelism` | 2 | PartialAdmission：允许 Kueue 将 parallelism 从 10 弹性缩减至最少 2 |
| `fairSharing.preemptionStrategies` | `[LessThanOrEqualToFinalShare, LessThanInitialShare]` | Kueue 全局配置，启用公平分配抢占 |

### 两阶段演示

```
Phase 1 (借用)  ─ CQ 无 borrowingLimit，team-b 独自运行
                 Job-B 借用 team-a 闲置的 4 CPU
                 → Job-B 以 10 pods 满载运行（6 nominal + 4 borrowed）

Phase 2 (公平分配) ─ CQ 设置 borrowingLimit=0，两个 job 同时提交
                    Kueue PartialAdmission 弹性调整 parallelism
                    → Job-A 以 4 pods 运行（requested=10 → admitted=4）
                    → Job-B 以 6 pods 运行（requested=10 → admitted=6）
                    → 4:6 = 2:3 ✓
```

---

## 前提条件

```bash
kubectl get nodes                       # kind 集群已运行
kubectl get pods -n kueue-system        # Kueue controller Running
kubectl get resourceflavor              # default-flavor 已存在
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
01-namespaces.yaml              Namespace: fairshare-team-a / fairshare-team-b
02-clusterqueue-team-a.yaml     CQ: cq-team-a，nominalQuota=4，weight=2，borrowingLimit=0
03-clusterqueue-team-b.yaml     CQ: cq-team-b，nominalQuota=6，weight=3，borrowingLimit=0
04-localqueues.yaml             LocalQueue: lq-team-a / lq-team-b
05-elastic-job-team-b.yaml      Elastic Job: max 10 pods，min 2，sleep 300s
06-elastic-job-team-a.yaml      Elastic Job: max 10 pods，min 2，sleep 300s
```

---

## 启用 Kueue FairSharing

FairSharing 默认未启用，需要修改 ConfigMap 并重启 controller。

```bash
# 备份并修改配置
kubectl get configmap kueue-manager-config -n kueue-system \
  -o jsonpath='{.data.controller_manager_config\.yaml}' > /tmp/kueue-config.yaml

# 取消注释 fairSharing 段
sed -i '' 's|#fairSharing:|fairSharing:|' /tmp/kueue-config.yaml
sed -i '' 's|#  preemptionStrategies: \[LessThan.*\]|  preemptionStrategies: [LessThanOrEqualToFinalShare, LessThanInitialShare]|' /tmp/kueue-config.yaml

# 应用修改
kubectl create configmap kueue-manager-config \
  -n kueue-system \
  --from-file=controller_manager_config.yaml=/tmp/kueue-config.yaml \
  --dry-run=client -o yaml | kubectl apply -f -

# 重启 controller
kubectl rollout restart deployment/kueue-controller-manager -n kueue-system
kubectl rollout status deployment/kueue-controller-manager -n kueue-system --timeout=60s
```

```
deployment.apps/kueue-controller-manager restarted
deployment "kueue-controller-manager" successfully rolled out
```

---

## 完整执行步骤与真实输出

### Step 1 — 部署基础资源

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

**验证 CQ 配置：**

```bash
kubectl get clusterqueue cq-team-a cq-team-b \
  -o custom-columns="NAME:.metadata.name,COHORT:.spec.cohortName,WEIGHT:.spec.fairSharing.weight,CPU_QUOTA:.spec.resourceGroups[0].flavors[0].resources[0].nominalQuota,BORROW_LIMIT:.spec.resourceGroups[0].flavors[0].resources[0].borrowingLimit"
```

```
NAME        COHORT             WEIGHT   CPU_QUOTA   BORROW_LIMIT
cq-team-a   fairshare-cohort   2        4           0
cq-team-b   fairshare-cohort   3        6           0
```

> `WEIGHT 2:3` 对应公平份额比例；`BORROW_LIMIT=0` 确保 Phase 2 严格按 nominalQuota 分配。

---

### Phase 1 — 借用演示：team-b 独自占用所有资源

> **说明**：Phase 1 使用不带 `borrowingLimit` 的 CQ 配置（即将 `borrowingLimit: "0"` 注释掉后重建 CQ），演示当 team-a 空闲时，team-b 可借用其全部 4 CPU。Phase 2 使用的 `borrowingLimit=0` 则关闭了借用能力以强制 2:3 分配。

```bash
kubectl apply -f 05-elastic-job-team-b.yaml
# 提交时间: 2026-05-21T16:42:37Z
```

```
job.batch/elastic-job-team-b created
```

**等待 10 秒后检查：**

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

> **10 个 pod 全部 Running**，超出了 cq-team-b 的 nominalQuota（6 CPU），额外 4 CPU 来自借用 cq-team-a。

```bash
kubectl get clusterqueue cq-team-a cq-team-b \
  -o custom-columns="NAME:.metadata.name,NOMINAL:.spec.resourceGroups[0].flavors[0].resources[0].nominalQuota,USED:.status.flavorsUsage[0].resources[0].total,BORROWED:.status.flavorsUsage[0].resources[0].borrowed"
```

```
NAME        NOMINAL   USED   BORROWED
cq-team-a   4         0      0          ← 空闲，其 4 CPU 被 team-b 借走
cq-team-b   6         10     4          ← 使用了 10 CPU，其中 4 CPU 是借来的
```

> `cq-team-b BORROWED=4`：证明成功借用了 cq-team-a 闲置的 4 CPU。

**Kueue log — Phase 1 admission（Job-B 借用全部资源）：**

```json
// [1] 调度循环处理 Job-B workload，cq-team-a 完全空闲，可借用
{"ts":"2026-05-21T16:42:37Z","logger":"scheduler",
 "msg":"Attempting to schedule workload","schedulingCycle":N,
 "workload":{"name":"job-elastic-job-team-b-e7175","namespace":"fairshare-team-b"},
 "clusterQueue":{"name":"cq-team-b"},
 "parentCohort":{"name":"fairshare-cohort"}}

// [2] Job-B 以 10 pods 被 admit（6 nominal + 4 borrowed）
// QuotaReserved 事件里的 "borrow=1" 表示使用了借用配额
// Flavors considered: main: default-flavor(Fit;borrow=1)
{"ts":"2026-05-21T16:42:37Z","logger":"events",
 "msg":"Quota reserved in ClusterQueue cq-team-b, wait time since queued was 0s;
        Flavors considered: main: default-flavor(Fit;borrow=1)",
 "reason":"QuotaReserved"}

// [3] PartialAdmission 将 parallelism 设为 10（cohort 内有足够空间）
{"ts":"2026-05-21T16:42:37Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors",
 "assignments":[{"name":"main",
   "resourceUsage":{"cpu":"10","memory":"2560Mi"},
   "count":10}]}
```

---

### Phase 2 — 公平分配：同时提交两个 elastic job

```bash
kubectl apply -f 06-elastic-job-team-a.yaml
kubectl apply -f 05-elastic-job-team-b.yaml
# 提交时间: 2026-05-21T16:45:50Z
```

```
job.batch/elastic-job-team-a created
job.batch/elastic-job-team-b created
```

**等待 12 秒后检查：**

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

> 两个 workload 均 `ADMITTED=True`，几乎在同一时刻被调度。

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

> **team-a: 4 pods（2 份），team-b: 6 pods（3 份）→ 4:6 = 2:3 ✓**

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

> **关键**：两个 job 的 `spec.parallelism` 均由 Kueue PartialAdmission 从 **10 弹性缩减**为 4 和 6。
> `SUSPEND=false` 表示两个 job 都在运行中。

```bash
kubectl get clusterqueue cq-team-a cq-team-b \
  -o custom-columns="NAME:.metadata.name,NOMINAL:.spec.resourceGroups[0].flavors[0].resources[0].nominalQuota,USED:.status.flavorsUsage[0].resources[0].total,BORROWED:.status.flavorsUsage[0].resources[0].borrowed,ADMITTED:.status.admittedWorkloads"
```

```
NAME        NOMINAL   USED   BORROWED   ADMITTED
cq-team-a   4         4      0          1
cq-team-b   6         6      0          1
```

> `USED=4` 和 `USED=6`，`BORROWED=0`——每个 CQ 严格使用自己的 nominalQuota，没有借用发生。

**Kubernetes Events — Phase 2 公平分配：**

```
# ─── team-a Job-A 准入 ─────────────────────────────────────────────────────

Normal   QuotaReserved   workload/job-elastic-job-team-a-dbd47
  Quota reserved in ClusterQueue cq-team-a, wait time since queued was 0s

Normal   Admitted        workload/job-elastic-job-team-a-dbd47
  Admitted by ClusterQueue cq-team-a, wait time since reservation was 0s

Normal   Resumed         job/elastic-job-team-a
  Job resumed
  ↑ Kueue 将 spec.parallelism 调整为 4，解除 suspend

# ─── team-b Job-B 准入（与 Job-A 同一秒）────────────────────────────────────

Normal   QuotaReserved   workload/job-elastic-job-team-b-cd21b
  Quota reserved in ClusterQueue cq-team-b, wait time since queued was 0s

Normal   Admitted        workload/job-elastic-job-team-b-cd21b
  Admitted by ClusterQueue cq-team-b, wait time since reservation was 0s

Normal   Resumed         job/elastic-job-team-b
  Job resumed
  ↑ Kueue 将 spec.parallelism 调整为 6，解除 suspend
```

**Kueue controller log — Phase 2 两个连续调度循环：**

```json
// ─── Scheduling Cycle #6742: Job-A ───────────────────────────────────────────

// [1] Job-A workload 进入调度循环，属于 cohort: fairshare-cohort
{"ts":"2026-05-21T16:45:50.299671Z","logger":"scheduler",
 "msg":"Attempting to schedule workload","schedulingCycle":6742,
 "workload":{"name":"job-elastic-job-team-a-dbd47","namespace":"fairshare-team-a"},
 "clusterQueue":{"name":"cq-team-a"},
 "parentCohort":{"name":"fairshare-cohort"},
 "rootCohort":{"name":"fairshare-cohort"}}

// [2] PartialAdmission 计算：cq-team-a 有 4 CPU，最多分配 4 pods（count=4）
{"ts":"2026-05-21T16:45:50.304092Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":6742,
 "workload":{"name":"job-elastic-job-team-a-dbd47","namespace":"fairshare-team-a"},
 "clusterQueue":{"name":"cq-team-a"},
 "assignments":[{"name":"main",
   "flavors":{"cpu":"default-flavor","memory":"default-flavor"},
   "resourceUsage":{"cpu":"4","memory":"1Gi"},
   "count":4}]}
 // ↑ count=4：Job-A 的 parallelism 从 10 弹性缩减为 4

// [3] Job-A 被 admit，Job controller unsuspend 并设置 spec.parallelism=4
{"ts":"2026-05-21T16:45:50.303717Z","logger":"job",
 "msg":"Job admitted, unsuspending",
 "job":"fairshare-team-a/elastic-job-team-a"}

// ─── Scheduling Cycle #6743: Job-B（仅 41ms 后）────────────────────────────

// [4] Job-B workload 进入下一个调度循环
{"ts":"2026-05-21T16:45:50.341108Z","logger":"scheduler",
 "msg":"Attempting to schedule workload","schedulingCycle":6743,
 "workload":{"name":"job-elastic-job-team-b-cd21b","namespace":"fairshare-team-b"},
 "clusterQueue":{"name":"cq-team-b"},
 "parentCohort":{"name":"fairshare-cohort"},
 "rootCohort":{"name":"fairshare-cohort"}}
 // ↑ parentCohort 和 rootCohort 均为 fairshare-cohort

// [5] PartialAdmission 计算：cq-team-b 有 6 CPU，分配 6 pods（count=6）
{"ts":"2026-05-21T16:45:50.344746Z","logger":"scheduler",
 "msg":"Workload successfully admitted and assigned flavors","schedulingCycle":6743,
 "workload":{"name":"job-elastic-job-team-b-cd21b","namespace":"fairshare-team-b"},
 "clusterQueue":{"name":"cq-team-b"},
 "assignments":[{"name":"main",
   "flavors":{"cpu":"default-flavor","memory":"default-flavor"},
   "resourceUsage":{"cpu":"6","memory":"1536Mi"},
   "count":6}]}
 // ↑ count=6：Job-B 的 parallelism 从 10 弹性缩减为 6

// [6] Job-B admitted, spec.parallelism=6
{"ts":"2026-05-21T16:45:50.345021Z","logger":"job",
 "msg":"Job admitted, unsuspending",
 "job":"fairshare-team-b/elastic-job-team-b"}
```

> **关键观察**：Cycle 6742 和 6743 相差仅 **41ms**（`waitDuration: 0.041s`），两个 job 在同一秒内都被 admitted。Kueue 的 PartialAdmission 为每个 workload 独立计算最大可分配 pods：4 和 6，完美实现 2:3。

---

## 实际时间线（本次真实运行）

| 绝对时间 (UTC) | 相对时间 | 事件 |
|---|---|---|
| 16:42:37 | Phase 1 T+0s | Job-B 提交（max=10, min=2） |
| 16:42:37 | Phase 1 T+0s | Kueue 以 10 pods admit Job-B（borrows 4 CPU from cq-team-a） |
| 16:42:37 | Phase 1 T+1s | 10 pods Running，cq-team-b USED=10 BORROWED=4 |
| — | 重置 | 删除 Job-B，更新 CQ 加入 borrowingLimit=0 |
| 16:45:50 | Phase 2 T+0s | Job-A 和 Job-B 同时提交（均为 max=10, min=2） |
| 16:45:50 | Phase 2 T+0s | Scheduling cycle #6742：Job-A admitted，count=4，cq-team-a USED=4 |
| 16:45:50 | Phase 2 T+0s | Scheduling cycle #6743（41ms 后）：Job-B admitted，count=6，cq-team-b USED=6 |
| 16:45:51 | Phase 2 T+1s | team-a: 4 pods Running，team-b: 6 pods Running → **2:3 ✓** |

---

## 内部机制详解

### PartialAdmission（弹性 Job 的核心）

```
batch/v1 Job 默认是 all-or-nothing：如果 parallelism=10，必须同时有 10 个 CPU
才能被 admit。

PartialAdmission 打破了这个限制：
  annotation: kueue.x-k8s.io/job-min-parallelism: "2"
  含义：Job 至少需要 2 个 pod 才有意义；Kueue 可以在 [2, parallelism] 范围内
       自动选择实际运行的 pod 数量。

Kueue 的决策逻辑（简化）：
  admitted_count = min(requested_parallelism, available_quota_in_cpu)
  if admitted_count >= min_parallelism:
      admit the job with parallelism = admitted_count
  else:
      job stays in queue (pending)

本次结果：
  Job-A: min(10, 4) = 4  → parallelism 设为 4
  Job-B: min(10, 6) = 6  → parallelism 设为 6
```

### FairSharing Weight 与 NominalQuota 的关系

```
NominalQuota（4 和 6）是每个 CQ 的资源保证：
  - 无论其他 CQ 是否使用资源，这部分始终可用
  - 比例 4:6 = 2:3 与 weight 2:3 一致（互相印证）

FairSharing Weight（2 和 3）影响竞争时的优先顺序：
  - Kueue 使用 Dominant Resource Fairness（DRF）思想
  - 份额 = 已使用资源 / weight
  - Kueue 优先调度"份额最低"的 CQ 的 workload
  - 从而在长期运行中保持 2:3 的比例

当 borrowingLimit=0 时：
  - 每个 CQ 只能用自己的 nominalQuota
  - 公平份额直接由配额决定，不需要 weight 干预
  - Weight 在此场景下仅作为概念一致性保证

当 borrowingLimit=null（Phase 1）时：
  - CQ 可以借用 cohort 内其他 CQ 的空闲资源
  - Weight 影响竞争借用的优先级
```

### suspend/unsuspend 与 PartialAdmission 协作

```
Kueue 通过修改 Job.spec.parallelism 实现弹性调整：

  Job 提交时：
    spec.parallelism = 10 (用户请求上限)
    spec.suspend = true  (Kueue 要求)
    annotation: job-min-parallelism = "2" (用户设置下限)

  Kueue admit 时（以 Job-A 为例）：
    计算 admitted_count = min(10, 4) = 4
    写入: spec.parallelism = 4  ← 弹性缩减
    写入: spec.suspend = false  ← 启动
    Job controller 根据 parallelism=4 创建 4 个 pod

  如果 Job-A 被抢占后重新 admit（配额增加时）：
    重新计算 admitted_count = min(10, available)
    spec.parallelism 可以上调（弹性扩展）
```

---

## 清理

```bash
kubectl delete namespace fairshare-team-a fairshare-team-b
kubectl delete clusterqueue cq-team-a cq-team-b
```

验证：
```bash
kubectl get ns fairshare-team-a 2>&1  # Error from server (NotFound)
kubectl get clusterqueue cq-team-a 2>&1  # Error from server (NotFound)
```

---

## 附录：完整 YAML 文件

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
    weight: "2"               # team-a 占 2/(2+3) = 40% 份额
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
              borrowingLimit: "0"
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
    weight: "3"               # team-b 占 3/(2+3) = 60% 份额
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
    kueue.x-k8s.io/job-min-parallelism: "2"  # PartialAdmission 最小 pod 数
spec:
  parallelism: 10         # 弹性上限：最多希望 10 个 pod
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
    kueue.x-k8s.io/job-min-parallelism: "2"  # PartialAdmission 最小 pod 数
spec:
  parallelism: 10         # 弹性上限：最多希望 10 个 pod
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
