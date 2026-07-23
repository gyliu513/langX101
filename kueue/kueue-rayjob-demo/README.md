# Kueue + KubeRay：RayJob 批处理排队 Demo（手把手教程）

一个**从零到跑通**的端到端示例：在本地 **kind** 集群上，由 **Kueue** 对
**RayJob** 做配额排队与准入。**无需 GPU，全部在 CPU 上运行**
（Ray 镜像是 amd64+arm64 多架构，Apple Silicon 也能原生跑）。

本文档的每一步都附有**真实命令和真实输出**（在 macOS/Apple Silicon +
Docker Desktop 上实跑记录），照着敲即可完整复现。

三个组件的分工：

| 组件 | 作用 |
|------|------|
| **kind** | 本地 Kubernetes 集群（1 control-plane + 2 worker 节点） |
| **KubeRay operator** | 监听 RayJob CRD：为每个 RayJob 创建**临时 Ray 集群**（head + workers）和提交任务的 submitter Pod，任务结束后删掉集群 |
| **Kueue** | 通过控制 RayJob 的 `spec.suspend` 字段做**配额准入**：head + workers + submitter 的资源必须一次性全部放得下才放行 |

任务本身是 **Monte Carlo 估算 π**：24 个 `@ray.remote` task 撒到 2 个
worker Pod 上并行执行，最后打印每个 Pod 跑了几个 task——直观看到计算
真的分布在了多个 Pod 上。

---

## 拓扑与生命周期

```
kind 集群 (kueue-rayjob-demo)
 ├─ control-plane
 ├─ worker-1 ─┐        RayJob "rayjob-pi"（Kueue 准入后由 KubeRay 展开）
 └─ worker-2 ─┴─►  ┌──────────────────────────────────────────────────┐
                   │  head Pod      1 CPU / 5Gi   （GCS + Dashboard，   │
                   │                num-cpus=0，不跑计算任务）           │
                   │  worker Pod    1 CPU / 2Gi   ×2 （跑计算任务）      │
                   │  submitter Pod 0.5 CPU / 200Mi（ray job submit）   │
                   └──────────────────────────────────────────────────┘
                     Kueue 计费合计：3.5 CPU / ~9.2Gi
                     （ClusterQueue 配额：4 CPU / 10Gi → 同时只放得下 1 个）
```

```
kubectl apply RayJob
   │
   ▼
Kueue：创建 Workload，spec.suspend=true（排队）
   │  ClusterQueue 有 3.5 CPU / 9.2Gi 空闲？
   ▼
Kueue：admit → spec.suspend=false
   │
   ▼
KubeRay operator：创建临时 RayCluster（1 head + 2 worker）+ submitter Pod
   │
   ▼
submitter：ray job submit -- python sample_code.py（driver 跑在 head 上）
   │
   ▼
任务结束 → shutdownAfterJobFinishes=true → RayCluster 被删除
   │
   ▼
Kueue：配额释放，队列中下一个 workload 被自动 admit
```

这就是 RayJob 和"裸集群" RayCluster 的本质区别：**用完即焚，配额流转**。

---

## 前置条件

- `docker`（已启动，建议给 Docker Desktop 至少 6 CPU / 12Gi 内存）
- `kind`
- `kubectl`
- `helm`（用于安装 KubeRay operator）

版本（实测验证过的组合）：**KubeRay chart 1.6.2**、**Kueue v0.18.0**、
**Ray 2.46.0**。Kueue v0.18 **默认启用** `ray.io/rayjob` 集成，无需改配置。

检查工具是否齐全：

```bash
$ which docker kind kubectl helm
/usr/local/bin/docker
/usr/local/bin/kind
/usr/local/bin/kubectl
/opt/homebrew/bin/helm
```

---

## 两种跑法

- **一键脚本**（急着看效果）：`./setup.sh && ./run.sh`，看完 `./cleanup.sh`。
- **手把手逐步执行**（推荐初学者）：跟着下面第 1~10 步走，每一步都解释了
  在干什么、以及输出里该看哪个字段。

---

## 第 1 步：创建 kind 集群

kind 会用 3 个 Docker 容器模拟出一个 3 节点的 Kubernetes 集群
（1 个 control-plane + 2 个 worker）。

```bash
cd kueue-rayjob-demo
kind create cluster --config kind-cluster.yaml
```

输出：

```
Creating cluster "kueue-rayjob-demo" ...
 ✓ Ensuring node image (kindest/node:v1.35.0) 🖼
 ✓ Preparing nodes 📦 📦 📦
 ✓ Writing configuration 📜
 ✓ Starting control-plane 🕹️
 ✓ Installing CNI 🔌
 ✓ Installing StorageClass 💾
 ✓ Joining worker nodes 🚜
Set kubectl context to "kind-kueue-rayjob-demo"
```

