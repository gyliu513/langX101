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

### 实际观测到的 Workload 状态

```yaml
status:
  clusterName: mk-worker2            # ← 最终跑在哪个集群（一旦设置就不可变）
  admissionChecks:
  - name: multikueue-check
    state: Ready
    message: The workload was admitted on "mk-worker2"
  conditions:
  - type: QuotaReserved              # ← 闸门①：manager 配额通过
    status: "True"
    message: Quota reserved in ClusterQueue cluster-queue
  - type: Admitted                   # ← 闸门②：worker 接了单
    status: "True"
  - type: PodsReady
    status: "True"
```

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

## 8. 什么时候才真的需要 OCM 之类的多集群平台

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
