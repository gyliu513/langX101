# MultiKueue + OCM + JobSet 演示（Kueue v0.16.4）

> English version: [README.md](./README.md)

用两个本地 `kind` 集群，借助 **Open Cluster Management (OCM)** 完成集群注册与凭据下发，
再用 **Kueue MultiKueue** 实现跨集群作业分发。提交到 **hub** 的 `JobSet` 由 Kueue 接纳，
但**真正在 managed 集群上执行**，执行状态再回传到 hub。

本 README 是一份**从零开始、可直接复制粘贴的操作手册**：从没有任何集群开始，逐条命令
带真实输出，最终提交并跑完一个 MultiKueue JobSet。

---

## 架构

```
┌─────────────────────────────┐   OCM 注册        ┌─────────────────────────────┐
│  kind: hub  (Manager)       │◀────────────────▶│  kind: managed (Worker)     │
│  172.19.0.2                 │                   │  172.19.0.3                 │
│  - OCM Hub                  │                   │  - OCM Klusterlet (cluster1)│
│  - managed-serviceaccount   │   token 同步      │  - SA kueue-multikueue      │
│    addon manager            │◀── 回传 hub ──────│    (+ MultiKueue RBAC)       │
│  - Kueue v0.16.4 (MultiKueue)│                  │  - Kueue v0.16.4            │
│  - JobSet v0.8.1 (CRD)      │                   │  - JobSet v0.8.1 (跑 Pod)   │
│  - MultiKueueConfig/Cluster │                   │                             │
│  - AdmissionCheck           │   hub→managed     │                             │
│  - ClusterQueue + 准入检查      经 kubeconfig    │  - ClusterQueue (普通)       │
└─────────────────────────────┘   secret          └─────────────────────────────┘
   提交 JobSet → hub 接纳 → 分发到 managed 执行 → 状态回传 hub
```

| 组件 | 版本 |
|---|---|
| Kueue | **v0.16.4**（MultiKueue 自 0.9 起为默认开启的 Beta 门控） |
| JobSet | **v0.8.1**（`jobset.x-k8s.io/v1alpha2`） |
| OCM `clusteradm` | v1.3.1 |
| OCM managed-serviceaccount addon（Helm chart） | 0.10.0 |
| Kueue API 存储版本 | `kueue.x-k8s.io/v1beta2` |

---

## 第 0 步 — 前置条件

需要 `docker`、`kind`、`kubectl`、`helm`，以及 OCM 的 `clusteradm`（第 1 步安装）。
本演示基于 **arm64 macOS + Docker Desktop**。

```console
gyliu-cary@Mac multikueue-ocm-demo % kind version
kind v0.31.0 go1.25.5 darwin/arm64
gyliu-cary@Mac multikueue-ocm-demo % kubectl version --client | head -1
Client Version: v1.32.2
gyliu-cary@Mac multikueue-ocm-demo % helm version --short
v4.2.0+g0646808
gyliu-cary@Mac multikueue-ocm-demo % docker version --format '{{.Server.Version}}'
28.4.0
```

---

## 第 1 步 — 安装 OCM `clusteradm` CLI

Homebrew **没有** `clusteradm`，直接下载 darwin/arm64 的 release 二进制。

```console
gyliu-cary@Mac multikueue-ocm-demo % TAG=$(curl -fsSL https://api.github.com/repos/open-cluster-management-io/clusteradm/releases/latest | grep -m1 '"tag_name"' | cut -d'"' -f4)
gyliu-cary@Mac multikueue-ocm-demo % curl -fsSL "https://github.com/open-cluster-management-io/clusteradm/releases/download/${TAG}/clusteradm_darwin_arm64.tar.gz" -o /tmp/clusteradm.tar.gz
gyliu-cary@Mac multikueue-ocm-demo % tar xzf /tmp/clusteradm.tar.gz -C /tmp && mv /tmp/clusteradm /opt/homebrew/bin/clusteradm
gyliu-cary@Mac multikueue-ocm-demo % clusteradm version | head -1
clusteradm	version	:v1.3.1-0-g90bdc31
```

---

## 第 1.5 步 — 清理旧环境（可选）

如果之前已经创建过 `hub` / `managed` kind 集群，先删掉，避免端口、CSR、Secret 残留干扰。