确认 3 个节点都在（刚建好时 `NotReady` 是正常的，等几十秒就绪）：

```bash
$ kubectl get nodes
NAME                              STATUS   ROLES           AGE   VERSION
kueue-rayjob-demo-control-plane   Ready    control-plane   1m    v1.35.0
kueue-rayjob-demo-worker          Ready    <none>          1m    v1.35.0
kueue-rayjob-demo-worker2         Ready    <none>          1m    v1.35.0
```

---

## 第 2 步：预载 Ray 镜像到 kind 节点

Ray 镜像约 800MB（压缩后）。如果不预载，每个 kind 节点都会各自从
Docker Hub 拉一遍。先拉到本机，再灌进两个 worker 节点：

```bash
# 本地已有镜像可跳过 pull（Docker Desktop 对已存在镜像再 pull 有时会长时间无输出）
docker image inspect rayproject/ray:2.46.0 >/dev/null 2>&1 || docker pull rayproject/ray:2.46.0
docker save rayproject/ray:2.46.0 -o /tmp/ray.tar
for node in $(kind get nodes --name kueue-rayjob-demo | grep -v control-plane); do
  docker exec --privileged -i "$node" \
    ctr --namespace=k8s.io images import --digests --snapshotter=overlayfs - < /tmp/ray.tar
done
rm /tmp/ray.tar
```

输出（每个节点一次）：

```
docker.io/rayproject/ray:2.46.0         	saved
application/vnd.oci.image.index.v1+json sha256:764d7d4b...
Importing	elapsed: 12.2s
```

> **为什么不用 `kind load docker-image`？** 当 Docker 开启 containerd
> image store 时（新版 Docker Desktop 默认开启），`kind load` 内部的
> `ctr import --all-platforms` 会因多架构 attestation manifest 报错
> `ctr: content digest ... not found`。上面这种手动 import（不带
> `--all-platforms`）在两种模式下都能工作。control-plane 节点带污点、
> 不会调度 Ray Pod，所以跳过。

确认镜像已进节点：

```bash
$ docker exec kueue-rayjob-demo-worker crictl images | grep rayproject
docker.io/rayproject/ray    2.46.0    8a6d155dff140    845MB
```

---

## 第 3 步：安装 KubeRay operator

KubeRay operator 是一个普通的 Deployment，它注册 RayCluster / RayJob /
RayService 三个 CRD 并负责调和它们。用 Helm 安装：

```bash
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm repo update kuberay
helm upgrade --install kuberay-operator kuberay/kuberay-operator \
  --version 1.6.2 --namespace kuberay-system --create-namespace
kubectl wait --for=condition=Available --timeout=300s \
  -n kuberay-system deploy/kuberay-operator
```

验证 operator 在跑、CRD 已注册：

```bash
$ kubectl get pods -n kuberay-system
NAME                                READY   STATUS    RESTARTS   AGE
kuberay-operator-5dff8cd9d5-5mbq6   1/1     Running   0          1m

$ kubectl get crd | grep ray.io
rayclusters.ray.io
raycronjobs.ray.io
rayjobs.ray.io
rayservices.ray.io
```

（KubeRay 1.6 有 4 个 CRD，`raycronjobs` 是 1.6 新增的定时任务类型，
本 demo 不用它。）

---

## 第 4 步：安装 Kueue

```bash
kubectl apply --server-side -f \
  "https://github.com/kubernetes-sigs/kueue/releases/download/v0.18.0/manifests.yaml"
kubectl wait --for=condition=Available --timeout=300s \
  -n kueue-system deploy/kueue-controller-manager
```

验证：

```bash
$ kubectl get pods -n kueue-system
NAME                                        READY   STATUS    RESTARTS   AGE
kueue-controller-manager-5cc7bd8db4-jxnkq   1/1     Running   0          1m
```

> Kueue 的 webhook 在 Deployment `Available` 之后还要预热十几秒才开始
> 服务，如果下一步 apply 报 webhook 连接错误，等几秒重试即可。

---

## 第 5 步：创建 Kueue 配额对象

这是**管理员视角**的一步，建立三层结构：

- **ResourceFlavor**：资源的"型号"（本 demo 用一个不区分节点的默认型号）；
- **ClusterQueue**：集群级配额池——**4 CPU / 10Gi**；
- **LocalQueue**：namespace 级的提交入口，用户的 RayJob 都投到这里。

```bash
kubectl apply -f 00-kueue-resources.yaml
```

