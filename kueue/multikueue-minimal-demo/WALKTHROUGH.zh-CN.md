# MultiKueue Demo 分步操作手册

> English: [WALKTHROUGH.md](WALKTHROUGH.md) · 架构原理：[README.zh-CN.md](README.zh-CN.md)

本文档记录搭建全过程的**每一条命令和它的真实输出**（在 macOS / Apple Silicon / Docker
Desktop 上实际执行采集）。原理和架构见 [README.zh-CN.md](README.zh-CN.md)。

**目录**

- [第 0 步：安装前置工具](#第-0-步安装前置工具)
- [第 1 步：创建 3 个 kind 集群](#第-1-步创建-3-个-kind-集群)
- [集群上下文切换](#集群上下文切换context-switching)
- [第 2 步：安装 JobSet 和 KubeRay](#第-2-步安装-jobset-和-kuberay)
- [第 3 步：安装 Kueue 并启用 MultiKueue](#第-3-步安装-kueue-并启用-multikueue)
- [第 4 步：配置 worker 队列](#第-4-步配置-worker-队列)
- [第 5 步：打通 manager 到 worker 的连接](#第-5-步打通-manager-到-worker-的连接)
- [第 6 步：在 manager 上接线 MultiKueue](#第-6-步在-manager-上接线-multikueue)
- [测试 1：batch/v1 Job](#测试-1batchv1-job)
- [测试 2：JobSet](#测试-2jobset)
- [测试 3：RayJob](#测试-3rayjob)
- [排错手册](#排错手册)
- [清理](#清理)

---

## 第 0 步：安装前置工具

### 0.1 Docker

MultiKueue demo 需要同时跑 3 个 kind 集群，建议给 Docker 至少 **8GB 内存**（跑 RayJob 建议
12GB+）。macOS 上从 Docker Desktop → Settings → Resources 调整。

```console
gyliu-cary@Mac multikueue-minimal-demo % docker info --format '{{.MemTotal}} {{.NCPU}}'
24898469888 14
```

### 0.2 kind

必须 **≥ v0.31.0**（默认节点镜像为 k8s v1.35.0）。

```console
gyliu-cary@Mac multikueue-minimal-demo % brew install kind
```

其他平台：

```console
# Linux amd64
gyliu-cary@Mac ~ % curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-linux-amd64
gyliu-cary@Mac ~ % chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind

# macOS Apple Silicon（不用 brew 时）
gyliu-cary@Mac ~ % curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-darwin-arm64
gyliu-cary@Mac ~ % chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
```

验证：

```console
gyliu-cary@Mac multikueue-minimal-demo % kind version
kind v0.31.0 go1.25.5 darwin/arm64
```

### 0.3 kubectl 和 helm

```console
gyliu-cary@Mac multikueue-minimal-demo % brew install kubectl helm
```

验证：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl version --client
Client Version: v1.32.2
Kustomize Version: v5.5.0
```

`helm` 只用来装 KubeRay operator。Kueue 和 JobSet 都是直接 apply 官方发布的
`manifests.yaml`，不需要 helm。

---

## 第 1 步：创建 3 个 kind 集群

一个 manager，两个 worker，每个都是单节点集群。

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/0-create-clusters.sh
==> creating cluster mk-manager
Creating cluster "mk-manager" ...
 • Ensuring node image (kindest/node:v1.35.0) 🖼  ...
 ✓ Ensuring node image (kindest/node:v1.35.0) 🖼
 • Preparing nodes 📦   ...
 ✓ Preparing nodes 📦
 • Writing configuration 📜  ...
 ✓ Writing configuration 📜
 • Starting control-plane 🕹️  ...
 ✓ Starting control-plane 🕹️
 • Installing CNI 🔌  ...
 ✓ Installing CNI 🔌
 • Installing StorageClass 💾  ...
 ✓ Installing StorageClass 💾
 • Waiting ≤ 2m0s for control-plane = Ready ⏳  ...
 ✓ Waiting ≤ 2m0s for control-plane = Ready ⏳
 • Ready after 16s 💚
Set kubectl context to "kind-mk-manager"

==> creating cluster mk-worker1
Creating cluster "mk-worker1" ...
 ✓ Ready after 17s 💚
Set kubectl context to "kind-mk-worker1"

==> creating cluster mk-worker2
Creating cluster "mk-worker2" ...
 ✓ Ready after 16s 💚
Set kubectl context to "kind-mk-worker2"

==> clusters ready:
mk-manager
mk-worker1
mk-worker2
```

等价的手工命令：

```console
gyliu-cary@Mac multikueue-minimal-demo % kind create cluster --name mk-manager --image kindest/node:v1.35.0 --wait 120s
gyliu-cary@Mac multikueue-minimal-demo % kind create cluster --name mk-worker1 --image kindest/node:v1.35.0 --wait 120s
gyliu-cary@Mac multikueue-minimal-demo % kind create cluster --name mk-worker2 --image kindest/node:v1.35.0 --wait 120s
```

### 验证

```console
gyliu-cary@Mac multikueue-minimal-demo % kind get clusters
mk-manager
mk-worker1
mk-worker2
```

kind 会自动往 kubeconfig 里写 3 个 context：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl config get-contexts | grep mk-
*         kind-mk-manager   kind-mk-manager   kind-mk-manager
          kind-mk-worker1   kind-mk-worker1   kind-mk-worker1
          kind-mk-worker2   kind-mk-worker2   kind-mk-worker2
```

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get nodes
NAME                       STATUS   ROLES           AGE   VERSION
mk-manager-control-plane   Ready    control-plane   27m   v1.35.0
```

### 关键点：3 个集群在同一个 docker 网络里

kind 默认把所有集群放进名为 `kind` 的 docker bridge 网络。**这是 manager 能连上 worker
API server 的前提**：

```console
gyliu-cary@Mac multikueue-minimal-demo % docker network inspect kind -f '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}' | grep control-plane
mk-manager-control-plane 172.19.0.2/16
mk-worker1-control-plane 172.19.0.3/16
mk-worker2-control-plane 172.19.0.4/16
```

第 5 步会用到这几个 IP。

---

## 集群上下文切换（Context Switching）

这个 demo 有 3 个集群，验证过程中需要频繁在 manager 和 worker 之间来回查 Pod。这一节把
所有切换方式集中说明。

### 三个 context 的名字

kind 建集群时会自动往 `~/.kube/config` 里写入 context，命名规则是 `kind-<集群名>`：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl config get-contexts | grep mk-
*         kind-mk-manager   kind-mk-manager   kind-mk-manager
          kind-mk-worker1   kind-mk-worker1   kind-mk-worker1
          kind-mk-worker2   kind-mk-worker2   kind-mk-worker2
```

| 集群 | context 名字 | 角色 |
|---|---|---|
| mk-manager | `kind-mk-manager` | 提交作业、看 Workload 分发结果 |
| mk-worker1 | `kind-mk-worker1` | 看真正运行的 Pod |
| mk-worker2 | `kind-mk-worker2` | 看真正运行的 Pod |

### 方式一：`--context` 一次性指定（推荐）

**不改变当前默认 context**，最安全，本手册里所有命令都用这种写法：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get workloads
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get pods
```

好处是可以在**同一行命令里对比多个集群**，不会因为忘记切回去而误操作：

```console
gyliu-cary@Mac multikueue-minimal-demo % for c in manager worker1 worker2; do \
  echo "--- $c"; kubectl --context kind-mk-$c -n default get pods --no-headers 2>&1; done
--- manager
No resources found in default namespace.
--- worker1
demo-job-3-lhjdn   1/1   Running   0   12s
--- worker2
demo-job-2-lhjct   1/1   Running   0   13s
```

这条命令一眼就能看出 MultiKueue 生效了：manager 上没有 Pod，两个 worker 上各有一个。

### 方式二：切换默认 context

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl config use-context kind-mk-worker1
Switched to context "kind-mk-worker1".
```

查看当前指向哪个集群：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl config current-context
kind-mk-worker1
```

切完之后不带 `--context` 的命令就作用在这个集群上：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl get nodes
NAME                       STATUS   ROLES           AGE   VERSION
mk-worker1-control-plane   Ready    control-plane   38m   v1.35.0
```

切回 manager：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl config use-context kind-mk-manager
Switched to context "kind-mk-manager".
```

### 方式三：用本 demo 的辅助脚本

`scripts/ctx.sh` 封装了上面的操作，参数支持简写：

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/ctx.sh
==> demo contexts (* = current):
  * kind-mk-manager
    kind-mk-worker1
    kind-mk-worker2

usage: ./scripts/ctx.sh <manager|worker1|worker2>
```

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/ctx.sh worker1
Switched to context "kind-mk-worker1".
==> now pointing at mk-worker1
NAME                       STATUS   ROLES           AGE   VERSION
mk-worker1-control-plane   Ready    control-plane   38m   v1.35.0
```

支持的简写：`manager` / `mgr` / `m`，`worker1` / `w1` / `1`，`worker2` / `w2` / `2`。

### 方式四：定义 shell 别名（做实验时最省事）

把这几行贴进当前终端（或写进 `~/.zshrc`）：

```console
gyliu-cary@Mac multikueue-minimal-demo % alias kmgr='kubectl --context kind-mk-manager'
gyliu-cary@Mac multikueue-minimal-demo % alias kw1='kubectl --context kind-mk-worker1'
gyliu-cary@Mac multikueue-minimal-demo % alias kw2='kubectl --context kind-mk-worker2'
```

之后就可以这样用：

```console
gyliu-cary@Mac multikueue-minimal-demo % kmgr -n default get workloads
gyliu-cary@Mac multikueue-minimal-demo % kw1 -n default get pods
gyliu-cary@Mac multikueue-minimal-demo % kw2 -n default get pods
```

### 方式五：kubectx（第三方工具）

```console
gyliu-cary@Mac multikueue-minimal-demo % brew install kubectx
gyliu-cary@Mac multikueue-minimal-demo % kubectx kind-mk-worker1
gyliu-cary@Mac multikueue-minimal-demo % kubectx -          # 回到上一个 context
```

### 常用对照速查

| 想看什么 | 在哪个集群 | 命令 |
|---|---|---|
| 提交的 Job/JobSet/RayJob | manager | `kubectl --context kind-mk-manager -n default get jobs,jobsets,rayjobs` |
| Workload 被派到哪 | manager | `kubectl --context kind-mk-manager -n default get workloads -o custom-columns='WL:.metadata.name,RAN-ON:.status.clusterName'` |
| MultiKueue 连接状态 | manager | `kubectl --context kind-mk-manager get multikueuecluster` |
| **真正运行的 Pod** | worker | `kubectl --context kind-mk-worker1 -n default get pods` |
| worker 配额使用情况 | worker | `kubectl --context kind-mk-worker1 get clusterqueue cluster-queue` |
| Kueue 控制器日志 | manager | `kubectl --context kind-mk-manager -n kueue-system logs deployment/kueue-controller-manager` |

> `./scripts/status.sh` 会自动遍历 3 个集群，把上面这些一次性打出来，不用手工切换。

---

## 第 2 步：安装 JobSet 和 KubeRay

**必须在装 Kueue 之前做。** Kueue 在启动时才判断哪些集成可以启用（依据是对应 CRD 是否存在），
CRD 后装的话 Kueue 不会自动感知。

三个集群**都要装**，包括 manager。原因：MultiKueue 需要在 manager 上保存一份 JobSet/RayJob
的"影子副本"。两个 operator 都遵守 `spec.managedBy=kueue.x-k8s.io/multikueue`，在 manager
上看到这个字段就主动不干活，所以 manager 上不会产生任何 Pod。
（要求 JobSet ≥ v0.6.0、KubeRay ≥ v1.3.1。）

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/1-install-frameworks.sh
==> adding the kuberay helm repo
==> installing JobSet v0.12.0 on mk-manager
==> installing KubeRay 1.6.2 on mk-manager
Release "kuberay-operator" does not exist. Installing it now.
NAME: kuberay-operator
LAST DEPLOYED: Fri Aug 14 10:44:19 2026
NAMESPACE: kuberay-system
STATUS: deployed
REVISION: 1

==> installing JobSet v0.12.0 on mk-worker1
==> installing KubeRay 1.6.2 on mk-worker1
...
==> waiting for the JobSet controller on mk-manager
deployment "jobset-controller-manager" successfully rolled out
==> waiting for the JobSet controller on mk-worker1
deployment "jobset-controller-manager" successfully rolled out
==> waiting for the JobSet controller on mk-worker2
deployment "jobset-controller-manager" successfully rolled out

==> framework CRDs now available:
--- mk-manager
jobsets.jobset.x-k8s.io
rayjobs.ray.io
rayclusters.ray.io
rayservices.ray.io
--- mk-worker1
jobsets.jobset.x-k8s.io
rayjobs.ray.io
rayclusters.ray.io
rayservices.ray.io
--- mk-worker2
jobsets.jobset.x-k8s.io
rayjobs.ray.io
rayclusters.ray.io
rayservices.ray.io
```

等价的手工命令（对每个 context 各跑一遍）：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply --server-side \
  -f https://github.com/kubernetes-sigs/jobset/releases/download/v0.12.0/manifests.yaml

gyliu-cary@Mac multikueue-minimal-demo % helm repo add kuberay https://ray-project.github.io/kuberay-helm/
gyliu-cary@Mac multikueue-minimal-demo % helm --kube-context kind-mk-manager upgrade --install kuberay-operator \
  kuberay/kuberay-operator --version 1.6.2 -n kuberay-system --create-namespace --wait
```

### 验证

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get pods -A | grep -E "jobset|kuberay"
jobset-system        jobset-controller-manager-5585d4c665-c9qf4         1/1     Running   0          14m
kuberay-system       kuberay-operator-5dff8cd9d5-wz9nm                  1/1     Running   0          14m
```

---

## 第 3 步：安装 Kueue 并启用 MultiKueue

### 3.1 MultiKueue 需要额外"开启"吗？

**不需要。** `MultiKueue` 特性门控自 Kueue v0.9 起就是 **Beta 且默认开启**：

```go
// pkg/features/kube_features.go
MultiKueue: {
    {Version: version.MustParse("0.6"), Default: false, PreRelease: featuregate.Alpha},
    {Version: version.MustParse("0.9"), Default: true,  PreRelease: featuregate.Beta},
},
```

所以装完 Kueue 就能用，不用加任何 `--feature-gates` 参数。真正让 MultiKueue "生效"的动作是
第 6 步创建那几个 CR（AdmissionCheck / MultiKueueConfig / MultiKueueCluster）。

### 3.2 安装

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/2-install-kueue.sh
==> installing Kueue v0.19.1 on mk-manager
==> pinning enabled integrations on mk-manager
configmap/kueue-manager-config configured
deployment.apps/kueue-controller-manager restarted
==> installing Kueue v0.19.1 on mk-worker1
==> pinning enabled integrations on mk-worker1
configmap/kueue-manager-config configured
deployment.apps/kueue-controller-manager restarted
==> installing Kueue v0.19.1 on mk-worker2
==> pinning enabled integrations on mk-worker2
configmap/kueue-manager-config configured
deployment.apps/kueue-controller-manager restarted
==> waiting for kueue-controller-manager on mk-manager
deployment "kueue-controller-manager" successfully rolled out
==> waiting for kueue-controller-manager on mk-worker1
deployment "kueue-controller-manager" successfully rolled out
==> waiting for kueue-controller-manager on mk-worker2
deployment "kueue-controller-manager" successfully rolled out
==> enabled integrations (should list batch/job, jobset and the ray kinds):
integrations:
  frameworks:
  - "batch/job"
  - "jobset.x-k8s.io/jobset"
  - "ray.io/rayjob"
  - "ray.io/raycluster"
  - "ray.io/rayservice"
```

等价的手工命令：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply --server-side \
  -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.19.1/manifests.yaml
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f manifests/kueue-config.yaml
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system rollout restart deployment/kueue-controller-manager
```

### 3.3 为什么必须改 ConfigMap

这是本 demo 最重要的一个坑。Kueue 默认启用了一大堆集成：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system get cm kueue-manager-config \
  -o jsonpath='{.data.controller_manager_config\.yaml}' | grep -A 20 "^integrations:"
integrations:
  frameworks:
  - "batch/job"
  - "kubeflow.org/mpijob"
  - "ray.io/rayjob"
  - "ray.io/raycluster"
  - "ray.io/rayservice"
  - "jobset.x-k8s.io/jobset"
  - "workload.codeflare.dev/appwrapper"
  - "trainer.kubeflow.org/trainjob"
  - "pod"
  - "deployment"
  - "statefulset"
  - "leaderworkerset.x-k8s.io/leaderworkerset"
```

MultiKueue 会**为每个启用的框架**在每个 worker 上建立 watch。worker 上没装 AppWrapper /
Kubeflow Trainer / LeaderWorkerSet 的 CRD，watch 建不起来，整个集群连接就失败。所以
`manifests/kueue-config.yaml` 把列表收窄到本 demo 实际安装的这几个。

**规则：`integrations.frameworks` 必须和 worker 上实际装的 operator 严格对应。**

### 3.4 配置里的分发策略

同一个 ConfigMap 里还配了 MultiKueue 的分发策略：

```yaml
multiKueue:
  dispatcherName: kueue.x-k8s.io/multikueue-dispatcher-all-at-once
  workerLostTimeout: 15m
  gcInterval: 1m
```

完整解释见 [README 第 5 节](README.zh-CN.md#5-分发策略dispatch-strategy)。

### 验证

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system get pods
NAME                                        READY   STATUS    RESTARTS   AGE
kueue-controller-manager-5cb5c9fbcd-mt4h2   1/1     Running   0          9m54s
```

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get crd | grep -E "jobset|ray.io|kueue"
admissionchecks.kueue.x-k8s.io              2026-08-14T14:32:18Z
clusterqueues.kueue.x-k8s.io                2026-08-14T14:32:18Z
cohorts.kueue.x-k8s.io                      2026-08-14T14:32:18Z
jobsets.jobset.x-k8s.io                     2026-08-14T14:44:18Z
localqueues.kueue.x-k8s.io                  2026-08-14T14:32:18Z
multikueueclusters.kueue.x-k8s.io           2026-08-14T14:32:18Z
multikueueconfigs.kueue.x-k8s.io            2026-08-14T14:32:18Z
provisioningrequestconfigs.kueue.x-k8s.io   2026-08-14T14:32:18Z
rayclusters.ray.io                          2026-08-14T14:44:18Z
raycronjobs.ray.io                          2026-08-14T14:44:18Z
rayjobs.ray.io                              2026-08-14T14:44:18Z
rayservices.ray.io                          2026-08-14T14:44:18Z
```

---

## 第 4 步：配置 worker 队列

worker 集群就是一个普通的独立 Kueue 集群。关键约束：**namespace 和 LocalQueue 的名字必须
和 manager 完全一致**（这里是 `default` / `user-queue`），因为 MultiKueue 是把 Workload
原样复制过去的。

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/3-setup-workers.sh
==> applying queues on mk-worker1
resourceflavor.kueue.x-k8s.io/default-flavor created
clusterqueue.kueue.x-k8s.io/cluster-queue created
localqueue.kueue.x-k8s.io/user-queue created
==> applying queues on mk-worker2
resourceflavor.kueue.x-k8s.io/default-flavor created
clusterqueue.kueue.x-k8s.io/cluster-queue created
localqueue.kueue.x-k8s.io/user-queue created
==> worker queues:
--- mk-worker1
NAME                                        COHORT   PENDING WORKLOADS
clusterqueue.kueue.x-k8s.io/cluster-queue            0

NAMESPACE   NAME                                   CLUSTERQUEUE    PENDING WORKLOADS   ADMITTED WORKLOADS
default     localqueue.kueue.x-k8s.io/user-queue   cluster-queue   0                   0
--- mk-worker2
NAME                                        COHORT   PENDING WORKLOADS
clusterqueue.kueue.x-k8s.io/cluster-queue            0

NAMESPACE   NAME                                   CLUSTERQUEUE    PENDING WORKLOADS   ADMITTED WORKLOADS
default     localqueue.kueue.x-k8s.io/user-queue   cluster-queue   0                   0
```

worker 配额刻意设小（2 CPU / 4Gi），这样才能演示"配额压力在 worker 侧"：

```yaml
# manifests/worker-queues.yaml
resources:
  - name: cpu
    nominalQuota: 2
  - name: memory
    nominalQuota: 4Gi
```

---

## 第 5 步：打通 manager 到 worker 的连接

这是**唯一**的跨集群连接机制：一份 kubeconfig，存成 manager 上的 Secret。

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/4-connect.sh
==> creating MultiKueue ServiceAccount on mk-worker1
serviceaccount/multikueue-sa created
clusterrole.rbac.authorization.k8s.io/multikueue-sa-role created
clusterrolebinding.rbac.authorization.k8s.io/multikueue-sa-crb created
secret/multikueue-sa created
==> waiting for the ServiceAccount token to be populated on mk-worker1
==> mk-worker1 API server reachable in-network at https://172.19.0.3:6443
==> storing mk-worker1 kubeconfig as a Secret on mk-manager
secret/mk-worker1-secret created
==> creating MultiKueue ServiceAccount on mk-worker2
serviceaccount/multikueue-sa created
clusterrole.rbac.authorization.k8s.io/multikueue-sa-role created
clusterrolebinding.rbac.authorization.k8s.io/multikueue-sa-crb created
secret/multikueue-sa created
==> waiting for the ServiceAccount token to be populated on mk-worker2
==> mk-worker2 API server reachable in-network at https://172.19.0.4:6443
==> storing mk-worker2 kubeconfig as a Secret on mk-manager
secret/mk-worker2-secret created
==> connection secrets on the manager:
mk-worker1-secret           Opaque   1      0s
mk-worker2-secret           Opaque   1      0s
```

这一步做了三件事：

**1）在 worker 上创建受限的 ServiceAccount**（`manifests/worker-multikueue-rbac.yaml`）。
权限只覆盖 Kueue Workload + 本 demo 安装的三种框架。注意这个 ClusterRole 必须覆盖第 3 步
`integrations.frameworks` 里的每一个框架，否则 manager 的 watch 会被 403 拒绝。

**2）为该 SA 申请长期 token**。k8s 1.24 起不再自动给 SA 建 token Secret，要显式声明：

```yaml
apiVersion: v1
kind: Secret
type: kubernetes.io/service-account-token
metadata:
  name: multikueue-sa
  namespace: kueue-system
  annotations:
    kubernetes.io/service-account.name: multikueue-sa
```

**3）拼出 kubeconfig，注意 server 地址** ← **kind 环境最大的坑**

`kind get kubeconfig` 给出的地址是 `https://127.0.0.1:<随机端口>`，**只在宿主机上有效**。
manager 上的 Kueue Pod 跑在容器网络里，访问不到。必须换成 worker control-plane 容器在
`kind` docker 网络上的 IP：

```console
gyliu-cary@Mac multikueue-minimal-demo % docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' mk-worker1-control-plane
172.19.0.3
```

kubeadm 会把这个 IP 写进 API server 的服务端证书 SAN，所以 TLS 校验照样通过，不需要
`insecure-skip-tls-verify`。

生成出来的 kubeconfig 长这样（token 已截断）：

```yaml
apiVersion: v1
kind: Config
clusters:
  - name: mk-worker1
    cluster:
      certificate-authority-data: LS0tLS1CRUdJTiBDRVJU...
      server: https://172.19.0.3:6443     # ← 容器网络内的地址，不是 127.0.0.1
users:
  - name: multikueue-sa
    user:
      token: eyJhbGciOiJSUzI1NiIsImtpZCI6...
contexts:
  - name: mk-worker1
    context:
      cluster: mk-worker1
      user: multikueue-sa
current-context: mk-worker1
```

### 验证

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system get secret | grep -- -secret
mk-worker1-secret           Opaque   1      12m
mk-worker2-secret           Opaque   1      12m
```

---

## 第 6 步：在 manager 上接线 MultiKueue

创建那条对象链：`ClusterQueue → AdmissionCheck → MultiKueueConfig → MultiKueueCluster → Secret`。

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/5-setup-manager.sh
==> applying MultiKueue setup on mk-manager
resourceflavor.kueue.x-k8s.io/default-flavor created
clusterqueue.kueue.x-k8s.io/cluster-queue created
localqueue.kueue.x-k8s.io/user-queue created
admissioncheck.kueue.x-k8s.io/multikueue-check created
multikueueconfig.kueue.x-k8s.io/multikueue-config created
multikueuecluster.kueue.x-k8s.io/mk-worker1 created
multikueuecluster.kueue.x-k8s.io/mk-worker2 created
==> waiting for both MultiKueueClusters to report Active
CLUSTER      ACTIVE   REASON   MESSAGE
mk-worker1   True     Active   Connected
mk-worker2   True     Active   Connected

CHECK              ACTIVE   MESSAGE
multikueue-check   True     The admission check is active
```

**`Active=True / Connected` 就是环境搭好了的标志。**

关键的一段是 ClusterQueue 上挂 AdmissionCheck ——「普通队列」和「跨集群派发队列」的唯一区别：

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
kind: ClusterQueue
metadata:
  name: cluster-queue
spec:
  # ... resourceGroups ...
  admissionChecksStrategy:
    admissionChecks:
      - name: multikueue-check     # ← 加了这个，这个队列就不在本地跑任何东西了
```

### 验证

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get multikueuecluster
NAME         CONNECTED   AGE
mk-worker1   True        3m
mk-worker2   True        3m
```

如果 `ACTIVE` 是 `False`，直接看 `MESSAGE` 字段，绝大多数问题它都说清楚了 ——
见[排错手册](#排错手册)。

---

## 测试 1：batch/v1 Job

**目标**：验证最基础的跨集群派发，并观察配额如何在 worker 侧生效。

### 场景设计

- 提交 **3 个 Job**，每个请求 **2 CPU**
- manager 配额 **10 CPU**（不构成瓶颈）
- 每个 worker 配额 **2 CPU**（真正的闸门）

预期：2 个 Job 各占一个 worker 跑起来，第 3 个因两边都满而排队。

### 分发策略

本测试用的是 **AllAtOnce**（`kueue.x-k8s.io/multikueue-dispatcher-all-at-once`），
配置在 `manifests/kueue-config.yaml` 的 `multiKueue.dispatcherName`。
行为是：Workload 在 manager 拿到 `QuotaReserved` 后，**同时**在 mk-worker1 和 mk-worker2
上各建一份副本，谁先 admit 谁赢，输的那份被删除。

### 执行

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/run-demo-job.sh
==> deleting demo workloads on mk-manager
==> sweeping mk-worker1
==> sweeping mk-worker2
==> queues are empty:
mk-worker1   0     0
mk-worker2   0     0
==> submitting 3 batch/Jobs to mk-manager
job.batch/demo-job-1 created
job.batch/demo-job-2 created
job.batch/demo-job-3 created
==> waiting for MultiKueue to dispatch...

==> MANAGER (mk-manager) — submitted here, but nothing executes here
NAME                   STATUS    COMPLETIONS   DURATION   AGE
job.batch/demo-job-1   Running   0/1                      6s
job.batch/demo-job-2   Running   0/1           5s         6s
job.batch/demo-job-3   Running   0/1           4s         6s
  pods on the manager (expected: none):
  <none>

==> MANAGER — Workloads: which worker cluster each one was dispatched to
WORKLOAD               ADMITTED   DISPATCHED-TO   MESSAGE
job-demo-job-1-a9067   <none>     <none>
job-demo-job-2-dd6ff   True       mk-worker2      The workload was admitted on "mk-worker2"
job-demo-job-3-53d6e   True       mk-worker1      The workload was admitted on "mk-worker1"

==> WORKER (mk-worker1) — the Pods actually run here
NAME                   STATUS    COMPLETIONS   DURATION   AGE
job.batch/demo-job-3   Running   0/1           4s         4s
NAME               READY   STATUS    RESTARTS   AGE
demo-job-3-lhjdn   1/1     Running   0          4s
CLUSTERQUEUE    PENDING   ADMITTED
cluster-queue   1         1

==> WORKER (mk-worker2) — the Pods actually run here
NAME                   STATUS    COMPLETIONS   DURATION   AGE
job.batch/demo-job-2   Running   0/1           5s         5s
NAME               READY   STATUS    RESTARTS   AGE
demo-job-2-lhjct   1/1     Running   0          5s
CLUSTERQUEUE    PENDING   ADMITTED
cluster-queue   1         1
```

### 结果解读

| 观察点 | 输出 | 说明 |
|---|---|---|
| manager 上的 Pod | `<none>` | **MultiKueue 生效的核心证据** |
| demo-job-2 | `mk-worker2` | 被派到 worker2 |
| demo-job-3 | `mk-worker1` | 被派到 worker1 |
| demo-job-1 | `ADMITTED <none>` | manager 配额够，但两个 worker 都满了 |
| worker `PENDING 1` | 两个 worker 都是 1 | AllAtOnce 在**两个** worker 上都建了 demo-job-1 的副本，都在排队 |

`PENDING 1` 这一栏是理解 AllAtOnce 的关键：同一个 Workload 同时在两个集群排队，哪个先有
空位就在哪跑，另一份会被删除。

### 手工验证 managedBy

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get job demo-job-1 \
  -o custom-columns='JOB:.metadata.name,SUSPEND:.spec.suspend,MANAGED-BY:.spec.managedBy'
JOB          SUSPEND   MANAGED-BY
demo-job-1   true      kueue.x-k8s.io/multikueue
```

`managedBy` 不是我们在 YAML 里写的，是 Kueue webhook 自动打上的 —— 因为
`user-queue` 指向的 ClusterQueue 挂了 MultiKueue AdmissionCheck。manager 上的原生 Job
控制器看到这个值不是自己，就完全不碰它。

### 查看完整 Workload 状态

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get workload -o yaml | grep -A 40 "  status:"
  status:
    admission:
      clusterQueue: cluster-queue
      podSetAssignments:
      - count: 2
        flavors:
          cpu: default-flavor
          memory: default-flavor
        name: workers
        resourceUsage:
          cpu: "1"
          memory: 400Mi
    admissionChecks:
    - lastTransitionTime: "2026-08-14T14:56:12Z"
      message: The workload was admitted on "mk-worker2"
      name: multikueue-check
      state: Ready
    clusterName: mk-worker2
    conditions:
    - lastTransitionTime: "2026-08-14T14:56:11Z"
      message: Quota reserved in ClusterQueue cluster-queue
      observedGeneration: 1
      reason: QuotaReserved
      status: "True"
      type: QuotaReserved
    - lastTransitionTime: "2026-08-14T14:56:12Z"
      message: The workload is admitted
      observedGeneration: 1
      reason: Admitted
      status: "True"
      type: Admitted
    - lastTransitionTime: "2026-08-14T14:56:16Z"
      message: All pods reached readiness and the workload is running
      observedGeneration: 1
      reason: Started
      status: "True"
      type: PodsReady
```

两道闸门在这里看得最清楚：`QuotaReserved`（manager 放行）→ `Admitted`（worker 接单）。

---

## 测试 2：JobSet

**目标**：验证一个多 Pod 的 gang 工作负载被**整体**派发到同一个集群，不会被拆散。

### 场景设计

一个 JobSet，2 个 replicated Job，每个请求 500m CPU（总计 1 CPU）。

### 分发策略

同样是 **AllAtOnce**（全局配置，对所有工作负载类型生效）。分发策略是 Kueue 级别的配置，
不区分框架。

### 执行

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/run-demo-jobset.sh
==> deleting demo workloads on mk-manager
==> sweeping mk-worker1
==> sweeping mk-worker2
==> queues are empty:
mk-worker1   0     0
mk-worker2   0     0
==> submitting a JobSet to mk-manager
jobset.jobset.x-k8s.io/demo-jobset created
==> spec.managedBy defaulted by the Kueue webhook on the manager:
demo-jobset  managedBy=kueue.x-k8s.io/multikueue  suspend=false
==> waiting for MultiKueue to dispatch...
==> dispatched to mk-worker2

==> MANAGER (mk-manager) — submitted here, but nothing executes here
NAME                                 TERMINALSTATE   RESTARTS   COMPLETED   SUSPENDED   AGE
jobset.jobset.x-k8s.io/demo-jobset                                          false       2s
  pods on the manager (expected: none):
  <none>

==> MANAGER — Workloads: which worker cluster each one was dispatched to
WORKLOAD                   ADMITTED   DISPATCHED-TO   MESSAGE
jobset-demo-jobset-0e211   True       mk-worker2      The workload was admitted on "mk-worker2"

==> WORKER (mk-worker1) — the Pods actually run here
CLUSTERQUEUE    PENDING   ADMITTED
cluster-queue   0         0

==> WORKER (mk-worker2) — the Pods actually run here
NAME                              STATUS    COMPLETIONS   DURATION   AGE
job.batch/demo-jobset-workers-0   Running   0/1           2s         2s
job.batch/demo-jobset-workers-1   Running   0/1           2s         2s
NAME                                 TERMINALSTATE   RESTARTS   COMPLETED   SUSPENDED   AGE
jobset.jobset.x-k8s.io/demo-jobset                   0                      false       2s
NAME                            READY   STATUS              RESTARTS   AGE
demo-jobset-workers-0-0-p44m7   0/1     ContainerCreating   0          2s
demo-jobset-workers-1-0-9xqnm   0/1     ContainerCreating   0          2s
CLUSTERQUEUE    PENDING   ADMITTED
cluster-queue   0         1
```

### 结果解读

| 观察点 | 输出 | 说明 |
|---|---|---|
| manager 上的 JobSet | 存在，`SUSPENDED false` | 只是个影子对象 |
| manager 上的**子 Job** | 不存在 | JobSet 控制器因 `managedBy` 主动不干活 |
| manager 上的 Pod | `<none>` | ✓ |
| mk-worker2 | 2 个子 Job + 2 个 Pod | 整个 JobSet 完整落在**一个**集群 |
| mk-worker1 | 空 | ✓ **gang 不会被跨集群拆散** |

这是 MultiKueue 相比"把 Pod 撒到各个集群"的关键区别：**派发的最小单位是整个 Workload**，
分布式训练需要的 Pod 间通信因此得以保证。

`managedBy=kueue.x-k8s.io/multikueue` 在提交后 2 秒就被 webhook 打上了，我们的 YAML 里
并没有写它：

```console
gyliu-cary@Mac multikueue-minimal-demo % grep -c managedBy examples/jobset.yaml
0
```

---

## 测试 3：RayJob

**目标**：验证一个会**动态创建子资源**（RayCluster）的工作负载，其子资源只在目标 worker
上被创建。

### 场景设计

一个 RayJob：head 500m/2Gi + 1 个 worker 500m/1Gi（合计 1 CPU / 3Gi，装得进 worker 的
2 CPU / 4Gi 配额）。`shutdownAfterJobFinishes: true`，跑完自动拆掉 RayCluster 释放配额。

### 分发策略

仍是 **AllAtOnce**。

### 执行

脚本会先把 Ray 镜像预加载进两个 worker（177MB 的精简 Ray 镜像，比官方 `rayproject/ray`
的数 GB 轻很多）：

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/run-demo-rayjob.sh
==> deleting demo workloads on mk-manager
==> sweeping mk-worker1
==> sweeping mk-worker2
==> queues are empty:
mk-worker1   0     0
mk-worker2   0     0
==> pre-pulling us-central1-docker.pkg.dev/k8s-staging-images/kueue/ray-project-mini:0.0.4 on the host
==> loading the Ray image into mk-worker1
==> loading the Ray image into mk-worker2
==> submitting a RayJob to mk-manager
rayjob.ray.io/demo-rayjob created
==> spec.managedBy defaulted by the Kueue webhook on the manager:
demo-rayjob  managedBy=kueue.x-k8s.io/multikueue  suspend=
==> waiting for MultiKueue to dispatch...
==> dispatched to mk-worker2
==> watching the RayCluster come up on the worker (Ctrl-C is safe)...
  demo-rayjob-mm7f9-head-7zzgz                 0/1   Running       0     2s
  demo-rayjob-mm7f9-small-group-worker-llslc   0/1   Init:0/1      0     2s

==> MANAGER (mk-manager) — submitted here, but nothing executes here
NAME                        JOB STATUS   DEPLOYMENT STATUS   RAY CLUSTER NAME    START TIME             END TIME   AGE
rayjob.ray.io/demo-rayjob                Initializing        demo-rayjob-mm7f9   2026-08-14T14:55:38Z              3s
  pods on the manager (expected: none):
  <none>

==> MANAGER — Workloads: which worker cluster each one was dispatched to
WORKLOAD                   ADMITTED   DISPATCHED-TO   MESSAGE
rayjob-demo-rayjob-a5a54   True       mk-worker2      The workload was admitted on "mk-worker2"

==> WORKER (mk-worker1) — the Pods actually run here
CLUSTERQUEUE    PENDING   ADMITTED
cluster-queue   0         0

==> WORKER (mk-worker2) — the Pods actually run here
NAME                        JOB STATUS   DEPLOYMENT STATUS   RAY CLUSTER NAME    START TIME             END TIME   AGE
rayjob.ray.io/demo-rayjob                Initializing        demo-rayjob-mm7f9   2026-08-14T14:55:38Z              2s
NAME                                         READY   STATUS   RESTARTS   AGE
demo-rayjob-mm7f9-head-7zzgz                 0/1     Running  0          2s
demo-rayjob-mm7f9-small-group-worker-llslc   0/1     Init:0/1 0          2s
CLUSTERQUEUE    PENDING   ADMITTED
cluster-queue   0         1

==> waiting for the RayJob to finish...
==> final state on the manager (status synced back from the worker):
NAME          JOB-STATUS   DEPLOYMENT   MANAGED-BY
demo-rayjob   SUCCEEDED    Running      kueue.x-k8s.io/multikueue
WORKLOAD                   FINISHED   RAN-ON
rayjob-demo-rayjob-a5a54   <none>     mk-worker2
  pods on the manager (expected: none):
  No resources found in default namespace.
```

### 结果解读

| 观察点 | 输出 | 说明 |
|---|---|---|
| manager 上的 RayJob | 存在，`RAY CLUSTER NAME` 有值 | 状态从 worker 同步回来的 |
| manager 上的 **RayCluster Pod** | `<none>` | KubeRay operator 因 `managedBy` 不建 Pod |
| mk-worker2 | head + worker Pod | RayCluster 只在这里被真正创建 |
| manager 最终 `JOB-STATUS` | `SUCCEEDED` | **worker 上的执行结果同步回了 manager** |

最后一行是 MultiKueue 状态同步的直接证明：用户只跟 manager 打交道，却能看到 worker 上的
真实执行结果。

### 观察 RayCluster 的生命周期

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get events --sort-by=.lastTimestamp | tail -8
53s   Normal  CreatedService          rayjob/demo-rayjob    Created the service default/demo-rayjob-head-svc
53s   Normal  CreatedRayJobSubmitter  rayjob/demo-rayjob    Created Kubernetes Job default/demo-rayjob
52s   Normal  Started                 pod/demo-rayjob-mlv7m Container started
43s   Normal  DeletedRayCluster       rayjob/demo-rayjob    Deleted cluster default/demo-rayjob-4sp5h
43s   Normal  Killing                 pod/demo-rayjob-4sp5h-head-nmg2m  Stopping container ray-head
43s   Normal  Completed               job/demo-rayjob       Job completed
```

`Job completed` → `DeletedRayCluster` 就是 `shutdownAfterJobFinishes: true` 在起作用，
worker 的配额随之释放。

---

## 排错手册

### 坑1: JobSet CRD 缺失导致连接失败

**症状**：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get multikueuecluster \
  -o custom-columns='CLUSTER:.metadata.name,ACTIVE:.status.conditions[?(@.type=="Active")].status,REASON:.status.conditions[?(@.type=="Active")].reason,MESSAGE:.status.conditions[?(@.type=="Active")].message'
CLUSTER      ACTIVE   REASON                   MESSAGE
mk-worker1   False    ClientConnectionFailed   no matches for kind "JobSet" in version "jobset.x-k8s.io/v1alpha2"
mk-worker2   False    ClientConnectionFailed   no matches for kind "JobSet" in version "jobset.x-k8s.io/v1alpha2"

CHECK              ACTIVE   MESSAGE
multikueue-check   False    Inactive clusters: [mk-worker1 mk-worker2]
```

**原因**：Kueue 默认启用了 jobset / appwrapper / trainer / lws 等一堆集成，MultiKueue
为每个启用的框架在 worker 上建 watch，worker 缺对应 CRD 就整体失败。

**解决**：二选一

1. 在**所有** worker 上装齐这些 operator；或者
2. 把 `integrations.frameworks` 收窄到实际安装的那几个（本 demo 的做法，见
   `manifests/kueue-config.yaml`），改完必须重启 controller：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f manifests/kueue-config.yaml
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system rollout restart deployment/kueue-controller-manager
```

### 坑2: manager 连不上 worker（kind 网络）

**症状**：`Active=False`，MESSAGE 里是 `connection refused` 或 `i/o timeout`。

**原因**：kubeconfig 里的 server 写成了 `https://127.0.0.1:<port>`。宿主机能通，manager
的 Pod 通不了。

**排查**：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system get secret mk-worker1-secret \
  -o jsonpath='{.data.kubeconfig}' | base64 -d | grep server
    server: https://172.19.0.3:6443
```

必须是 `172.x.x.x` 这种 docker 网络内地址。如果是 `127.0.0.1`，重跑 `./scripts/4-connect.sh`。

### 坑3: RayJob head 容器 OOMKilled

**症状**：head Pod `CrashLoopBackOff`，且**一行日志都没有**。

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get pod <head-pod> \
  -o jsonpath='{.status.containerStatuses[0].lastState}'
{"terminated":{"exitCode":137,"reason":"OOMKilled",...}}
```

**原因**：Ray head 内存给少了。`exitCode 137` = OOMKilled。

**解决**：head 的 `limits.memory` 至少 4Gi（本 demo 给了 8Gi）。注意 `requests` 才是
Kueue 配额账本上算的数，`limits` 不算 —— 所以可以 requests 给 2Gi、limits 给 8Gi，既不
撑爆配额又不会 OOM。

### 坑4: Ray object store 尺寸报错

**症状**：

```
ValueError: Attempting to cap object store memory usage at 1146470 bytes,
but the minimum allowed is 78643200 bytes.
```

**解决**：在 `rayStartParams` 里显式指定：

```yaml
rayStartParams:
  object-store-memory: "134217728"
```

### 坑5: kind load docker-image 失败

**症状**：

```
ERROR: failed to load image: ... ctr: content digest sha256:...: not found
```

**原因**：`kind load docker-image` 用 `--all-platforms` 重新导入，多架构镜像在本地只有
当前平台的层，其他平台的 digest 找不到。

**解决**：先 `docker save --platform` 存成单平台归档再导入：

```console
gyliu-cary@Mac multikueue-minimal-demo % docker save --platform linux/arm64 <image> -o image.tar
gyliu-cary@Mac multikueue-minimal-demo % kind load image-archive image.tar --name mk-worker1
```

### 坑6: Workload 卡在 pending，worker 上什么都没有

**排查顺序**：

```console
# 1. AdmissionCheck 是否 Active
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get admissioncheck multikueue-check -o yaml | grep -A5 conditions

# 2. worker 上是否有同名 namespace 和 LocalQueue（名字必须完全一致）
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get localqueue

# 3. worker 的 ResourceFlavor 名字是否和 manager 一致
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get resourceflavor

# 4. worker 配额是否根本装不下这个 Workload
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get clusterqueue cluster-queue -o yaml | grep -A20 "status:"

# 5. 看 manager 的 Kueue 日志
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system logs deployment/kueue-controller-manager --tail=100 | grep -i multikueue
```

### 通用状态检查

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/status.sh
```

---

## 清理

清掉工作负载但保留集群（方便反复做实验）：

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/clean-workloads.sh
==> deleting demo workloads on mk-manager
==> sweeping mk-worker1
==> sweeping mk-worker2
==> queues are empty:
mk-worker1   0     0
mk-worker2   0     0
```

删掉整个环境：

```console
gyliu-cary@Mac multikueue-minimal-demo % ./scripts/down.sh
==> deleting cluster mk-manager
Deleting cluster "mk-manager" ...
==> deleting cluster mk-worker1
Deleting cluster "mk-worker1" ...
==> deleting cluster mk-worker2
Deleting cluster "mk-worker2" ...
==> torn down
```

等价手工命令：

```console
gyliu-cary@Mac multikueue-minimal-demo % kind delete clusters mk-manager mk-worker1 mk-worker2
```
