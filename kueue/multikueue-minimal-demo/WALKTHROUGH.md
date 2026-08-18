# MultiKueue Demo — Step-by-Step Walkthrough

> 中文版：[WALKTHROUGH.zh-CN.md](WALKTHROUGH.zh-CN.md) · Architecture: [README.md](README.md)

Every command below, and its **real output**, captured from an actual run on
macOS / Apple Silicon / Docker Desktop. This walkthrough uses `kubectl` / `kind` /
`helm` step by step — not the wrapper scripts.

The `scripts/` directory is still there as an optional one-shot shortcut; it is not
what this document teaches.

**Contents**

- [Step 0: install the prerequisites](#step-0-install-the-prerequisites)
- [Step 1: create the three kind clusters](#step-1-create-the-three-kind-clusters)
- [Context switching](#context-switching)
- [Step 2: install JobSet and KubeRay](#step-2-install-jobset-and-kuberay)
- [Step 3: install Kueue and enable MultiKueue](#step-3-install-kueue-and-enable-multikueue)
- [Step 4: configure the worker queues](#step-4-configure-the-worker-queues)
- [Step 5: connect the manager to the workers](#step-5-connect-the-manager-to-the-workers)
- [Step 6: wire up MultiKueue on the manager](#step-6-wire-up-multikueue-on-the-manager)
- [Test 1: batch/v1 Job](#test-1-batchv1-job)
- [Test 2: JobSet](#test-2-jobset)
- [Test 3: RayJob](#test-3-rayjob)
- [Troubleshooting](#troubleshooting)
- [Cleanup](#cleanup)

---

## Step 0: install the prerequisites

### 0.1 Docker

Three kind clusters run side by side, so give Docker at least **8GB of memory**
(12GB+ if you want the RayJob example). On macOS: Docker Desktop → Settings → Resources.

```console
gyliu-cary@Mac multikueue-minimal-demo % docker info --format '{{.MemTotal}} {{.NCPU}}'
24898469888 14
```

### 0.2 kind

Must be **≥ v0.31.0** (its default node image is k8s v1.35.0).

```console
gyliu-cary@Mac multikueue-minimal-demo % brew install kind
```

Other platforms:

```console
# Linux amd64
gyliu-cary@Mac ~ % curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-linux-amd64
gyliu-cary@Mac ~ % chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind

# macOS Apple Silicon (without brew)
gyliu-cary@Mac ~ % curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-darwin-arm64
gyliu-cary@Mac ~ % chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
```

Verify:

```console
gyliu-cary@Mac multikueue-minimal-demo % kind version
kind v0.31.0 go1.25.5 darwin/arm64
```

### 0.3 kubectl and helm

```console
gyliu-cary@Mac multikueue-minimal-demo % brew install kubectl helm
```

Verify:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl version --client
Client Version: v1.32.2
Kustomize Version: v5.5.0
```

`helm` is used only for the KubeRay operator. Kueue and JobSet are installed by applying
their official released `manifests.yaml` — no helm needed.

---

## Step 1: create the three kind clusters

One manager, two workers, each a single-node cluster.

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

### Verify

```console
gyliu-cary@Mac multikueue-minimal-demo % kind get clusters
mk-manager
mk-worker1
mk-worker2
```

kind writes three contexts into your kubeconfig automatically:

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

### Key point: all three clusters share one docker network

kind puts every cluster on a bridge network called `kind`. **This is what makes the
manager able to reach the worker API servers:**

```console
gyliu-cary@Mac multikueue-minimal-demo % docker network inspect kind -f '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}' | grep control-plane
mk-manager-control-plane 172.19.0.2/16
mk-worker1-control-plane 172.19.0.3/16
mk-worker2-control-plane 172.19.0.4/16
```

Step 5 uses these IPs.

---

## Context switching

This demo spans 3 clusters, and verifying it means constantly hopping between the manager
and the workers to inspect pods. This section collects every way to do that.

### The three context names

kind writes contexts into `~/.kube/config` automatically, named `kind-<cluster>`:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl config get-contexts | grep mk-
*         kind-mk-manager   kind-mk-manager   kind-mk-manager
          kind-mk-worker1   kind-mk-worker1   kind-mk-worker1
          kind-mk-worker2   kind-mk-worker2   kind-mk-worker2
```

| Cluster | Context name | Role |
|---|---|---|
| mk-manager | `kind-mk-manager` | submit jobs, inspect dispatch results |
| mk-worker1 | `kind-mk-worker1` | see the pods that actually run |
| mk-worker2 | `kind-mk-worker2` | see the pods that actually run |

### Option 1: `--context` per command (recommended)

**Leaves your default context untouched** — the safest form, and what every command in this
walkthrough uses:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get workloads
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get pods
```

The upside is that you can **compare clusters in a single command line**, with no risk of
forgetting to switch back:

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

That one command shows MultiKueue working at a glance: no pods on the manager, one on each
worker.

### Option 2: switch the default context

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl config use-context kind-mk-worker1
Switched to context "kind-mk-worker1".
```

Check where you currently point:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl config current-context
kind-mk-worker1
```

Commands without `--context` now act on that cluster:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl get nodes
NAME                       STATUS   ROLES           AGE   VERSION
mk-worker1-control-plane   Ready    control-plane   38m   v1.35.0
```

Switch back to the manager:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl config use-context kind-mk-manager
Switched to context "kind-mk-manager".
```

### Option 3: shell aliases (easiest while experimenting)

Paste these into your shell (or into `~/.zshrc`):

```console
gyliu-cary@Mac multikueue-minimal-demo % alias kmgr='kubectl --context kind-mk-manager'
gyliu-cary@Mac multikueue-minimal-demo % alias kw1='kubectl --context kind-mk-worker1'
gyliu-cary@Mac multikueue-minimal-demo % alias kw2='kubectl --context kind-mk-worker2'
```

Then:

```console
gyliu-cary@Mac multikueue-minimal-demo % kmgr -n default get workloads
gyliu-cary@Mac multikueue-minimal-demo % kw1 -n default get pods
gyliu-cary@Mac multikueue-minimal-demo % kw2 -n default get pods
```

### Option 4: kubectx (third-party)

```console
gyliu-cary@Mac multikueue-minimal-demo % brew install kubectx
gyliu-cary@Mac multikueue-minimal-demo % kubectx kind-mk-worker1
gyliu-cary@Mac multikueue-minimal-demo % kubectx -          # back to the previous context
```

### Quick reference

| What you want to see | Which cluster | Command |
|---|---|---|
| Submitted Job/JobSet/RayJob | manager | `kubectl --context kind-mk-manager -n default get jobs,jobsets,rayjobs` |
| Where a Workload was dispatched | manager | `kubectl --context kind-mk-manager -n default get workloads -o custom-columns='WL:.metadata.name,RAN-ON:.status.clusterName'` |
| MultiKueue connection health | manager | `kubectl --context kind-mk-manager get multikueuecluster` |
| **The pods that actually run** | worker | `kubectl --context kind-mk-worker1 -n default get pods` |
| Worker quota usage | worker | `kubectl --context kind-mk-worker1 get clusterqueue cluster-queue` |
| Kueue controller logs | manager | `kubectl --context kind-mk-manager -n kueue-system logs deployment/kueue-controller-manager` |

To compare "submitted where vs running where" in one pass:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get jobs,jobsets,rayjobs,workloads,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get jobs,jobsets,rayjobs,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get clusterqueue cluster-queue
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get jobs,jobsets,rayjobs,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 get clusterqueue cluster-queue
```

---

## Step 2: install JobSet and KubeRay

**This must happen before installing Kueue.** Kueue decides which integrations to enable
at startup based on which CRDs exist; CRDs installed afterwards are not picked up.

All three clusters get them, **including the manager**. Reason: MultiKueue keeps a "shadow"
copy of the JobSet/RayJob on the manager. Both operators honour
`spec.managedBy=kueue.x-k8s.io/multikueue` and deliberately do nothing when they see it, so
no pods are created on the manager. (Requires JobSet ≥ v0.6.0 and KubeRay ≥ v1.3.1.)

Install on all three clusters. Repeat the block below for each context
(`kind-mk-manager`, `kind-mk-worker1`, `kind-mk-worker2`). Add the helm repo once:

```console
gyliu-cary@Mac multikueue-minimal-demo % helm repo add kuberay https://ray-project.github.io/kuberay-helm/
gyliu-cary@Mac multikueue-minimal-demo % helm repo update kuberay
```

Manager example (swap the context name for each worker):

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply --server-side \
  -f https://github.com/kubernetes-sigs/jobset/releases/download/v0.12.0/manifests.yaml

gyliu-cary@Mac multikueue-minimal-demo % helm --kube-context kind-mk-manager upgrade --install kuberay-operator \
  kuberay/kuberay-operator --version 1.6.2 -n kuberay-system --create-namespace --wait

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n jobset-system \
  rollout status deployment/jobset-controller-manager --timeout=300s
deployment "jobset-controller-manager" successfully rolled out
```

Sample helm output:

```
NAME: kuberay-operator
LAST DEPLOYED: Fri Aug 14 10:44:19 2026
NAMESPACE: kuberay-system
STATUS: deployed
REVISION: 1
```

### Verify

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get pods -A | grep -E "jobset|kuberay"
jobset-system        jobset-controller-manager-5585d4c665-c9qf4         1/1     Running   0          14m
kuberay-system       kuberay-operator-5dff8cd9d5-wz9nm                  1/1     Running   0          14m
```

Confirm the CRDs exist on every cluster:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get crd \
  jobsets.jobset.x-k8s.io rayjobs.ray.io rayclusters.ray.io rayservices.ray.io \
  -o custom-columns='CRD:.metadata.name' --no-headers
jobsets.jobset.x-k8s.io
rayjobs.ray.io
rayclusters.ray.io
rayservices.ray.io
```

---

## Step 3: install Kueue and enable MultiKueue

### 3.1 Does MultiKueue need to be turned on?

**No.** The `MultiKueue` feature gate has been **Beta and enabled by default since Kueue
v0.9**:

```go
// pkg/features/kube_features.go
MultiKueue: {
    {Version: version.MustParse("0.6"), Default: false, PreRelease: featuregate.Alpha},
    {Version: version.MustParse("0.9"), Default: true,  PreRelease: featuregate.Beta},
},
```

So installing Kueue is enough — no `--feature-gates` flag required. What actually *activates*
MultiKueue is creating the CRs in step 6 (AdmissionCheck / MultiKueueConfig / MultiKueueCluster).

### 3.2 Install

Repeat this on all three contexts:

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

Repeat with `kind-mk-worker1` and `kind-mk-worker2`.

The `rollout restart` after applying `kueue-config.yaml` is required: Kueue reads that
ConfigMap at startup only.

Do not apply Kueue CRs until the webhook has endpoints, or you will get `connection
refused`:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system get endpointslice \
  -l kubernetes.io/service-name=kueue-webhook-service
```

Confirm the integrations list is now narrow:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system get cm kueue-manager-config \
  -o jsonpath='{.data.controller_manager_config\.yaml}'
```

You should see:

```
integrations:
  frameworks:
  - "batch/job"
  - "jobset.x-k8s.io/jobset"
  - "ray.io/rayjob"
  - "ray.io/raycluster"
  - "ray.io/rayservice"
```

### 3.3 Why the ConfigMap must be edited

This is the most important gotcha in the whole demo. Kueue enables a long list of
integrations out of the box:

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

MultiKueue opens a watch **per enabled framework** on every worker. The workers have no
AppWrapper / Kubeflow Trainer / LeaderWorkerSet CRDs, so those watches fail and the entire
cluster connection is marked failed. `manifests/kueue-config.yaml` narrows the list to what
this demo actually installs.

**Rule: `integrations.frameworks` must correspond exactly to the operators installed on the
workers.**

### 3.4 The dispatch strategy lives in the same ConfigMap

```yaml
multiKueue:
  dispatcherName: kueue.x-k8s.io/multikueue-dispatcher-all-at-once
  workerLostTimeout: 15m
  gcInterval: 1m
```

Full explanation in [README section 5](README.md#5-dispatch-strategy).

### Verify

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

## Step 4: configure the worker queues

A worker cluster is just an ordinary standalone Kueue cluster. The key constraint:
**the namespace and LocalQueue names must match the manager exactly** (here `default` /
`user-queue`), because MultiKueue copies the Workload verbatim.

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

If the webhook returns `connection refused`, wait a few seconds and `kubectl apply` again.

Confirm both queues exist:

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

The worker quota is deliberately small (2 CPU / 4Gi) so the demo can show quota pressure
landing on the worker side:

```yaml
# manifests/worker-queues.yaml
resources:
  - name: cpu
    nominalQuota: 2
  - name: memory
    nominalQuota: 4Gi
```

---

## Step 5: connect the manager to the workers

This is the **only** cross-cluster mechanism: the manager holds a kubeconfig whose **token**
authenticates it to the worker API server, so it can `watch Workload` / `create Job`.

The steps below are for `mk-worker1`. Repeat them for `mk-worker2`, changing the context
and Secret name.

### 5.1 Create a restricted ServiceAccount on the worker

Permissions cover Kueue Workloads plus the three frameworks this demo installs. This
ClusterRole must cover **every** framework listed in `integrations.frameworks` from step 3,
or the manager's watch gets a 403.

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 apply -f manifests/worker-multikueue-rbac.yaml
serviceaccount/multikueue-sa created
clusterrole.rbac.authorization.k8s.io/multikueue-sa-role created
clusterrolebinding.rbac.authorization.k8s.io/multikueue-sa-crb created
secret/multikueue-sa created
```

The YAML requests a long-lived token Secret (k8s 1.24 no longer creates these automatically):

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

Wait a few seconds for kube-controller-manager to populate the token, then check it is
non-empty:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n kueue-system get secret multikueue-sa \
  -o jsonpath='{.data.token}' | wc -c
```

### 5.2 Extract the token and CA, assemble a kubeconfig

**The biggest kind gotcha:** `kind get kubeconfig` gives `https://127.0.0.1:<random-port>`,
which only works from the host. The Kueue pod on the manager lives on the docker network
and must use the worker control-plane container's IP on the `kind` bridge:

```console
gyliu-cary@Mac multikueue-minimal-demo % docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' mk-worker1-control-plane
172.19.0.3
```

kubeadm puts that IP in the API server certificate SANs, so TLS still verifies — no
`insecure-skip-tls-verify`.

Pull token, CA, and that IP into a kubeconfig (do not copy the token by hand):

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

The result looks like this (token truncated):

```yaml
apiVersion: v1
kind: Config
clusters:
  - name: mk-worker1
    cluster:
      certificate-authority-data: LS0tLS1CRUdJTiBDRVJU...
      server: https://172.19.0.3:6443     # ← in-network address, NOT 127.0.0.1
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

`certificate-authority-data` proves the peer is w1's API server; `token` proves the caller
is `multikueue-sa`. Without the token the worker returns `401` and no create/watch happens.

### 5.3 Store the kubeconfig as a Secret on the manager

Kueue reads the remote client from the Secret key `kubeconfig`:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system create secret generic \
  mk-worker1-secret --from-file=kubeconfig=/tmp/mk-worker1.kubeconfig
secret/mk-worker1-secret created
```

Repeat 5.1–5.3 for `mk-worker2`: apply RBAC, write `/tmp/mk-worker2.kubeconfig`, create
`mk-worker2-secret`. Get the IP with:

```console
gyliu-cary@Mac multikueue-minimal-demo % docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' mk-worker2-control-plane
172.19.0.4
```

### Verify

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system get secret | grep -- -secret
mk-worker1-secret           Opaque   1      12m
mk-worker2-secret           Opaque   1      12m
```

---

## Step 6: wire up MultiKueue on the manager

Create the object chain:
`ClusterQueue → AdmissionCheck → MultiKueueConfig → MultiKueueCluster → Secret`.

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

Kueue uses the Secrets from step 5 to reach the workers. Wait until both are `Active`:

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

**`Active=True / Connected` means the environment is ready.**

The critical piece is attaching the AdmissionCheck to the ClusterQueue — the only difference
between an ordinary queue and a cross-cluster dispatching queue:

```yaml
apiVersion: kueue.x-k8s.io/v1beta2
kind: ClusterQueue
metadata:
  name: cluster-queue
spec:
  # ... resourceGroups ...
  admissionChecksStrategy:
    admissionChecks:
      - name: multikueue-check     # ← with this, nothing runs locally any more
```

### Verify

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get multikueuecluster
NAME         CONNECTED   AGE
mk-worker1   True        3m
mk-worker2   True        3m
```

If `ACTIVE` is `False`, read the `MESSAGE` field — it explains almost every failure mode.
See [Troubleshooting](#troubleshooting).

---

## Test 1: batch/v1 Job

**Goal:** verify basic cross-cluster dispatch and observe quota taking effect on the worker side.

### Scenario

- Submit **3 Jobs**, each requesting **2 CPU**
- Manager quota **10 CPU** (not a bottleneck)
- Each worker quota **2 CPU** (the real gate)

Expected: 2 Jobs run, one per worker; the 3rd queues because both workers are full.

### Dispatch strategy

This test uses **AllAtOnce** (`kueue.x-k8s.io/multikueue-dispatcher-all-at-once`), configured
via `multiKueue.dispatcherName` in `manifests/kueue-config.yaml`. Behaviour: once a Workload
reaches `QuotaReserved` on the manager, a copy is created on mk-worker1 **and** mk-worker2
simultaneously; the first to admit wins and the loser copy is deleted.

### Run

Clear leftover workloads first (all three clusters, so leftover quota does not leak):

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
```

Submit the three Jobs **to the manager only**:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f examples/jobs.yaml
job.batch/demo-job-1 created
job.batch/demo-job-2 created
job.batch/demo-job-3 created
```

Wait ~15s for MultiKueue to dispatch, then compare the three clusters:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get jobs,pods
NAME                   STATUS    COMPLETIONS   DURATION   AGE
job.batch/demo-job-1   Running   0/1                      6s
job.batch/demo-job-2   Running   0/1           5s         6s
job.batch/demo-job-3   Running   0/1           4s         6s
No resources found in default namespace.    # ← no pods on the manager

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

### Reading the result

| Observation | Output | Meaning |
|---|---|---|
| Pods on the manager | `<none>` | **the core proof MultiKueue works** |
| demo-job-2 | `mk-worker2` | dispatched to worker2 |
| demo-job-3 | `mk-worker1` | dispatched to worker1 |
| demo-job-1 | `ADMITTED <none>` | manager quota was fine, both workers full |
| worker `PENDING 1` | on both workers | AllAtOnce created demo-job-1's copy on **both**, both queued |

That `PENDING 1` column is the key to understanding AllAtOnce: the same Workload queues on
two clusters at once; whichever frees capacity first runs it, and the other copy is deleted.

### Verify managedBy by hand

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get job demo-job-1 \
  -o custom-columns='JOB:.metadata.name,SUSPEND:.spec.suspend,MANAGED-BY:.spec.managedBy'
JOB          SUSPEND   MANAGED-BY
demo-job-1   true      kueue.x-k8s.io/multikueue
```

We never wrote `managedBy` in the YAML — the Kueue webhook stamped it, because `user-queue`
points at a ClusterQueue carrying a MultiKueue AdmissionCheck. The manager's native Job
controller sees a value that is not its own and leaves the object entirely alone.

### Inspect the full Workload status

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

The two gates are clearest here: `QuotaReserved` (manager let it through) → `Admitted`
(a worker took it).

---

## Test 2: JobSet

**Goal:** verify a multi-pod gang workload is dispatched to a single cluster **as a unit**,
never split across clusters.

### Scenario

One JobSet with 2 replicated Jobs, 500m CPU each (1 CPU total).

### Dispatch strategy

**AllAtOnce** again — the dispatcher is a Kueue-level setting and applies to every workload
type, not per framework.

### Run

Clear leftovers, then submit the JobSet to the manager only:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found

gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f examples/jobset.yaml
jobset.jobset.x-k8s.io/demo-jobset created
```

Check that the webhook stamped `managedBy` (it is not in the YAML):

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get jobset demo-jobset \
  -o jsonpath='{.metadata.name}{"  managedBy="}{.spec.managedBy}{"  suspend="}{.spec.suspend}{"\n"}'
demo-jobset  managedBy=kueue.x-k8s.io/multikueue  suspend=false
```

See which worker won:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get workloads \
  -o custom-columns='WORKLOAD:.metadata.name,ADMITTED:.status.conditions[?(@.type=="Admitted")].status,DISPATCHED-TO:.status.clusterName,MESSAGE:.status.admissionChecks[0].message'
WORKLOAD                   ADMITTED   DISPATCHED-TO   MESSAGE
jobset-demo-jobset-0e211   True       mk-worker2      The workload was admitted on "mk-worker2"
```

No pods or child Jobs on the manager; they exist only on the winner:

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

### Reading the result

| Observation | Output | Meaning |
|---|---|---|
| JobSet on the manager | exists, `SUSPENDED false` | a shadow object only |
| **Child Jobs** on the manager | none | the JobSet controller stood down because of `managedBy` |
| Pods on the manager | `<none>` | ✓ |
| mk-worker2 | 2 child Jobs + 2 Pods | the whole JobSet landed on **one** cluster |
| mk-worker1 | empty | ✓ **the gang was not split across clusters** |

This is the key difference from "spray pods across clusters": **the unit of dispatch is the
entire Workload**, which is what makes pod-to-pod communication in distributed training work.

`managedBy=kueue.x-k8s.io/multikueue` appeared 2 seconds after submission, stamped by the
webhook — our YAML does not contain it:

```console
gyliu-cary@Mac multikueue-minimal-demo % grep -c managedBy examples/jobset.yaml
0
```

---

## Test 3: RayJob

**Goal:** verify a workload that **dynamically creates child resources** (a RayCluster) has
those children created only on the target worker.

### Scenario

One RayJob: head 500m/2Gi + 1 worker 500m/1Gi (1 CPU / 3Gi total, fits the worker's
2 CPU / 4Gi quota). `shutdownAfterJobFinishes: true` tears the RayCluster down when the job
completes, releasing quota.

### Dispatch strategy

**AllAtOnce** again.

### Run

Clear leftovers first. The Ray image is ~177MB (Kueue's slim test image). Without pre-loading,
pods sit in `ContainerCreating` for a long time. **Do not use `kind load docker-image`**
(multi-arch attestation fails with `content digest ... not found`); use a single-platform
archive:

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

On Intel Macs, use `--platform linux/amd64`.

Submit the RayJob:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f examples/rayjob.yaml
rayjob.ray.io/demo-rayjob created
```

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get rayjob demo-rayjob \
  -o jsonpath='{.metadata.name}{"  managedBy="}{.spec.managedBy}{"  suspend="}{.spec.suspend}{"\n"}'
demo-rayjob  managedBy=kueue.x-k8s.io/multikueue  suspend=
```

See where it went:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get workloads \
  -o custom-columns='WORKLOAD:.metadata.name,ADMITTED:.status.conditions[?(@.type=="Admitted")].status,DISPATCHED-TO:.status.clusterName,MESSAGE:.status.admissionChecks[0].message'
WORKLOAD                   ADMITTED   DISPATCHED-TO   MESSAGE
rayjob-demo-rayjob-a5a54   True       mk-worker2      The workload was admitted on "mk-worker2"
```

No pods on the manager; the RayCluster appears only on the winner:

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

Wait for the job to finish (a minute or two). Status on the manager is **synced back** from
the worker:

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

### Reading the result

| Observation | Output | Meaning |
|---|---|---|
| RayJob on the manager | exists, `RAY CLUSTER NAME` populated | status synced back from the worker |
| **RayCluster pods** on the manager | `<none>` | KubeRay operator created none, because of `managedBy` |
| mk-worker2 | head + worker pods | the RayCluster was only materialised here |
| Manager's final `JOB-STATUS` | `SUCCEEDED` | **the worker's execution result synced back to the manager** |

That last row is direct proof of MultiKueue's status sync: the user only ever talks to the
manager, yet sees the real result from the worker.

### Watch the RayCluster lifecycle

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get events --sort-by=.lastTimestamp | tail -8
53s   Normal  CreatedService          rayjob/demo-rayjob    Created the service default/demo-rayjob-head-svc
53s   Normal  CreatedRayJobSubmitter  rayjob/demo-rayjob    Created Kubernetes Job default/demo-rayjob
52s   Normal  Started                 pod/demo-rayjob-mlv7m Container started
43s   Normal  DeletedRayCluster       rayjob/demo-rayjob    Deleted cluster default/demo-rayjob-4sp5h
43s   Normal  Killing                 pod/demo-rayjob-4sp5h-head-nmg2m  Stopping container ray-head
43s   Normal  Completed               job/demo-rayjob       Job completed
```

`Job completed` → `DeletedRayCluster` is `shutdownAfterJobFinishes: true` doing its work,
and the worker's quota is released with it.

---

## Troubleshooting

### Pitfall 1: a missing JobSet CRD breaks the connection

**Symptom:**

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get multikueuecluster \
  -o custom-columns='CLUSTER:.metadata.name,ACTIVE:.status.conditions[?(@.type=="Active")].status,REASON:.status.conditions[?(@.type=="Active")].reason,MESSAGE:.status.conditions[?(@.type=="Active")].message'
CLUSTER      ACTIVE   REASON                   MESSAGE
mk-worker1   False    ClientConnectionFailed   no matches for kind "JobSet" in version "jobset.x-k8s.io/v1alpha2"
mk-worker2   False    ClientConnectionFailed   no matches for kind "JobSet" in version "jobset.x-k8s.io/v1alpha2"

CHECK              ACTIVE   MESSAGE
multikueue-check   False    Inactive clusters: [mk-worker1 mk-worker2]
```

**Cause:** Kueue enables jobset / appwrapper / trainer / lws and more by default. MultiKueue
opens a watch per enabled framework on each worker; a missing CRD fails the whole connection.

**Fix:** either

1. install all those operators on **every** worker, or
2. narrow `integrations.frameworks` to what is actually installed (what this demo does — see
   `manifests/kueue-config.yaml`). The controller must be restarted afterwards:

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager apply -f manifests/kueue-config.yaml
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system rollout restart deployment/kueue-controller-manager
```

### Pitfall 2: the manager cannot reach the worker (kind networking)

**Symptom:** `Active=False` with `connection refused` or `i/o timeout` in MESSAGE.

**Cause:** the kubeconfig's server is `https://127.0.0.1:<port>`. Works from the host, not
from the manager's pod.

**Check:**

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system get secret mk-worker1-secret \
  -o jsonpath='{.data.kubeconfig}' | base64 -d | grep server
    server: https://172.19.0.3:6443
```

It must be a `172.x.x.x` in-network address. If it says `127.0.0.1`, delete the Secret and
rebuild the kubeconfig with the control-plane container IP as in step 5, then
`kubectl create secret` again.

### Pitfall 3: the RayJob head container is OOMKilled

**Symptom:** the head pod is in `CrashLoopBackOff` with **no log output at all**.

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get pod <head-pod> \
  -o jsonpath='{.status.containerStatuses[0].lastState}'
{"terminated":{"exitCode":137,"reason":"OOMKilled",...}}
```

**Cause:** not enough memory for the Ray head. `exitCode 137` = OOMKilled.

**Fix:** give the head at least 4Gi of `limits.memory` (this demo uses 8Gi). Note that Kueue
counts **requests**, not limits, so you can request 2Gi and limit 8Gi — neither blowing the
quota nor OOMing.

### Pitfall 4: Ray object store sizing error

**Symptom:**

```
ValueError: Attempting to cap object store memory usage at 1146470 bytes,
but the minimum allowed is 78643200 bytes.
```

**Fix:** set it explicitly in `rayStartParams`:

```yaml
rayStartParams:
  object-store-memory: "134217728"
```

### Pitfall 5: `kind load docker-image` fails

**Symptom:**

```
ERROR: failed to load image: ... ctr: content digest sha256:...: not found
```

**Cause:** `kind load docker-image` re-imports with `--all-platforms`; for a multi-arch image
only the local platform's layers exist, so the other platforms' digests are missing.

**Fix:** save a single-platform archive first:

```console
gyliu-cary@Mac multikueue-minimal-demo % docker save --platform linux/arm64 <image> -o image.tar
gyliu-cary@Mac multikueue-minimal-demo % kind load image-archive image.tar --name mk-worker1
```

### Pitfall 6: Workload stuck pending, nothing on any worker

**Check in this order:**

```console
# 1. is the AdmissionCheck Active?
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get admissioncheck multikueue-check -o yaml | grep -A5 conditions

# 2. does the worker have a same-named namespace and LocalQueue? (names must match exactly)
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get localqueue

# 3. do the worker's ResourceFlavor names match the manager's?
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get resourceflavor

# 4. is the worker's quota simply too small for this Workload?
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get clusterqueue cluster-queue -o yaml | grep -A20 "status:"

# 5. read the manager's Kueue logs
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n kueue-system logs deployment/kueue-controller-manager --tail=100 | grep -i multikueue
```

### General status check

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default get jobs,jobsets,rayjobs,workloads,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager get multikueuecluster,admissioncheck
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default get jobs,jobsets,rayjobs,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 get clusterqueue cluster-queue
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default get jobs,jobsets,rayjobs,pods
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 get clusterqueue cluster-queue
```

---

## Cleanup

Wipe the workloads but keep the clusters (handy for repeated experiments):

```console
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-manager -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker1 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
gyliu-cary@Mac multikueue-minimal-demo % kubectl --context kind-mk-worker2 -n default delete jobs,jobsets,rayjobs --all --ignore-not-found
```

Delete the whole environment:

```console
gyliu-cary@Mac multikueue-minimal-demo % kind delete cluster --name mk-manager
Deleting cluster "mk-manager" ...
gyliu-cary@Mac multikueue-minimal-demo % kind delete cluster --name mk-worker1
Deleting cluster "mk-worker1" ...
gyliu-cary@Mac multikueue-minimal-demo % kind delete cluster --name mk-worker2
Deleting cluster "mk-worker2" ...
```

Or in one shot:

```console
gyliu-cary@Mac multikueue-minimal-demo % kind delete clusters mk-manager mk-worker1 mk-worker2
```
