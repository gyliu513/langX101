# MultiKueue 最小化 Demo

> English: [README.md](README.md) · 分步操作手册：[WALKTHROUGH.zh-CN.md](WALKTHROUGH.zh-CN.md)

用 **kind + Kueue + JobSet + KubeRay** 四个组件，在本地搭出一套跨 3 个 Kubernetes 集群的
MultiKueue 环境，并跑通 **batch/Job、JobSet、RayJob** 三种工作负载的跨集群分发。

**不需要 OCM、Karmada、ArgoCD 或任何多集群管理平台。** MultiKueue 本身就是完整的多集群
调度方案，集群之间的连接就是一份 kubeconfig。

---

## 1. 组件清单

装在**每一个**集群上（manager 和 worker 都装）：

| 组件 | 版本 | 作用 | 是否必需 |
|---|---|---|---|
| kind | v0.31.0 | 创建本地 k8s 集群 | 必需 |
| Kubernetes | v1.35.0 | 节点镜像 | 必需（≥ 1.32） |
| **Kueue** | v0.19.1 | 队列 / 配额 / MultiKueue 调度 | **必需** |
| JobSet | v0.12.0 | JobSet 工作负载类型 | 只跑 batch/Job 时可省 |
| KubeRay | v1.6.2 | RayJob / RayCluster 工作负载类型 | 只跑 batch/Job 时可省 |

版本不是随便选的：Kueue v0.19.1 的 `go.mod` 里锁定的就是 jobset v0.12.0 和 kuberay v1.6.2，
这三个版本是上游 e2e 验证过能配合工作的组合。

`k8s ≥ 1.32` 这个下限来自 `JobManagedBy` 特性门控 —— MultiKueue 靠给 Job 打
`spec.managedBy` 来让 manager 上的原生 Job 控制器"别插手"，1.32 起该门控默认开启。

---

## 2. 架构图

```
┌────────────────────────────────────────────────────────────────────────────┐
│  MANAGER 集群   (kind: mk-manager)                    业务 Pod 数量：0      │
│                                                                             │
│    kubectl apply  Job / JobSet / RayJob   (标签: kueue.x-k8s.io/queue-name) │
│                              │                                              │
│                              ▼                                              │
│    ┌──────────────────────────────────────────────────────────────────┐    │
│    │  LocalQueue        user-queue                                     │    │
│    │       │                                                           │    │
│    │       ▼                                                           │    │
│    │  ClusterQueue      cluster-queue          配额: 10 CPU / 20Gi     │    │
│    │       │                                   (闸门①  —— 分发节流)    │    │
│    │       │  admissionChecksStrategy                                  │    │
│    │       ▼                                                           │    │
│    │  AdmissionCheck    multikueue-check                               │    │
│    │       │            controllerName: kueue.x-k8s.io/multikueue      │    │
│    │       │  parameters                                               │    │
│    │       ▼                                                           │    │
│    │  MultiKueueConfig  multikueue-config                              │    │
│    │       │            clusters: [ mk-worker1, mk-worker2 ]           │    │
│    │       ├───────────────────────────┬───────────────────────────┐   │    │
│    │       ▼                           ▼                           │   │    │
│    │  MultiKueueCluster           MultiKueueCluster                │   │    │
│    │    mk-worker1                  mk-worker2                     │   │    │
│    │       │ kubeConfig                │ kubeConfig                 │   │    │
│    │       ▼ locationType: Secret      ▼                            │   │    │
│    │  Secret                       Secret                          │   │    │
│    │    mk-worker1-secret            mk-worker2-secret             │   │    │
│    └───────┼───────────────────────────┼───────────────────────────────┘    │
└────────────┼───────────────────────────┼────────────────────────────────────┘
             │                           │
             │  ServiceAccount token     │  ServiceAccount token
             │  https://172.19.0.3:6443  │  https://172.19.0.4:6443
             │  (docker "kind" 网络内)    │
             ▼                           ▼
┌───────────────────────────────┐ ┌───────────────────────────────┐
│ WORKER 集群      mk-worker1   │ │ WORKER 集群      mk-worker2   │
│                               │ │                               │
│  LocalQueue    user-queue     │ │  LocalQueue    user-queue     │ ← 名字必须
│       │                       │ │       │                       │   和 manager
│       ▼                       │ │       ▼                       │   完全一致
│  ClusterQueue  cluster-queue  │ │  ClusterQueue  cluster-queue  │
│       配额: 2 CPU / 4Gi       │ │       配额: 2 CPU / 4Gi       │ ← 闸门②
│       (真正的准入决策)         │ │       (真正的准入决策)         │   物理容量
│                               │ │                               │
│  ▶▶ Pod 真正在这里运行         │ │  ▶▶ Pod 真正在这里运行         │
└───────────────────────────────┘ └───────────────────────────────┘
```