```
resourceflavor.kueue.x-k8s.io/default-flavor created
clusterqueue.kueue.x-k8s.io/rayjob-cluster-queue created
localqueue.kueue.x-k8s.io/rayjob-user-queue created
```

验证：

```bash
$ kubectl get clusterqueue,localqueue
NAME                                               COHORT   PENDING WORKLOADS
clusterqueue.kueue.x-k8s.io/rayjob-cluster-queue            0

NAME                                          CLUSTERQUEUE           PENDING WORKLOADS   ADMITTED WORKLOADS
localqueue.kueue.x-k8s.io/rayjob-user-queue   rayjob-cluster-queue   0                   0
```

**配额是怎么算的？** 一个 RayJob 在 Kueue 里被拆成 3 个 PodSet 计费：

| PodSet | 请求 |
|--------|------|
| head | 1 CPU + 5Gi |
| cpu-workers ×2 | 2 CPU + 4Gi |
| submitter | 0.5 CPU + 200Mi |
| **合计** | **3.5 CPU + ~9.2Gi** |

注意 **submitter Pod 也计入配额**——这是实测踩过的坑：配额给 8Gi 时任务
恰好差 200Mi 一直 `Suspended`。

---

## 第 6 步：提交 RayJob（用户视角）

从这里开始是**用户视角**：只需要在 RayJob 的 label 里写上队列名。

```yaml
metadata:
  name: rayjob-pi
  labels:
    kueue.x-k8s.io/queue-name: rayjob-user-queue   # 没有这行，Kueue 完全不管它
```

提交 driver 脚本（ConfigMap）和 RayJob：

```bash
kubectl apply -f 01-ray-code-configmap.yaml
kubectl apply -f 02-rayjob.yaml
```

```
configmap/rayjob-pi-code created
rayjob.ray.io/rayjob-pi created
```

立刻看 Kueue 的反应——它为 RayJob 创建了一个 Workload 对象并**整体预留**
了配额（`ADMITTED=True`）：

```bash
$ kubectl get workloads -o wide
NAME                     QUEUE               RESERVED IN            ADMITTED   FINISHED   AGE
rayjob-rayjob-pi-665b4   rayjob-user-queue   rayjob-cluster-queue   True                  5s

$ kubectl get rayjob
NAME        JOB STATUS   DEPLOYMENT STATUS   RAY CLUSTER NAME   START TIME             AGE
rayjob-pi                Initializing        rayjob-pi-5hsrj    2026-07-23T16:00:03Z   5s
```

关键字段解读：

- Workload 的 `ADMITTED=True`：配额够，Kueue 已把 `spec.suspend` 翻成
  `false`，放行；
- RayJob 的 `DEPLOYMENT STATUS: Initializing`：KubeRay 接手，正在创建
  临时集群 `rayjob-pi-5hsrj`。

如果配额不够，这里会看到 RayJob 停在 `Suspended`、Workload 的
`ADMITTED` 为空——第 9 步会故意制造这个场景。

---

## 第 7 步：观察临时 Ray 集群拉起

```bash
$ kubectl get pods -o wide
NAME                                       READY   STATUS    AGE   NODE
rayjob-pi-5hsrj-cpu-workers-worker-dsl7b   0/1     Running   12s   kueue-rayjob-demo-worker2
rayjob-pi-5hsrj-cpu-workers-worker-k8h7v   0/1     Running   12s   kueue-rayjob-demo-worker2
rayjob-pi-5hsrj-head-qktbh                 1/1     Running   12s   kueue-rayjob-demo-worker
```

- **head Pod**：跑 `ray start --head`，内含 GCS（集群元数据）、Dashboard
  （8265 端口，也是任务提交 API）；
- **worker Pod**：有个 init 容器 `wait-gcs-ready` 先等 head 就绪（此时
  `READY 0/1` 正常），然后 `ray start --address=<head>:6379` 注册进集群；
- head Ready 之后，KubeRay 会再创建一个 **submitter Pod**（K8s Job），
  它执行 `ray job submit --address http://<head-svc>:8265 -- python
  /home/ray/samples/sample_code.py`。

等 head 就绪：

```bash
kubectl wait --for=condition=Ready pod -l ray.io/node-type=head --timeout=600s
```

---

## 第 8 步：查看任务日志

driver 的输出通过 submitter Pod 中转，直接跟它的日志即可：

```bash
kubectl logs -f -l job-name=rayjob-pi
```

真实输出（节选）：

