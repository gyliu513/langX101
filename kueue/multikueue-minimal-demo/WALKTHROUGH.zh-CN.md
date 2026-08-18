# MultiKueue Demo 分步操作手册

> English: [WALKTHROUGH.md](WALKTHROUGH.md) · 架构原理：[README.zh-CN.md](README.zh-CN.md)

本文档记录搭建全过程的**每一条命令和它的真实输出**（在 macOS / Apple Silicon / Docker
Desktop 上实际执行采集）。全程用 `kubectl` / `kind` / `helm` 逐步敲，不依赖封装脚本。
原理和架构见 [README.zh-CN.md](README.zh-CN.md)。

仓库里仍有 `scripts/`，只是可选的一键封装；本手册讲解不以脚本为准。

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
gyliu-cary@Mac multikueue-minimal-demo % kind create cluster --name mk-manager --image kindest/node:v1.35.0 --wait 120s
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

gyliu-cary@Mac multikueue-minimal-demo % kind create cluster --name mk-worker1 --image kindest/node:v1.35.0 --wait 120s
Creating cluster "mk-worker1" ...
 ✓ Ready after 17s 💚
Set kubectl context to "kind-mk-worker1"

gyliu-cary@Mac multikueue-minimal-demo % kind create cluster --name mk-worker2 --image kindest/node:v1.35.0 --wait 120s
Creating cluster "mk-worker2" ...
 ✓ Ready after 16s 💚
Set kubectl context to "kind-mk-worker2"
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

### 方式三：定义 shell 别名（做实验时最省事）

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

### 方式四：kubectx（第三方工具）

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

对照一次「提交在哪 vs 跑在哪」，把这几条挨个跑：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get jobs,jobsets,rayjobs,workloads,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get jobs,jobsets,rayjobs,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get clusterqueue cluster-queue
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get jobs,jobsets,rayjobs,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 get clusterqueue cluster-queue
```

---

## 第 2 步：安装 JobSet 和 KubeRay

**必须在装 Kueue 之前做。** Kueue 在启动时才判断哪些集成可以启用（依据是对应 CRD 是否存在），
CRD 后装的话 Kueue 不会自动感知。

三个集群**都要装**，包括 manager。原因：MultiKueue 需要在 manager 上保存一份 JobSet/RayJob
的"影子副本"。两个 operator 都遵守 `spec.managedBy=kueue.x-k8s.io/multikueue`，在 manager
上看到这个字段就主动不干活，所以 manager 上不会产生任何 Pod。
（要求 JobSet ≥ v0.6.0、KubeRay ≥ v1.3.1。）

三个集群都要装。对每个 context（`kind-mk-manager`、`kind-mk-worker1`、`kind-mk-worker2`）
各跑一遍下面这组命令。先加 helm repo（只需一次）：

```console
gyliu-cary@Mac multikueue-minimal-demo % helm repo add kuberay https://ray-project.github.io/kuberay-helm/
gyliu-cary@Mac multikueue-minimal-demo % helm repo update kuberay
```

以 manager 为例（worker 把 `--context` / `--kube-context` 换成对应名字即可）：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply --server-side \
  -f https://github.com/kubernetes-sigs/jobset/releases/download/v0.12.0/manifests.yaml

gyliu-cary@Mac multikueue-minimal-demo % helm --kube-context kind-mk-manager upgrade --install kuberay-operator \
  kuberay/kuberay-operator --version 1.6.2 -n kuberay-system --create-namespace --wait

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n jobset-system \
  rollout status deployment/jobset-controller-manager --timeout=300s
deployment "jobset-controller-manager" successfully rolled out
```

真实输出（三个集群装完后）：

```
NAME: kuberay-operator
LAST DEPLOYED: Fri Aug 14 10:44:19 2026
NAMESPACE: kuberay-system
STATUS: deployed
REVISION: 1
```

### 验证

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get crd \
  jobsets.jobset.x-k8s.io rayjobs.ray.io rayclusters.ray.io rayservices.ray.io \
  -o custom-columns='CRD:.metadata.name' --no-headers