### 三条必须记住的规则

1. **worker 上的 namespace 和 LocalQueue 名字必须和 manager 完全一致。**
   MultiKueue 把 Workload 原样复制到 worker，找不到同名 LocalQueue 就卡住。

2. **`integrations.frameworks` 必须和 worker 上实际装的 operator 一致。**
   manager 会为每个启用的框架在 worker 上建 watch，缺 CRD 就整个连接失败。这是本 demo
   踩到的第一个坑，见 [WALKTHROUGH 排错](WALKTHROUGH.zh-CN.md#坑1-jobset-crd-缺失导致连接失败)。

3. **manager 上永远不会有业务 Pod。** 这是验证 MultiKueue 是否真的生效的最直接标志。

「两边都 admit 了为什么不会跑两遍」「Workload 到底是什么」这类问题见 [§8 FAQ](#8-faq)。

---

## 3. 工作流程图

```
  用户                 MANAGER 集群                   WORKER w1        WORKER w2
   │                       │                            │                │
   │ ① kubectl apply job   │                            │                │
   │   (带 queue-name 标签) │                            │                │
   ├──────────────────────>│                            │                │
   │                       │                            │                │
   │            ┌──────────┴──────────┐                 │                │
   │            │ ② Kueue webhook 拦截 │                 │                │
   │            │   suspend = true    │                 │                │
   │            │   managedBy =       │                 │                │
   │            │   .../multikueue    │                 │                │
   │            └──────────┬──────────┘                 │                │
   │                       │  原生 Job 控制器发现        │                │
   │                       │  managedBy 不是自己         │                │
   │                       │  → 完全不碰                 │                │
   │                       │                            │                │
   │            ┌──────────┴──────────┐                 │                │
   │            │ ③ 创建 Workload      │                 │                │
   │            │   闸门①: manager     │                 │                │
   │            │   ClusterQueue 配额  │                 │                │
   │            │   → QuotaReserved   │                 │                │
   │            └──────────┬──────────┘                 │                │
   │                       │                            │                │
   │            ┌──────────┴──────────┐                 │                │
   │            │ ④ AdmissionCheck    │                 │                │
   │            │   触发 dispatcher    │                 │                │
   │            │   AllAtOnce → 两个都提名               │                │
   │            │ status.nominated    │                 │                │
   │            │   ClusterNames      │                 │                │
   │            └──────────┬──────────┘                 │                │
   │                       │                            │                │
   │                       │ ⑤ 在候选 worker 上各建一份远程 Workload      │
   │                       ├───────────────────────────>│                │
   │                       ├────────────────────────────────────────────>│
   │                       │                            │                │
   │                       │        ⑥ 闸门②: worker ClusterQueue 配额     │
   │                       │           w1 先 admit      │                │
   │                       │<───────────────────────────┤                │
   │                       │                            │                │
   │            ┌──────────┴──────────┐                 │                │
   │            │ ⑦ w1 胜出:           │                 │                │
   │            │  • 删掉 w2 上的副本  ─┼─────────────────┼───────────────>│ ✗
   │            │  • status.cluster   │                 │                │
   │            │    Name = w1        │                 │                │
   │            │    (从此不可变)      │                 │                │
   │            └──────────┬──────────┘                 │                │
   │                       │                            │                │
   │                       │ ⑧ 在 w1 上创建真正的 Job    │                │
   │                       │   打 prebuilt-workload-name 标签关联         │
   │                       ├───────────────────────────>│                │
   │                       │                            │                │
   │                       │           ⑨ w1 上的 Job 控制器 unsuspend     │
   │                       │              → Pod 在这里跑 ◀◀              │
   │                       │                            │                │
   │                       │ ⑩ 持续状态同步              │                │
   │                       │<══════════════════════════>│                │
   │                       │                            │                │
   │ kubectl get job       │                            │                │
   │<──────────────────────┤  看到的是 w1 上的真实执行结果                 │
   │                       │                            │                │
   │                       │ ⑪ Workload Finished → 最后一次同步，          │
   │                       │    然后删除 w1 上的远程对象                   │
   │                       ├───────────────────────────>│ ✗              │
```

### ⑤～⑦ 详解 —— 为什么只有一个 worker 会真正跑

第 ⑤ 步会让人立刻产生一个疑问：*既然 Workload 被复制到了 w1 和 w2 **两边**，为什么不会跑两遍？*
答案是：**被复制过去的那个东西，根本跑不起来任何东西。**

#### ⑤ manager 复制的是 Workload，不是 Job

`Workload` 只是一条排队记录 —— 一次配额申请。Kubernetes 里没有任何控制器会根据 Workload 去创建
Pod。Pod 之所以存在，只可能是因为有一个 **Job / JobSet / RayJob** 对象，并且它的控制器把它
unsuspend 了。

第 ⑤ 步 manager 在 w1 和 w2 上创建的**只有 Workload 副本**，两个 worker 上都还没有 Job。所以
根本不存在"可能跑两遍"的东西：这两份副本是两次互相竞争的**配额投标**，而不是两个正在运行的任务。
真正的 Job 只会被创建一次，在第 ⑧ 步，也就是竞争已经分出胜负之后。

所以重复执行是**结构上不可能**，而不是"概率很小"—— 它不依赖于谁抢得够不够快。

#### ⑥ 每个 worker 各自独立 admit，彼此完全不知情

每个 worker 上跑的都是原生、未经改造的 Kueue。它的调度器看到本地 ClusterQueue 里来了一个新
Workload，本地配额够就 admit —— 和单集群 Kueue 走的是完全相同的代码路径。**worker 不知道
manager 的存在，不知道另一个 worker 的存在，也不知道自己正在参加一场竞争。** worker 之间没有任何
协调、没有锁、没有共识协议。

因此"w1 先 admit"的含义仅仅是：w1 的调度器碰巧比 w2 先把自己那份副本置为 `Admitted=True`。本
demo 里两个 worker 都是空闲的、配额也完全相同，所以谁赢纯属偶然 —— 重跑一次很可能就变成 w2。

#### manager 是怎么知道 w1 赢了的？

**是 manager 主动去看 worker，worker 从不向 manager 汇报。** manager 为每个 worker 持有一个远程
client，用的是 `mk-workerN-secret` 这个 Secret 里存的 kubeconfig（由 `scripts/4-connect.sh`
创建）；MultiKueue 的 AdmissionCheck 控制器**通过这条连接 watch 远程的 Workload 副本**。

方向是这里的关键。没有任何东西从 worker 推给 manager，所以 worker 不需要装 agent、不需要注册、
甚至不需要意识到自己身处一个联邦里 —— 这正是"一个 kubeconfig 就够，不需要任何多集群管理平台"
能够成立的原因。

当这个 watch 观测到某份远程副本带上了 `Admitted=True`，manager 就判定该副本所在的集群胜出。

#### ⑦ 胜者只会被锁定一次

确认 w1 admit 之后，manager 对自己**本地**那份 Workload 以及落败方做三件事：

1. 写入 `status.clusterName: mk-worker1` —— **这个字段一旦设置就不可变**；
2. 把 `multikueue-check` 这个 AdmissionCheck 置为 `Ready`；
3. **删除 w2 上的那份 Workload 副本**，从而释放 w2 已经临时占住的配额，让别的 Workload 能用。

第 (1) 条的不可变性就是这场竞争之所以安全的原因。如果两个 worker 在 manager reconcile 之前就都
admit 了（完全可能发生），manager 依然只会选**一个** —— watch 最先报上来的那个；第二次观测想去写
一个已经被写过的字段，会被直接丢弃。不存在"同时有两个胜者"的时间窗口。

到这时才轮到第 ⑧ 步：只在 w1 上创建真正的 Job，并打上
`kueue.x-k8s.io/prebuilt-workload-name` 标签指向那份已经被 admit 的副本 —— 这样 w1 的 Kueue 会
把这个 Job 绑定到已有的 admission 上，而不是再新建一个 Workload 重新排一遍队。

这是和单集群 Kueue 最大的差别。单集群里 Job **已经在本集群**，admit 之后 Kueue 把
`suspend` 翻成 `false`，本地 Job 控制器就开始建 Pod。MultiKueue 里 worker 上 admit 的是
**Workload 副本**，当时还没有 Job，所以 Job 控制器无事可做。真正的 Job 只在 `clusterName`
锁死之后、由 manager 创建到**一个** worker 上。

即使两边几乎同时 admit，时间线也是：

```
T1  w1 Workload Admitted=True     ← 只占配额，无 Job，无 Pod
T2  w2 Workload Admitted=True     ← 只占配额，无 Job，无 Pod
T3  manager 看到先报到的那个，写下 clusterName（不可变）
T4  删除落败方的 Workload 副本
T5  只在胜者上 create Job → 那边的 Job 控制器这时才建 Pod
```

T1～T4 期间两个 worker 上都没有 Job，不存在"两个 Job 控制器同时建 Pod"的窗口。

> **注意：**"复制给所有候选、谁先 admit 谁赢"这套行为是 **AllAtOnce** 分发器特有的，本 demo 在
> `manifests/kueue-config.yaml` 里配置的就是它。而 `Incremental` 分发器则是一次只提名一部分集群，
> 再按定时器逐步扩大范围 —— 产生的无用远程对象更少，但找到有空闲配额的集群更慢。

### 实际观测到的 Workload 状态

```yaml
status:
  clusterName: mk-worker1            # ← 最终跑在哪个集群（一旦设置就不可变）
  admissionChecks:
  - name: multikueue-check
    state: Ready
    message: The workload was admitted on "mk-worker1"
  conditions:
  - type: QuotaReserved              # ← 闸门①：manager 配额通过
    status: "True"
    message: Quota reserved in ClusterQueue cluster-queue
  - type: Admitted                   # ← 闸门②：worker 接了单
    status: "True"
  - type: PodsReady
    status: "True"
```

三个对象别混：

| 对象 | 是什么 | 会起 Pod 吗 |
|------|--------|-------------|
| **Job** | 用户提交的任务 | 会。但 manager 上那份因 `managedBy` 不执行；真正跑的那份只在胜者 worker 上由 manager 创建 |
| **Workload** | Kueue 的调度单元：配额申请 + 排队记录。单集群里就有，不是 MultiKueue 专属 | 不会。没有任何控制器根据 Workload 建 Pod |
| **`status.clusterName`** | manager 那份 Workload 上的结果字段 | 否。它只是"花落哪家"的不可变标记 |

远程 Workload 副本确实是中间过程（两边投标，分出胜负就删落败方）；但 Workload 的全部含义不只是"记下哪个 cluster 赢了"——选中之前它是配额申请单，`clusterName` 才是选中标记。

---

## 4. 配额是怎么执行的（Quota Enforcement）

这是 MultiKueue 最容易搞混的地方：**配额有两级，而且两级的含义完全不同。**

### 第一级：manager ClusterQueue —— 分发节流阀，不是执行闸门

manager 的配额决定"**同一时刻最多允许多少 Workload 进入分发流程**"。Workload 必须
先在 manager 拿到 `QuotaReserved`，MultiKueue 的 AdmissionCheck 才会被触发。

注意 manager 这一级配额是**虚账**：manager 上没有任何 Pod 真正消耗资源，它只是一个准入
节流阀。

### 第二级：worker ClusterQueue —— 真正的执行闸门

worker 的配额是**实账**，直接对应该集群的物理容量。Workload 副本要在 worker 的
ClusterQueue 里走一遍完整的标准 Kueue 准入（配额、ResourceFlavor 匹配、借用、抢占……）。
worker 拒绝，就没人跑。

### 两级配额怎么配

上游文档给的原则是：**manager 配额 ≈ 所有 worker 配额之和**。

| 配置 | 后果 |
|---|---|
| manager 配额 **远小于** worker 总和 | worker 集群闲置 —— manager 卡着不放行 |
| manager 配额 **远大于** worker 总和 | manager 分发出一大堆没人接得住的 Workload，白白建远程对象、白白监控 |
| manager 配额 ≈ worker 总和 | 合理 |

本 demo 故意**没有**遵守这条原则：manager 给了 10 CPU，两个 worker 各 2 CPU（总和 4 CPU）。
这是刻意的教学设置 —— 让 manager 不构成瓶颈，把配额压力全压到 worker 上，这样才能清楚看到
**是 worker 在真正做准入决策**。

### 实际观测

提交 3 个各要 2 CPU 的 Job：

```
MANAGER — Workloads
WORKLOAD               ADMITTED   DISPATCHED-TO
job-demo-job-1-a9067   <none>     <none>          ← 两个 worker 都满了，等着
job-demo-job-2-dd6ff   True       mk-worker2
job-demo-job-3-53d6e   True       mk-worker1

WORKER mk-worker1: cluster-queue   PENDING 1   ADMITTED 1
WORKER mk-worker2: cluster-queue   PENDING 1   ADMITTED 1
```

读法：manager 的 10 CPU 配额足够 3 个 Job 全部 `QuotaReserved`，所以 3 份副本都被分发到了
两个 worker（`PENDING 1` 就是那个没抢到的副本在排队）。但 worker 各只有 2 CPU，各自只能
admit 一个。第三个 Job 就一直挂着 —— **决定权在 worker，不在 manager**。

### 相关的进阶特性

- `MultiKueueManagerQuotaAutomation`（v0.18 引入，alpha，默认关闭）：让 manager 自动从
  worker 汇总配额，省掉手工对齐两级配额的麻烦。
- worker 上的 `ResourceFlavor` 名字要和 manager 对得上，否则 Workload 复制过去会因为
  找不到 flavor 而无法准入。本 demo 两边都叫 `default-flavor`。

---

## 5. 分发策略（Dispatch Strategy）

MultiKueue 决定"把 Workload 发给哪些 worker"的逻辑叫 **dispatcher**，在 Kueue 配置的
`multiKueue.dispatcherName` 字段里配。Kueue v0.13 起提供该机制。

| 策略 | 名称 | 行为 |
|---|---|---|
| **AllAtOnce**（默认） | `kueue.x-k8s.io/multikueue-dispatcher-all-at-once` | 一次性提名 MultiKueueConfig 里**所有** worker，每个都建一份远程 Workload，**谁先 admit 谁赢**，其余副本删掉 |
| **Incremental** | `kueue.x-k8s.io/multikueue-dispatcher-incremental` | 分批提名，每批 `stepSize` 个（默认 3）。若 5 分钟内无人接，再放下一批，直到被接或全部提名完 |
| **自定义** | 任意控制器名 | Kueue 只负责管远程副本，由你的控制器决定选哪些集群 |

### 本 demo 用的策略

显式配置为 **AllAtOnce**，写在 `manifests/kueue-config.yaml`：

```yaml
multiKueue:
  dispatcherName: kueue.x-k8s.io/multikueue-dispatcher-all-at-once
  # 仅 incremental 策略生效：
  # incrementalDispatcherConfig:
  #   stepSize: 1
  workerLostTimeout: 15m
  gcInterval: 1m
```

只有 2 个 worker 时 AllAtOnce 和 Incremental（默认 stepSize=3）行为一致，写出来是为了让这个
旋钮可见、可改。

### 怎么选

- **AllAtOnce**：启动最快（所有集群同时竞争），代价是瞬时会在 N 个集群上各建一份远程对象。
  集群数少（个位数）时用它。
- **Incremental**：集群规模大时更温和，避免一次性在几十个集群上建对象。而且从 v0.19 起
  `MultiKueueIncrementalDispatcherRespectConfigOrder` 门控（beta，默认开启）让提名顺序
  严格按 `MultiKueueConfig.spec.clusters` 的列表顺序走 —— **这等于把 clusters 列表变成了
  优先级列表**，可以实现"优先本地集群，本地满了再溢出到云上"这类策略。

### 观测分发过程

```bash
# 正在被提名、还没定下来的候选集群
kubectl --context kind-mk-manager -n default get workloads \
  -o custom-columns='WL:.metadata.name,NOMINATED:.status.nominatedClusterNames'

# 最终花落谁家（一旦设置即不可变，nominatedClusterNames 同时被清空）
kubectl --context kind-mk-manager -n default get workloads \
  -o custom-columns='WL:.metadata.name,WINNER:.status.clusterName'
```

---

## 6. 目录结构

```
multikueue-minimal-demo/
├── README.md                       # 架构与原理（英文）
├── README.zh-CN.md                 # 本文件：架构与原理（中文）
├── WALKTHROUGH.md                  # 分步操作 + 每条命令的真实输出（英文）
├── WALKTHROUGH.zh-CN.md            # 分步操作 + 每条命令的真实输出（中文）
├── manifests/
│   ├── kueue-config.yaml           # Kueue 配置：集成列表 + 分发策略
│   ├── worker-queues.yaml          # worker 侧队列（每个 worker 都要）
│   ├── worker-multikueue-rbac.yaml # worker 侧 SA/RBAC，manager 用它来操作 worker
│   └── manager-multikueue.yaml     # manager 侧队列 + MultiKueue 接线
├── examples/
│   ├── jobs.yaml                   # 示例1：3 个 batch/v1 Job
│   ├── jobset.yaml                 # 示例2：JobSet
│   └── rayjob.yaml                 # 示例3：RayJob
└── scripts/
    ├── common.sh                   # 版本号、集群名、公共函数
    ├── 0-create-clusters.sh        # 建 3 个 kind 集群
    ├── 1-install-frameworks.sh     # 装 JobSet + KubeRay（必须在 Kueue 之前）
    ├── 2-install-kueue.sh          # 装 Kueue + 应用配置
    ├── 3-setup-workers.sh          # worker 队列
    ├── 4-connect.sh                # 生成 kubeconfig 并存为 manager 上的 Secret
    ├── 5-setup-manager.sh          # manager MultiKueue 接线
    ├── run-demo-job.sh             # 示例1
    ├── run-demo-jobset.sh          # 示例2
    ├── run-demo-rayjob.sh          # 示例3
    ├── clean-workloads.sh          # 清空所有 demo 负载
    ├── ctx.sh                      # 在 3 个集群之间切换 kubectl context
    ├── status.sh                   # 查看"提交在哪 vs 跑在哪"
    ├── up.sh                       # 0~5 一把梭
    └── down.sh                     # 删集群
```

---

## 7. 快速开始

```bash
cd multikueue-minimal-demo

./scripts/up.sh                  # 建环境（约 8~12 分钟）

./scripts/run-demo-job.sh        # 示例1：batch/Job
./scripts/run-demo-jobset.sh     # 示例2：JobSet
./scripts/run-demo-rayjob.sh     # 示例3：RayJob

./scripts/status.sh              # 随时查看状态
./scripts/down.sh                # 清理
```

换 Kueue 版本（例如 v0.16.4，同样支持 MultiKueue 且已经是 v1beta2 API）：

```bash
KUEUE_VERSION=v0.16.4 JOBSET_VERSION=v0.10.1 KUBERAY_VERSION=1.5.1 ./scripts/up.sh
```

---

## 8. FAQ

### 两个 worker 都 admit 了，两边的 Job 控制器不就会同时建 Pod 吗？

不会。那是**单集群**路径：Job 已经在本集群里，admit 之后 Kueue unsuspend，本地 Job 控制器才建
Pod。

MultiKueue 把这条链拆开了：

```
单集群:   Job 已存在  →  Workload admit  →  unsuspend Job  →  建 Pod
MultiKueue: Workload 副本 admit（只占配额）→ 锁定 clusterName → manager 才在胜者上 create Job → 建 Pod
```

worker 上 admit 时还没有 Job，Job 控制器没有可 reconcile 的对象。两边同时 `Admitted=True`
只表示两边都临时占了一份配额，不是两边都开始跑任务。

### 为什么 manager 上不能跑这个 Job？

不是 manager 物理上跑不了，是 **MultiKueue 故意不让走这条队列的 Job 在 manager 上执行**。

提交到挂了 MultiKueue AdmissionCheck 的队列时，webhook 会改两个字段：

| 字段 | 效果 |
|------|------|
| `spec.suspend = true` | 先挂起，不建 Pod |
| `spec.managedBy = kueue.x-k8s.io/multikueue` | manager 上的原生 Job 控制器认为「这不是我的活」，永远不会 unsuspend |

原因有三条：

1. **避免跑两遍。** 用户 `kubectl apply` 的 Job 对象就在 manager 上。如果本地 Job 控制器也干活，manager 起一套 Pod，MultiKueue 又在 worker 上再创建一份，同一任务执行两次。
2. **manager 配额是虚账。** ClusterQueue 只决定同时允许多少任务进入分发，不对应真实机器容量。本 demo manager 给了 10 CPU，kind 节点并没有按 10 CPU 去跑业务 Pod。
3. **manager 是调度控制面。** 接单、占虚账、挑 worker、同步状态；算力在 worker 上。

如果 Job **不**走 MultiKueue 队列（没有那个 AdmissionCheck），它可以在 manager 上当普通单集群 Job 跑。拦住的是「跨集群分发」这条路径。

验证标准：manager 上 `kubectl get pods` 看不到业务 Pod，worker 上才看得到。这是 README 第 3 条规则。

### `managedBy` 是用来保证两个 worker 互斥的吗？

不是。分工是：

| 机制 | 保证什么 |
|------|----------|
| `managedBy` + `suspend` | **manager 本地**不执行 |
| 第 ⑤ 步只复制 Workload | 两边还没有能跑的 Job |
| `clusterName` 一旦写入就不可变 | 胜者只能有一个 |
| 删除落败方的 Workload | 另一边连投标都撤掉 |
| 第 ⑧ 步才创建 Job | 真正执行只发生一次、只在胜者上 |

两个 worker 互斥靠的是后四条，不是 `managedBy`。

### Workload 是不是专门用来标记哪个 cluster 被选中的中间对象？

一半对。

- **对 worker 副本来说：** 是中间过程。存在只为了向该集群投标配额，分出胜负就删落败方，任务跑完再删胜者那份。
- **对 Workload 整体来说：** 它是 Kueue 通用的调度单元（单集群里也有），用来申请配额、排队、admit、释放。
- **真正标记"跑在哪"的是** manager 那份 Workload 上的 `status.clusterName`，写上就不可变。

```
Job              = 用户提交的任务（最终会起 Pod）
Workload         = Kueue 为这个任务建的排队 / 配额对象
clusterName      = Workload 上"花落哪家"的结果字段
```

---

## 9. 什么时候才真的需要 OCM 之类的多集群平台

本 demo 证明了 MultiKueue 不依赖任何多集群管理平台。但下面这些场景，裸 MultiKueue 确实不够：

| 场景 | 裸 MultiKueue | 需要外部平台 |
|---|---|---|
| worker 在防火墙 / NAT 后，manager 拿不到可路由的 API server 地址 | ✗ 走不通（push 模型） | ✓ OCM 是 pull 模型 |
| 几十上百个集群的注册与凭证轮转 | ✗ 手工 SA + Secret，运维不可持续 | ✓ 自动注册与同步 |
| 需要基于集群标签/能力做动态放置 | ✗ MultiKueueConfig 是静态列表 | ✓ Placement 策略 |
| 几个集群、网络互通、手工可控 | ✓ 够用 | 不必要 |

中间路线是 Kueue v0.15 引入的 `MultiKueueClusterProfile`（alpha），通过标准的
[Cluster Inventory API](https://multicluster.sigs.k8s.io/) `ClusterProfile` 对象拿凭证 ——
厂商中立，OCM 能生成，也可以手工创建。