```
INFO cli.py:41 -- Job submission server address: http://rayjob-pi-5hsrj-head-svc.default.svc.cluster.local:8265
SUCC cli.py:66 -- Job 'rayjob-pi-8gxpr' submitted successfully
INFO worker.py:1694 -- Connecting to existing Ray cluster at address: 10.244.2.11:6379...
=== Ray cluster resources ===
{'object_store_memory': 805306368.0, 'CPU': 2.0, 'memory': 9663676416.0,
 'node:10.244.1.10': 1.0, 'node:10.244.1.11': 1.0, 'node:10.244.2.11': 1.0, ...}

=== Result ===
pi ~= 3.141989  (24 tasks x 200,000 samples, 0.8s)

=== Task distribution across pods ===
  rayjob-pi-5hsrj-cpu-workers-worker-dsl7b: 12 tasks
  rayjob-pi-5hsrj-cpu-workers-worker-k8h7v: 12 tasks

SUCCESS
SUCC cli.py:66 -- Job 'rayjob-pi-8gxpr' succeeded
```

解读：

- `CPU: 2.0`：集群总共 2 个逻辑 CPU——head 配了 `num-cpus: "0"`
  （最佳实践：head 只当控制面），所以只有 2 个 worker 各出 1 CPU；
- 24 个 task 分布在两个 worker 上、head 上 0 个。每次运行的分布会略有
  浮动（比如 12/12 或 14/10），取决于调度时机，属正常现象。

---

## 第 9 步：任务完成与集群自动回收

```bash
$ kubectl get rayjob
NAME        JOB STATUS   DEPLOYMENT STATUS   RAY CLUSTER NAME   START TIME             END TIME               AGE
rayjob-pi   SUCCEEDED    Complete            rayjob-pi-5hsrj    2026-07-23T16:00:03Z   2026-07-23T16:00:33Z   31s
```

任务结束约 30 秒后（`ttlSecondsAfterFinished: 30`），临时 RayCluster 被
删除，Workload 标记为已完成、配额释放：

```bash
$ kubectl get raycluster
No resources found in default namespace.

$ kubectl get workloads -o wide
NAME                     QUEUE               RESERVED IN            ADMITTED   FINISHED   AGE
rayjob-rayjob-pi-665b4   rayjob-user-queue   rayjob-cluster-queue   True       True       71s
```

`FINISHED=True` + RayCluster 消失 = **配额已还给队列**。

---

## 第 10 步：排队实验（Kueue 的核心价值）

配额（4 CPU / 10Gi）只放得下一个 RayJob（3.5 CPU / 9.2Gi）。趁第一个
还在跑时提交第二个：

```bash
kubectl delete rayjob rayjob-pi        # 先删掉第 9 步已完成的那个！
sleep 5
kubectl apply -f 02-rayjob.yaml        # 重新提交第一个（开始跑）
sleep 10
kubectl apply -f 03-rayjob-second.yaml # 趁第一个在跑，提交第二个
```

> **为什么要先 delete？** 已经 `Complete` 的 RayJob 再 apply 一遍**不会
> 重跑**（状态保持 Complete、不占配额），第二个任务会被直接放行，
> 你就看不到排队现象了。

第二个进不来，**排队**（真实输出）：

```bash
$ kubectl get workloads -o wide
NAME                       QUEUE               RESERVED IN            ADMITTED   FINISHED   AGE
rayjob-rayjob-pi-2-e6da8   rayjob-user-queue                                                8s
rayjob-rayjob-pi-ec65a     rayjob-user-queue   rayjob-cluster-queue   True                  21s

$ kubectl get rayjob
NAME          JOB STATUS   DEPLOYMENT STATUS   RAY CLUSTER NAME   START TIME             AGE
rayjob-pi                  Running             rayjob-pi-rvqrc    2026-07-23T16:02:31Z   21s
rayjob-pi-2                Suspended                              2026-07-23T16:02:43Z   8s
```

问 Kueue 为什么不放行：

```bash
$ kubectl describe workload rayjob-rayjob-pi-2-e6da8
...
Message:  couldn't assign flavors to pod set head: insufficient unused quota
          for cpu in flavor default-flavor, 500m more needed, insufficient
          unused quota for memory in flavor default-flavor, 4296Mi more needed; ...
Reason:   Pending
```

然后**什么都不用做**，等第一个跑完。看两个任务的时间戳：

```bash
$ kubectl get rayjob
NAME          JOB STATUS   DEPLOYMENT STATUS   START TIME             END TIME
rayjob-pi     SUCCEEDED    Complete            2026-07-23T16:02:31Z   2026-07-23T16:03:00Z
rayjob-pi-2   SUCCEEDED    Complete            2026-07-23T16:03:01Z   2026-07-23T16:03:31Z
```