```console
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name hub 2>/dev/null || true
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name managed 2>/dev/null || true
gyliu-cary@Mac multikueue-ocm-demo % kind get clusters
No kind clusters found.
```

同时删除上次运行生成的本地凭据（已在 `.gitignore` 中）：

```console
gyliu-cary@Mac multikueue-ocm-demo % rm -f hub-ca.crt worker1.kubeconfig
```

---

## 第 2 步 — 创建两个 kind 集群

创建后节点可能短暂显示 `NotReady`，等两边都变成 `Ready` 再继续。

```console
gyliu-cary@Mac multikueue-ocm-demo % kind create cluster --name hub
Creating cluster "hub" ...
 ✓ Ensuring node image (kindest/node:v1.35.0) 🖼
 ✓ Preparing nodes 📦
 ✓ Writing configuration 📜
 ✓ Starting control-plane 🕹️
 ✓ Installing CNI 🔌
 ✓ Installing StorageClass 💾
Set kubectl context to "kind-hub"

gyliu-cary@Mac multikueue-ocm-demo % kind create cluster --name managed
Creating cluster "managed" ...
 ✓ Ensuring node image (kindest/node:v1.35.0) 🖼
 ✓ Preparing nodes 📦
 ✓ Writing configuration 📜
 ✓ Starting control-plane 🕹️
 ✓ Installing CNI 🔌
 ✓ Installing StorageClass 💾
Set kubectl context to "kind-managed"

gyliu-cary@Mac multikueue-ocm-demo % kind get clusters
hub
managed
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get nodes
NAME                STATUS   ROLES           AGE   VERSION
hub-control-plane   Ready    control-plane   31m   v1.35.0
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get nodes
NAME                    STATUS   ROLES           AGE   VERSION
managed-control-plane   Ready    control-plane   29m   v1.35.0
```

### 网络拓扑（理解下面两个坑的关键）

两个 kind 容器在同一个 `kind` docker 网络里，彼此可通过 IP **以及容器名**（docker 内嵌
DNS）互访；但 macOS 宿主机**无法路由**到这些 IP。

```console
gyliu-cary@Mac multikueue-ocm-demo % docker network inspect kind -f '{{range .Containers}}{{.Name}} => {{.IPv4Address}}{{println}}{{end}}'
hub-control-plane => 172.19.0.2/16
managed-control-plane => 172.19.0.3/16
```

---

## 第 3 步 — 初始化 OCM hub

```console
gyliu-cary@Mac multikueue-ocm-demo % clusteradm init --context kind-hub --wait
Preflight check: HubApiServer check Passed with 0 warnings and 0 errors
Preflight check: cluster-info check Passed with 0 warnings and 0 errors
The multicluster hub control plane has been initialized successfully!
...
    clusteradm join --hub-token <token> --hub-apiserver https://127.0.0.1:59677 --wait --cluster-name <cluster_name>
```

`init` 给出的 join 命令里 hub 地址是 `https://127.0.0.1:<端口>`（宿主机端口），记下这个端口，
我们仅用它通过宿主机侧的预检。

---

## 第 4 步 — 让 managed 加入 hub（⚠️ 坑 #1）

**问题：** macOS 上 `clusteradm join` 的预检会**从宿主机** dial hub，而宿主机路由不到
docker 内网 IP `172.19.0.2:6443` → join 超时。

**解决：** 用宿主机可达的 `https://127.0.0.1:<端口>`（让预检通过）**外加
`--force-internal-endpoint-lookup`**，使 klusterlet 实际用 `https://hub-control-plane:6443`
连接（docker DNS，且该名字在 hub 证书 SAN 中）。

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > hub-ca.crt
gyliu-cary@Mac multikueue-ocm-demo % HUB_PORT=$(kubectl --context kind-hub config view --minify -o jsonpath='{.clusters[0].cluster.server}' | sed 's#.*:##')
gyliu-cary@Mac multikueue-ocm-demo % TOKEN=$(clusteradm get token --context kind-hub | grep -o 'token=[^ ]*' | head -1 | cut -d= -f2)
gyliu-cary@Mac multikueue-ocm-demo % clusteradm join \
    --hub-token "$TOKEN" \
    --hub-apiserver "https://127.0.0.1:${HUB_PORT}" \
    --ca-file hub-ca.crt \
    --force-internal-endpoint-lookup \
    --cluster-name cluster1 \
    --context kind-managed