jobsets.jobset.x-k8s.io
rayjobs.ray.io
rayclusters.ray.io
rayservices.ray.io
```

三个集群的 CRD 列表应相同。worker 上再各跑一遍 `kubectl --context kind-mk-worker1 get crd ...`。

再确认 operator 在跑：

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

对三个 context 各跑一遍：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply --server-side \
  -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.19.1/manifests.yaml
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f manifests/kueue-config.yaml
configmap/kueue-manager-config configured
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system \
  rollout restart deployment/kueue-controller-manager
deployment.apps/kueue-controller-manager restarted
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system \
  rollout status deployment/kueue-controller-manager --timeout=300s
deployment "kueue-controller-manager" successfully rolled out
```

把 `kind-mk-manager` 换成 `kind-mk-worker1`、`kind-mk-worker2` 再各做一次。

`apply -f manifests/kueue-config.yaml` 之后必须 `rollout restart`：Kueue 只在启动时读这份
ConfigMap，不重启就不会收窄 integrations。

webhook 就绪后再 apply 任何 Kueue CR，否则会 `connection refused`。可以看 endpoint：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system get endpointslice \
  -l kubernetes.io/service-name=kueue-webhook-service
```

装完后核对 integrations 是否已被收窄：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system get cm kueue-manager-config \
  -o jsonpath='{.data.controller_manager_config\.yaml}'
```

应能看到：

```
integrations:
  frameworks:
  - "batch/job"
  - "jobset.x-k8s.io/jobset"
  - "ray.io/rayjob"
  - "ray.io/raycluster"
  - "ray.io/rayservice"
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
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 apply -f manifests/worker-queues.yaml
resourceflavor.kueue.x-k8s.io/default-flavor created
clusterqueue.kueue.x-k8s.io/cluster-queue created
localqueue.kueue.x-k8s.io/user-queue created

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 apply -f manifests/worker-queues.yaml
resourceflavor.kueue.x-k8s.io/default-flavor created
clusterqueue.kueue.x-k8s.io/cluster-queue created
localqueue.kueue.x-k8s.io/user-queue created
```

如果报 webhook `connection refused`，等几秒再 `kubectl apply` 一次。

确认两边队列都在：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get clusterqueue,localqueue -A
NAME                                        COHORT   PENDING WORKLOADS
clusterqueue.kueue.x-k8s.io/cluster-queue            0

NAMESPACE   NAME                                   CLUSTERQUEUE    PENDING WORKLOADS   ADMITTED WORKLOADS
default     localqueue.kueue.x-k8s.io/user-queue   cluster-queue   0                   0

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 get clusterqueue,localqueue -A
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

这是**唯一**的跨集群连接机制：manager 拿一份 kubeconfig，用里面的 **token** 向 worker
的 API server 证明身份，然后才能 `watch Workload` / `create Job`。

下面以 `mk-worker1` 为例，完整敲一遍；`mk-worker2` 同样做，只改 context 和 Secret 名字。

### 5.1 在 worker 上创建受限 ServiceAccount

权限只覆盖 Kueue Workload + 本 demo 安装的三种框架。这个 ClusterRole 必须覆盖第 3 步
`integrations.frameworks` 里的每一个框架，否则 manager 的 watch 会被 403 拒绝。

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 apply -f manifests/worker-multikueue-rbac.yaml
serviceaccount/multikueue-sa created
clusterrole.rbac.authorization.k8s.io/multikueue-sa-role created
clusterrolebinding.rbac.authorization.k8s.io/multikueue-sa-crb created
secret/multikueue-sa created
```

YAML 里显式声明了长期 token Secret（k8s 1.24 起不再自动给 SA 建 token）：

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

等几秒让 kube-controller-manager 把 token 填进 Secret，再确认非空：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n kueue-system get secret multikueue-sa \
  -o jsonpath='{.data.token}' | wc -c
```

### 5.2 取出 token 和 CA，拼出 kubeconfig

**kind 环境最大的坑：** `kind get kubeconfig` 给出的是 `https://127.0.0.1:<随机端口>`，
只在宿主机有效。manager 上的 Kueue Pod 跑在 docker 网络里，必须用 worker control-plane
容器在 `kind` 网上的 IP：