第一个 **16:03:00** 结束，第二个 **16:03:01** 被自动放行——释放配额的
下一秒。这就是 RayJob + Kueue 的核心闭环：
**用完即焚 → 配额流转 → 队列自动前进**。

---

## 第 11 步：清理

```bash
kind delete cluster --name kueue-rayjob-demo
```

---

## 文件说明

| 文件 | 内容 |
|------|------|
| `kind-cluster.yaml` | 1 control-plane + 2 worker 的 kind 集群 |
| `00-kueue-resources.yaml` | ResourceFlavor / ClusterQueue（4 CPU / 10Gi）/ LocalQueue |
| `01-ray-code-configmap.yaml` | driver 脚本（Monte Carlo 估算 π），挂载到 head Pod |
| `02-rayjob.yaml` | RayJob 本体：queue-name label + 临时集群 spec |
| `03-rayjob-second.yaml` | 第二个 RayJob，用于第 10 步排队实验 |
| `setup.sh` | 一键完成第 1~5 步 |
| `run.sh` | 一键完成第 6~9 步 |
| `cleanup.sh` | 第 11 步 |

---

## 关键字段速查

- `metadata.labels."kueue.x-k8s.io/queue-name"` —— 提交到哪个 LocalQueue；
  **没有这个 label，Kueue 完全不管这个 RayJob**。
- `spec.suspend` —— Kueue 的控制点：排队时 `true`，admit 后被翻成
  `false`。**不要手工改它**。
- `spec.shutdownAfterJobFinishes: true` —— Kueue 场景下必须为 true：
  临时集群用完即删配额才会释放（RayJob 不能复用已有 RayCluster）。
- `resources.requests` —— Kueue 按 head + worker groups + **submitter**
  的 requests 计配额；`limits` 被 Ray 用来推导节点资源。
- `rayStartParams.num-cpus: "0"`（head）—— head 不跑计算任务，只当控制面。
- worker group 上限 **17** 个（一个 Workload 最多 18 个 PodSet，head 占 1）。

---

## 踩坑记录（实测遇到的真实问题）

以下问题全部在本 demo 开发过程中真实踩到，方案已固化进 YAML/脚本：

1. **`docker pull` 长时间无输出（本地已有镜像）**
   Docker Desktop 对已存在的镜像再执行 `docker pull` 时，可能长时间
   向 registry 校验 metadata 而无任何输出。本地已有
   `rayproject/ray:2.46.0` 时跳过 pull 即可（`setup.sh` 已自动检测）。

2. **`kind load docker-image` 报 `ctr: content digest ... not found`**
   Docker 开启 containerd image store 后的已知问题（`--all-platforms`
   与多架构 attestation 冲突）。解法见第 2 步：手动 `ctr import`。

3. **head Pod OOMKilled（2Gi/3Gi 都不够）**
   Ray 2.46 的 head 空载就要 **~3.8GB**（GCS + Dashboard 会 spawn 约
   10 个各 ~300MB 的 python 子进程，实测 `memory.peak` 3.78GB）。
   head 至少给 **5Gi**。

4. **`ValueError: Attempting to cap object store memory usage at ... bytes`**
   Ray 自动按 cgroup 的 `memory.current`（**含 page cache**）估算可用
   内存；镜像刚解压完 cache 把额度占满，object store 只分到 3MB（低于
   75MB 下限）直接崩溃。解法：`rayStartParams` 里显式
   `object-store-memory: "268435456"`。

5. **任务被 Ray 杀掉：`Task was killed due to the node running low on memory`**
   head 给 4Gi 时空载 3.81/4.00GB=95.2%，恰好越过 Ray 内存监控的 95%
   kill 阈值，job driver 一起被杀。解法同第 2 条：head 5Gi 留出余量。

6. **RayJob 一直 Suspended，`describe workload` 说差 200Mi**
   Kueue 把 **submitter Pod（0.5 CPU / 200Mi）也算进配额**，按
   head+workers 算的 8Gi 配额不够。配额按 3 个 PodSet 合计留余量。

---

## 切换到 GPU

1. kind 换成有 GPU 的真实集群（或 kind + GPU device plugin）。
2. `00-kueue-resources.yaml`：`coveredResources` 加 `"nvidia.com/gpu"`
   并给配额；ResourceFlavor 加 GPU 节点的 `nodeLabels`。
3. `02-rayjob.yaml`：worker 容器 requests/limits 加 `nvidia.com/gpu: "1"`，
   镜像换 `rayproject/ray:2.46.0-gpu`。
4. Ray 自动注册 GPU，task 用 `@ray.remote(num_gpus=1)` 声明。