Preflight check: HubKubeconfig check Passed with 0 warnings and 0 errors
Preflight check: DeployMode Check Passed with 0 warnings and 0 errors
Preflight check: ClusterName Check Passed with 0 warnings and 0 errors
Please log onto the hub cluster and run the following command:

    clusteradm accept --clusters cluster1
```

确认 klusterlet 的 bootstrap kubeconfig 指向 docker DNS 名（而非 127.0.0.1）：

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get secret -n open-cluster-management-agent bootstrap-hub-kubeconfig -o jsonpath='{.data.kubeconfig}' | base64 -d | grep server
    server: https://hub-control-plane:6443
```

---

## 第 5 步 — 在 hub 上接受注册

`clusteradm join` 只是**发起**注册，hub 还需要批准 CSR。如果立刻执行 `accept` 报
`managedcluster cluster1 not found` 或 `no csr is approved yet`，等几秒后重试即可——
klusterlet 需要一点时间才能在 hub 上创建 CSR。

```console
gyliu-cary@Mac multikueue-ocm-demo % clusteradm accept --clusters cluster1 --context kind-hub
Starting approve csrs for the cluster cluster1
CSR cluster1-89l55 approved
set hubAcceptsClient to true for managed cluster cluster1
 Your managed cluster cluster1 has joined the Hub successfully.

gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get managedclusters
NAME       HUB ACCEPTED   MANAGED CLUSTER URLS                 JOINED   AVAILABLE   AGE
cluster1   true           https://managed-control-plane:6443   True     True        20m
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get pods -n open-cluster-management-agent
NAME                                             READY   STATUS    RESTARTS   AGE
klusterlet-registration-agent-6f8894f78d-qxxfg   1/1     Running   0          20m
klusterlet-work-agent-679f75967d-nl9ck           1/1     Running   0          19m
```

> `JOINED=True` 在 accept 后很快出现；`AVAILABLE=True` 可能还要再等约一分钟（work agent
> 启动中）。后续步骤**不必**等 `AVAILABLE`。

---

## 第 6 步 — 两个集群都安装 JobSet v0.8.1

Kueue v0.16.4 需要 JobSet API（`jobset.x-k8s.io/v1alpha2`），这里固定用 v0.8.1。

```console
gyliu-cary@Mac multikueue-ocm-demo % curl -fsSL -o manifests/jobset-v0.8.1.yaml https://github.com/kubernetes-sigs/jobset/releases/download/v0.8.1/manifests.yaml
gyliu-cary@Mac multikueue-ocm-demo % for ctx in kind-hub kind-managed; do kubectl --context $ctx apply --server-side -f manifests/jobset-v0.8.1.yaml; done
...
deployment.apps/jobset-controller-manager serverside-applied
...
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get crd jobsets.jobset.x-k8s.io -o jsonpath='{.spec.versions[*].name}'
v1alpha2
```

---

## 第 7 步 — 两个集群都安装 Kueue v0.16.4

```console
gyliu-cary@Mac multikueue-ocm-demo % curl -fsSL -o manifests/kueue-v0.16.4.yaml https://github.com/kubernetes-sigs/kueue/releases/download/v0.16.4/manifests.yaml
gyliu-cary@Mac multikueue-ocm-demo % for ctx in kind-hub kind-managed; do kubectl --context $ctx apply --server-side -f manifests/kueue-v0.16.4.yaml; done
...
gyliu-cary@Mac multikueue-ocm-demo % for ctx in kind-hub kind-managed; do kubectl --context $ctx -n kueue-system rollout status deploy/kueue-controller-manager --timeout=180s; done
deployment "kueue-controller-manager" successfully rolled out
deployment "kueue-controller-manager" successfully rolled out
```

> MultiKueue 自 Kueue 0.9 起就是**默认开启的 Beta 门控**，且 `jobset.x-k8s.io/jobset`
> 已在默认集成列表里——所以这里无需改任何 feature gate。

---

## 第 8 步 — 裁剪 Kueue 集成框架（⚠️ 坑 #2）