```console
gyliu-cary@Mac multikueue-minimal-demo % docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' mk-worker1-control-plane
172.19.0.3
```

kubeadm 会把这个 IP 写进 API server 证书 SAN，所以 TLS 照样校验，不需要
`insecure-skip-tls-verify`。

把 token、CA、这个 IP 写成一份 kubeconfig（token / CA 不要手抄，从 Secret 抽）：

```console
gyliu-cary@Mac multikueue-minimal-demo % TOKEN=$(kubectl --context kind-mk-worker1 -n kueue-system get secret multikueue-sa \
    -o jsonpath='{.data.token}' | base64 -d)
gyliu-cary@Mac multikueue-minimal-demo % CA=$(kubectl --context kind-mk-worker1 -n kueue-system get secret multikueue-sa \
    -o jsonpath='{.data.ca\.crt}')
gyliu-cary@Mac multikueue-minimal-demo % API_IP=$(docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' mk-worker1-control-plane)

gyliu-cary@Mac multikueue-minimal-demo % cat > /tmp/mk-worker1.kubeconfig <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: mk-worker1
    cluster:
      certificate-authority-data: ${CA}
      server: https://${API_IP}:6443
users:
  - name: multikueue-sa
    user:
      token: ${TOKEN}
contexts:
  - name: mk-worker1
    context:
      cluster: mk-worker1
      user: multikueue-sa
current-context: mk-worker1
EOF
```

生成出来长这样（token 已截断）：

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

`certificate-authority-data` 用来确认对面真是 w1 的 API server；`token` 用来证明调用方是
`multikueue-sa`。没有 token，worker 会 `401`，后面的 create/watch 都不会发生。

### 5.3 把 kubeconfig 存成 manager 上的 Secret

Kueue 从 Secret 的 `kubeconfig` 这个 key 读出远程 client：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system create secret generic \
  mk-worker1-secret --from-file=kubeconfig=/tmp/mk-worker1.kubeconfig
secret/mk-worker1-secret created
```

对 `mk-worker2` 重复 5.1～5.3：`apply` RBAC、拼 `/tmp/mk-worker2.kubeconfig`、创建
`mk-worker2-secret`。IP 用：

```console
gyliu-cary@Mac multikueue-minimal-demo % docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' mk-worker2-control-plane
172.19.0.4
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
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f manifests/manager-multikueue.yaml
resourceflavor.kueue.x-k8s.io/default-flavor created
clusterqueue.kueue.x-k8s.io/cluster-queue created
localqueue.kueue.x-k8s.io/user-queue created
admissioncheck.kueue.x-k8s.io/multikueue-check created
multikueueconfig.kueue.x-k8s.io/multikueue-config created
multikueuecluster.kueue.x-k8s.io/mk-worker1 created
multikueuecluster.kueue.x-k8s.io/mk-worker2 created
```

Kueue 会用第 5 步存的 Secret 去连 worker。等两边都 `Active`：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get multikueuecluster \
  -o custom-columns='CLUSTER:.metadata.name,ACTIVE:.status.conditions[?(@.type=="Active")].status,REASON:.status.conditions[?(@.type=="Active")].reason,MESSAGE:.status.conditions[?(@.type=="Active")].message'
CLUSTER      ACTIVE   REASON   MESSAGE
mk-worker1   True     Active   Connected
mk-worker2   True     Active   Connected

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get admissioncheck multikueue-check \
  -o custom-columns='CHECK:.metadata.name,ACTIVE:.status.conditions[?(@.type=="Active")].status,MESSAGE:.status.conditions[?(@.type=="Active")].message'
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

先清掉残留负载（三个集群都删，避免上次实验占着配额）：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
```