**问题：** MultiKueue 管理端会为**每一个启用的集成框架**在 worker 上建立 informer。默认
列表包含 kubeflow/ray/appwrapper 等，而 worker 上没装这些 CRD，于是 MultiKueueCluster
一直处于 `ClientConnectionFailed: no matches for kind "XGBoostJob"`。

**解决：** 把**两个集群**的 `integrations.frameworks` 都裁剪为只保留已安装的框架
（`batch/job`、`jobset.x-k8s.io/jobset`），然后重启控制器。裁剪后的配置见
[`manifests/kueue-config.yaml`](./manifests/kueue-config.yaml)。

```console
gyliu-cary@Mac multikueue-ocm-demo % for ctx in kind-hub kind-managed; do
    kubectl --context $ctx -n kueue-system create configmap kueue-manager-config \
      --from-file=controller_manager_config.yaml=manifests/kueue-config.yaml \
      --dry-run=client -o yaml | kubectl --context $ctx apply -f -
    kubectl --context $ctx -n kueue-system rollout restart deploy/kueue-controller-manager
  done
configmap/kueue-manager-config configured
deployment.apps/kueue-controller-manager restarted
configmap/kueue-manager-config configured
deployment.apps/kueue-controller-manager restarted
```

两个集群上控制器最终状态：

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get pods -n kueue-system
NAME                                        READY   STATUS    RESTARTS   AGE
kueue-controller-manager-5c5c86454d-z8nn4   1/1     Running   0          8m53s
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get pods -n kueue-system
NAME                                        READY   STATUS    RESTARTS   AGE
kueue-controller-manager-5c5c86454d-4wtk6   1/1     Running   0          8m53s
```

---

## 第 9 步 — 在 hub 上安装 OCM managed-serviceaccount addon

该 addon 会在 **managed** 集群上创建一个 ServiceAccount，并把它的 token 同步回 **hub** 上
的一个 Secret——这就是 MultiKueue 要用的凭据。

```console
gyliu-cary@Mac multikueue-ocm-demo % helm repo add ocm https://open-cluster-management.io/helm-charts && helm repo update ocm
gyliu-cary@Mac multikueue-ocm-demo % helm install managed-serviceaccount ocm/managed-serviceaccount \
    --version 0.10.0 -n open-cluster-management-addon --create-namespace --kube-context kind-hub
NAME: managed-serviceaccount
STATUS: deployed
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get managedclusteraddon -n cluster1
NAME                     AVAILABLE   DEGRADED   PROGRESSING
managed-serviceaccount   True                   False
```

---

## 第 10 步 — 通过 `ManagedServiceAccount` 生成 worker 凭据

在 hub 的 `cluster1` namespace 创建 [`manifests/msa.yaml`](./manifests/msa.yaml)。OCM 会在
worker 上创建 SA，并把它的 token + CA 投递到同名的 hub Secret 里。

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub apply -f manifests/msa.yaml
managedserviceaccount.authentication.open-cluster-management.io/kueue-multikueue created
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get managedserviceaccount -n cluster1
NAME               AGE
kueue-multikueue   13m
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get secret -n cluster1 kueue-multikueue
NAME               TYPE     DATA   AGE
kueue-multikueue   Opaque   2      13m
```

---

## 第 11 步 — 给 worker SA 授予 MultiKueue RBAC

OCM 创建的 SA（worker 上的 `open-cluster-management-agent-addon/kueue-multikueue`）此时还
没有任何权限。分别应用 **ClusterRole** 与 **ClusterRoleBinding** 两个 manifest：
[`manifests/managed-rbac.yaml`](./manifests/managed-rbac.yaml) 和
[`manifests/crb.yaml`](./manifests/crb.yaml)。

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed apply -f manifests/managed-rbac.yaml
clusterrole.rbac.authorization.k8s.io/kueue-multikueue-role created
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed apply -f manifests/crb.yaml
clusterrolebinding.rbac.authorization.k8s.io/kueue-multikueue-crb created
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed auth can-i create jobsets.jobset.x-k8s.io --as=system:serviceaccount:open-cluster-management-agent-addon:kueue-multikueue
yes
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed auth can-i create workloads.kueue.x-k8s.io --as=system:serviceaccount:open-cluster-management-agent-addon:kueue-multikueue
yes
```

---

## 第 12 步 — 构建 MultiKueue kubeconfig 并存为 hub 上的 Secret

kubeconfig 的 `server` 必须**从 hub 的 Kueue pod 可达**——用 docker DNS 名
`https://managed-control-plane:6443`（在 managed 证书 SAN 中）。token 和 CA 取自 OCM 同步
过来的 Secret。