提交 3 个 Job（只打到 manager）：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f examples/jobs.yaml
job.batch/demo-job-1 created
job.batch/demo-job-2 created
job.batch/demo-job-3 created
```

等十几秒让 MultiKueue 分发，然后对照三个集群：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get jobs,pods
NAME                   STATUS    COMPLETIONS   DURATION   AGE
job.batch/demo-job-1   Running   0/1                      6s
job.batch/demo-job-2   Running   0/1           5s         6s
job.batch/demo-job-3   Running   0/1           4s         6s
No resources found in default namespace.    # ← manager 上没有 Pod

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get workloads \
  -o custom-columns='WORKLOAD:.metadata.name,ADMITTED:.status.conditions[?(@.type=="Admitted")].status,DISPATCHED-TO:.status.clusterName,MESSAGE:.status.admissionChecks[0].message'
WORKLOAD               ADMITTED   DISPATCHED-TO   MESSAGE
job-demo-job-1-a9067   <none>     <none>
job-demo-job-2-dd6ff   True       mk-worker2      The workload was admitted on "mk-worker2"
job-demo-job-3-53d6e   True       mk-worker1      The workload was admitted on "mk-worker1"

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get jobs,pods
NAME                   STATUS    COMPLETIONS   DURATION   AGE
job.batch/demo-job-3   Running   0/1           4s         4s
NAME               READY   STATUS    RESTARTS   AGE
demo-job-3-lhjdn   1/1     Running   0          4s

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get clusterqueue cluster-queue \
  -o custom-columns='CLUSTERQUEUE:.metadata.name,PENDING:.status.pendingWorkloads,ADMITTED:.status.admittedWorkloads'
CLUSTERQUEUE    PENDING   ADMITTED
cluster-queue   1         1

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get jobs,pods
NAME                   STATUS    COMPLETIONS   DURATION   AGE
job.batch/demo-job-2   Running   0/1           5s         5s
NAME               READY   STATUS    RESTARTS   AGE
demo-job-2-lhjct   1/1     Running   0          5s

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 get clusterqueue cluster-queue \
  -o custom-columns='CLUSTERQUEUE:.metadata.name,PENDING:.status.pendingWorkloads,ADMITTED:.status.admittedWorkloads'
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

同样先清掉残留，再只向 manager 提交 JobSet：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f examples/jobset.yaml
jobset.jobset.x-k8s.io/demo-jobset created
```

看 webhook 有没有打上 `managedBy`（YAML 里没有写这个字段）：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get jobset demo-jobset \
  -o jsonpath='{.metadata.name}{"  managedBy="}{.spec.managedBy}{"  suspend="}{.spec.suspend}{"\n"}'
demo-jobset  managedBy=kueue.x-k8s.io/multikueue  suspend=false
```

看被派到哪个 worker：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get workloads \
  -o custom-columns='WORKLOAD:.metadata.name,ADMITTED:.status.conditions[?(@.type=="Admitted")].status,DISPATCHED-TO:.status.clusterName,MESSAGE:.status.admissionChecks[0].message'
WORKLOAD                   ADMITTED   DISPATCHED-TO   MESSAGE
jobset-demo-jobset-0e211   True       mk-worker2      The workload was admitted on "mk-worker2"
```

manager 上没有 Pod、没有子 Job；真正的子 Job 只在胜者上：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get jobs,pods
No resources found in default namespace.

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get jobs,jobsets,pods
No resources found in default namespace.

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get jobs,jobsets,pods
NAME                              STATUS    COMPLETIONS   DURATION   AGE
job.batch/demo-jobset-workers-0   Running   0/1           2s         2s
job.batch/demo-jobset-workers-1   Running   0/1           2s         2s
NAME                                 TERMINALSTATE   RESTARTS   COMPLETED   SUSPENDED   AGE
jobset.jobset.x-k8s.io/demo-jobset                   0                      false       2s
NAME                            READY   STATUS              RESTARTS   AGE
demo-jobset-workers-0-0-p44m7   0/1     ContainerCreating   0          2s
demo-jobset-workers-1-0-9xqnm   0/1     ContainerCreating   0          2s
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

先清残留。Ray 镜像约 177MB（Kueue 测试用的精简镜像），不预载的话 Pod 会在
`ContainerCreating` 卡很久。**不要用 `kind load docker-image`**（多架构 attestation 会
报 `content digest ... not found`），改用单平台 archive：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found

gyliu-cary@Mac multikueue-minimal-demo % docker pull us-central1-docker.pkg.dev/k8s-staging-images/kueue/ray-project-mini:0.0.4
gyliu-cary@Mac multikueue-minimal-demo % docker save --platform linux/arm64 \
  us-central1-docker.pkg.dev/k8s-staging-images/kueue/ray-project-mini:0.0.4 -o /tmp/ray-mini.tar
gyliu-cary@Mac multikueue-minimal-demo % kind load image-archive /tmp/ray-mini.tar --name mk-worker1
gyliu-cary@Mac multikueue-minimal-demo % kind load image-archive /tmp/ray-mini.tar --name mk-worker2
```

Intel Mac 把 `--platform linux/arm64` 换成 `linux/amd64`。

提交 RayJob：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f examples/rayjob.yaml
rayjob.ray.io/demo-rayjob created
```

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get rayjob demo-rayjob \
  -o jsonpath='{.metadata.name}{"  managedBy="}{.spec.managedBy}{"  suspend="}{.spec.suspend}{"\n"}'
demo-rayjob  managedBy=kueue.x-k8s.io/multikueue  suspend=
```

看派到哪：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get workloads \
  -o custom-columns='WORKLOAD:.metadata.name,ADMITTED:.status.conditions[?(@.type=="Admitted")].status,DISPATCHED-TO:.status.clusterName,MESSAGE:.status.admissionChecks[0].message'
WORKLOAD                   ADMITTED   DISPATCHED-TO   MESSAGE
rayjob-demo-rayjob-a5a54   True       mk-worker2      The workload was admitted on "mk-worker2"
```

manager 上没有 Pod；RayCluster 只在胜者上出现：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get pods
No resources found in default namespace.

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get rayjob,pods
NAME                        JOB STATUS   DEPLOYMENT STATUS   RAY CLUSTER NAME    START TIME             END TIME   AGE
rayjob.ray.io/demo-rayjob                Initializing        demo-rayjob-mm7f9   2026-08-14T14:55:38Z              2s
NAME                                         READY   STATUS   RESTARTS   AGE
demo-rayjob-mm7f9-head-7zzgz                 0/1     Running  0          2s
demo-rayjob-mm7f9-small-group-worker-llslc   0/1     Init:0/1 0          2s
```

等任务结束（可能一两分钟）。manager 上的 RayJob status 是从 worker **同步回来**的：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get rayjob demo-rayjob \
  -o custom-columns='NAME:.metadata.name,JOB-STATUS:.status.jobStatus,DEPLOYMENT:.status.jobDeploymentStatus,MANAGED-BY:.spec.managedBy'
NAME          JOB-STATUS   DEPLOYMENT   MANAGED-BY
demo-rayjob   SUCCEEDED    Running      kueue.x-k8s.io/multikueue

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get workloads \
  -o custom-columns='WORKLOAD:.metadata.name,FINISHED:.status.conditions[?(@.type=="Finished")].status,RAN-ON:.status.clusterName'
WORKLOAD                   FINISHED   RAN-ON
rayjob-demo-rayjob-a5a54   <none>     mk-worker2
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

必须是 `172.x.x.x` 这种 docker 网络内地址。如果是 `127.0.0.1`，删掉 Secret 后按第 5 步用
control-plane 容器 IP 重新拼 kubeconfig 再 `kubectl create secret`。

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
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get jobs,jobsets,rayjobs,workloads,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get multikueuecluster,admissioncheck
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get jobs,jobsets,rayjobs,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get clusterqueue cluster-queue
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get jobs,jobsets,rayjobs,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 get clusterqueue cluster-queue
```

---

## 清理

清掉工作负载但保留集群（方便反复做实验）：

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
```

删掉整个环境：

```console
gyliu-cary@Mac multikueue-minimal-demo % kind delete cluster --name mk-manager
Deleting cluster "mk-manager" ...
gyliu-cary@Mac multikueue-minimal-demo % kind delete cluster --name mk-worker1
Deleting cluster "mk-worker1" ...
gyliu-cary@Mac multikueue-minimal-demo % kind delete cluster --name mk-worker2
Deleting cluster "mk-worker2" ...
```

或一条：

```console
gyliu-cary@Mac multikueue-minimal-demo % kind delete clusters mk-manager mk-worker1 mk-worker2
```