```console
gyliu-cary@Mac multikueue-ocm-demo % TOKEN=$(kubectl --context kind-hub get secret -n cluster1 kueue-multikueue -o jsonpath='{.data.token}' | base64 -d)
gyliu-cary@Mac multikueue-ocm-demo % CA=$(kubectl --context kind-hub get secret -n cluster1 kueue-multikueue -o jsonpath='{.data.ca\.crt}')
gyliu-cary@Mac multikueue-ocm-demo % cat > worker1.kubeconfig <<EOF
apiVersion: v1
kind: Config
clusters:
- name: cluster1
  cluster:
    server: https://managed-control-plane:6443
    certificate-authority-data: ${CA}
contexts:
- name: cluster1
  context: {cluster: cluster1, user: kueue-multikueue}
current-context: cluster1
users:
- name: kueue-multikueue
  user:
    token: ${TOKEN}
EOF
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub create secret generic multikueue1 -n kueue-system \
    --from-file=kubeconfig=worker1.kubeconfig --dry-run=client -o yaml | kubectl --context kind-hub apply -f -
secret/multikueue1 created
```

---

## 第 13 步 — 在 hub 上创建 MultiKueue 资源

见 [`manifests/hub-multikueue.yaml`](./manifests/hub-multikueue.yaml)：一个
`MultiKueueCluster`（指向 `multikueue1` Secret）、一个 `MultiKueueConfig`，以及一个挂在
控制器 `kueue.x-k8s.io/multikueue` 上的 `AdmissionCheck`。

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub apply -f manifests/hub-multikueue.yaml
multikueuecluster.kueue.x-k8s.io/cluster1 created
multikueueconfig.kueue.x-k8s.io/multikueue-config created
admissioncheck.kueue.x-k8s.io/sample-multikueue created
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get multikueuecluster
NAME       CONNECTED   AGE
cluster1   True        9m16s
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get admissioncheck
NAME                AGE
sample-multikueue   9m16s
```

`CONNECTED=True` 表示 hub 已用 OCM 凭据成功连上 worker。🎉

---

## 第 14 步 — 两个集群上创建队列

hub 的 ClusterQueue 通过 v1beta2 的 `spec.admissionChecksStrategy` 引用 MultiKueue 准入
检查；worker 的 ClusterQueue 是普通队列。见
[`manifests/hub-queues.yaml`](./manifests/hub-queues.yaml) 和
[`manifests/worker-queues.yaml`](./manifests/worker-queues.yaml)。

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed apply -f manifests/worker-queues.yaml
resourceflavor.kueue.x-k8s.io/default-flavor created
clusterqueue.kueue.x-k8s.io/cluster-queue created
localqueue.kueue.x-k8s.io/user-queue created
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub apply -f manifests/hub-queues.yaml
resourceflavor.kueue.x-k8s.io/default-flavor created
clusterqueue.kueue.x-k8s.io/cluster-queue created
localqueue.kueue.x-k8s.io/user-queue created
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get clusterqueue cluster-queue -o jsonpath='{.status.conditions[?(@.type=="Active")].message}'
Can admit new workloads
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get clusterqueue cluster-queue -o jsonpath='{.status.conditions[?(@.type=="Active")].message}'
Can admit new workloads
```

---

## 第 15 步 — 跑 demo：向 hub 提交 JobSet

把 [`manifests/jobset-demo.yaml`](./manifests/jobset-demo.yaml)（带标签
`kueue.x-k8s.io/queue-name: user-queue`）提交到 **hub**。

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub apply -f manifests/jobset-demo.yaml
jobset.jobset.x-k8s.io/multikueue-demo created
```

**在 hub 上：** Workload 被接纳，但**这里没有 Pod**——执行被下放。

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get workloads
NAME                           QUEUE        RESERVED IN     ADMITTED   FINISHED   AGE
jobset-multikueue-demo-6a2e2   user-queue   cluster-queue   True                  6s
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get pods
No resources found in default namespace.
```

**在 managed 上：** MultiKueue 复制出 JobSet，Pod 真正在这里运行。

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get jobset
NAME              TERMINALSTATE   RESTARTS   COMPLETED   SUSPENDED   AGE
multikueue-demo                                          false       5s
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get pods -o wide
NAME                                READY   STATUS    RESTARTS   AGE   IP            NODE                    NOMINATED NODE   READINESS GATES
multikueue-demo-workers-0-0-6h7ml   1/1     Running   0          5s    10.244.0.15   managed-control-plane   <none>           <none>
multikueue-demo-workers-0-1-76jj2   1/1     Running   0          5s    10.244.0.16   managed-control-plane   <none>           <none>
```

**等待完成**，再观察状态回传到 hub：

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed wait --for=condition=Completed jobset/multikueue-demo --timeout=120s
jobset.jobset.x-k8s.io/multikueue-demo condition met
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get jobset multikueue-demo -o jsonpath='{.status.terminalState}'
Completed
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get workloads
NAME                           QUEUE        RESERVED IN     ADMITTED   FINISHED   AGE
jobset-multikueue-demo-6a2e2   user-queue   cluster-queue   True       True       52s
```

worker Pod 的示例日志（运行期间抓取）：

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed logs multikueue-demo-workers-0-0-6h7ml
[multikueue-demo-workers-0-0] running on MultiKueue worker
done
```

> 完成后，Kueue 会回收 worker 侧的 JobSet/Workload——所以 `managed` 集群上 `workloads`
> 列表会重新变空。这是 MultiKueue 的预期行为；权威记录保留在 hub 上。

---

## 辅助脚本

| 脚本 | 用途 |
|---|---|
| [`setup-and-run.sh`](./setup-and-run.sh) | **一键跑通**：从空 kind 集群到 demo JobSet 完成（含 OCM accept / 状态同步重试） |
| [`status.sh`](./status.sh) | 打印两个集群的 OCM + MultiKueue 健康状态及队列 |
| [`run-demo.sh`](./run-demo.sh) | （重新）提交示例 JobSet 并观察在 worker 上的执行 |

从零干净重跑：

```console
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name hub 2>/dev/null || true
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name managed 2>/dev/null || true
gyliu-cary@Mac multikueue-ocm-demo % rm -f hub-ca.crt worker1.kubeconfig
gyliu-cary@Mac multikueue-ocm-demo % ./setup-and-run.sh
```

`status.sh` 示例输出：

```console
gyliu-cary@Mac multikueue-ocm-demo % ./status.sh
================ OCM ================
NAME       HUB ACCEPTED   MANAGED CLUSTER URLS                 JOINED   AVAILABLE   AGE
cluster1   true           https://managed-control-plane:6443   True     True        20m
================ MultiKueue (hub) ================
MultiKueueCluster cluster1 : Active / Connected
AdmissionCheck sample      : The admission check is active
...
```

---

## 清理

```console
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name hub
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name managed
```

---

## 踩坑小结

1. **macOS 上 OCM join** —— 宿主机路由不到 docker IP；预检用宿主机 `127.0.0.1:<端口>`
   **加 `--force-internal-endpoint-lookup`**，让 klusterlet 用 `hub-control-plane:6443`。
2. **`clusteradm accept` 时机** —— join 完成后在 hub 上执行；若 CSR 尚未就绪，等几秒重试。
3. **MultiKueue 连接失败** —— 把两个集群的 `integrations.frameworks` 裁剪为只含已安装的
   框架，否则会因缺少 CRD（如 `XGBoostJob`）而失败。
4. **kubeconfig 的 server 地址** —— 必须 hub-pod 可达：用 `https://managed-control-plane:6443`。
5. **v1beta2 API 变化** —— `MultiKueueCluster.spec.clusterSource.kubeConfig`（嵌套），以及
   `ClusterQueue.spec.admissionChecksStrategy.admissionChecks[].name`（旧的扁平
   `spec.admissionChecks` 已移除）。

## Tips

```console
cd kueue/multikueue-ocm-demo
kind delete cluster --name hub 2>/dev/null || true
kind delete cluster --name managed 2>/dev/null || true
rm -f hub-ca.crt worker1.kubeconfig
./setup-and-run.sh
```
