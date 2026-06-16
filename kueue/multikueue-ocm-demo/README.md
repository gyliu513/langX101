# MultiKueue + OCM + JobSet Demo (Kueue v0.16.4)

> 中文版见 [README.zh-CN.md](./README.zh-CN.md)

Two local `kind` clusters wired together with **Open Cluster Management (OCM)** for
cluster registration & credentials, and **Kueue MultiKueue** for cross-cluster job
dispatch. A `JobSet` submitted to the **hub** is admitted by Kueue and actually
**executed on the managed cluster**; its status flows back to the hub.

This README is a **from-scratch, copy-paste runbook**: starting from no clusters, it
walks through every command and shows its real output. By the end you will have
submitted and completed a MultiKueue JobSet.

---

## Architecture

```
┌─────────────────────────────┐   OCM register   ┌─────────────────────────────┐
│  kind: hub  (Manager)       │◀────────────────▶│  kind: managed (Worker)     │
│  172.19.0.2                 │                   │  172.19.0.3                 │
│  - OCM Hub                  │                   │  - OCM Klusterlet (cluster1)│
│  - managed-serviceaccount   │   token synced    │  - SA kueue-multikueue      │
│    addon manager            │◀── back to hub ───│    (+ MultiKueue RBAC)       │
│  - Kueue v0.16.4 (MultiKueue)│                  │  - Kueue v0.16.4            │
│  - JobSet v0.8.1 (CRDs)     │                   │  - JobSet v0.8.1 (runs Pods)│
│  - MultiKueueConfig/Cluster │                   │                             │
│  - AdmissionCheck           │   hub→managed     │                             │
│  - ClusterQueue+admissioncheck  via kubeconfig  │  - ClusterQueue (plain)     │
└─────────────────────────────┘   secret          └─────────────────────────────┘
   submit JobSet → admitted on hub → dispatched & run on managed → status flows back
```

| Component | Version |
|---|---|
| Kueue | **v0.16.4** (MultiKueue Beta gate on by default since 0.9) |
| JobSet | **v0.8.1** (`jobset.x-k8s.io/v1alpha2`) |
| OCM `clusteradm` | v1.3.1 |
| OCM managed-serviceaccount addon (Helm chart) | 0.10.0 |
| Kueue API storage version | `kueue.x-k8s.io/v1beta2` |

---

## Step 0 — Prerequisites

You need `docker`, `kind`, `kubectl`, `helm`, plus the OCM `clusteradm` CLI (installed in
Step 1). This demo was built on an **arm64 macOS + Docker Desktop**.

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

## Step 1 — Install the OCM `clusteradm` CLI

`clusteradm` is **not** in Homebrew; download the darwin/arm64 release binary directly.

```console
gyliu-cary@Mac multikueue-ocm-demo % TAG=$(curl -fsSL https://api.github.com/repos/open-cluster-management-io/clusteradm/releases/latest | grep -m1 '"tag_name"' | cut -d'"' -f4)
gyliu-cary@Mac multikueue-ocm-demo % curl -fsSL "https://github.com/open-cluster-management-io/clusteradm/releases/download/${TAG}/clusteradm_darwin_arm64.tar.gz" -o /tmp/clusteradm.tar.gz
gyliu-cary@Mac multikueue-ocm-demo % tar xzf /tmp/clusteradm.tar.gz -C /tmp && mv /tmp/clusteradm /opt/homebrew/bin/clusteradm
gyliu-cary@Mac multikueue-ocm-demo % clusteradm version | head -1
clusteradm	version	:v1.3.1-0-g90bdc31
```

---

## Step 1.5 — Clean up any previous run (optional)

If you already have `hub` / `managed` kind clusters from an earlier attempt, delete them
first so ports, CSR state, and leftover Secrets do not interfere.

```console
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name hub 2>/dev/null || true
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name managed 2>/dev/null || true
gyliu-cary@Mac multikueue-ocm-demo % kind get clusters
No kind clusters found.
```

Also remove locally generated credentials from a prior run (they are gitignored):

```console
gyliu-cary@Mac multikueue-ocm-demo % rm -f hub-ca.crt worker1.kubeconfig
```

---

## Step 2 — Create the two kind clusters

Wait until both nodes report `Ready` before continuing (kind may show `NotReady` for a few
seconds right after creation).

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

### Network topology (important for the two gotchas below)

Both kind containers share the `kind` docker network and can reach each other by IP
**and by container name** (docker embedded DNS). The macOS host, however, cannot route
to those IPs.

```console
gyliu-cary@Mac multikueue-ocm-demo % docker network inspect kind -f '{{range .Containers}}{{.Name}} => {{.IPv4Address}}{{println}}{{end}}'
hub-control-plane => 172.19.0.2/16
managed-control-plane => 172.19.0.3/16
```

---

## Step 3 — Initialize the OCM hub

```console
gyliu-cary@Mac multikueue-ocm-demo % clusteradm init --context kind-hub --wait
Preflight check: HubApiServer check Passed with 0 warnings and 0 errors
Preflight check: cluster-info check Passed with 0 warnings and 0 errors
The multicluster hub control plane has been initialized successfully!
...
    clusteradm join --hub-token <token> --hub-apiserver https://127.0.0.1:59677 --wait --cluster-name <cluster_name>
```

`clusteradm init` prints a join command pointing at `https://127.0.0.1:<port>` (the
host port). Keep that port — we use it only to pass the host-side preflight.

---

## Step 4 — Join the managed cluster (⚠️ gotcha #1)

**Problem:** on macOS, `clusteradm join`'s preflight dials the hub *from the host*, and
the host cannot route to the kind docker IP `172.19.0.2:6443` → the join times out.

**Fix:** pass the host-reachable `https://127.0.0.1:<port>` (so preflight passes) **plus
`--force-internal-endpoint-lookup`**, which makes the klusterlet actually connect via
`https://hub-control-plane:6443` (docker DNS, and it's in the hub cert SANs).

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

Verify the klusterlet's bootstrap kubeconfig points at the docker DNS name (not 127.0.0.1):

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get secret -n open-cluster-management-agent bootstrap-hub-kubeconfig -o jsonpath='{.data.kubeconfig}' | base64 -d | grep server
    server: https://hub-control-plane:6443
```

---

## Step 5 — Accept the registration on the hub

`clusteradm join` only **requests** registration; the hub must approve the CSR. If you run
`accept` immediately and see `managedcluster cluster1 not found` / `no csr is approved yet`,
wait a few seconds and retry — the klusterlet needs a moment to create the CSR on the hub.

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

> `JOINED=True` appears right after accept. `AVAILABLE=True` can take another minute while
> the work agent starts; later steps do not need to wait for it.

---

## Step 6 — Install JobSet v0.8.1 on both clusters

Kueue v0.16.4 expects the JobSet API (`jobset.x-k8s.io/v1alpha2`). We pin v0.8.1.

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

## Step 7 — Install Kueue v0.16.4 on both clusters

```console
gyliu-cary@Mac multikueue-ocm-demo % curl -fsSL -o manifests/kueue-v0.16.4.yaml https://github.com/kubernetes-sigs/kueue/releases/download/v0.16.4/manifests.yaml
gyliu-cary@Mac multikueue-ocm-demo % for ctx in kind-hub kind-managed; do kubectl --context $ctx apply --server-side -f manifests/kueue-v0.16.4.yaml; done
...
gyliu-cary@Mac multikueue-ocm-demo % for ctx in kind-hub kind-managed; do kubectl --context $ctx -n kueue-system rollout status deploy/kueue-controller-manager --timeout=180s; done
deployment "kueue-controller-manager" successfully rolled out
deployment "kueue-controller-manager" successfully rolled out
```

> MultiKueue is a **Beta feature gate enabled by default** since Kueue 0.9, and
> `jobset.x-k8s.io/jobset` is already in the default integrations list — so no feature
> gate flips are needed here.

---

## Step 8 — Trim Kueue integrations (⚠️ gotcha #2)

**Problem:** the MultiKueue manager builds informers on the worker for **every enabled
integration framework**. The default list includes kubeflow/ray/appwrapper, whose CRDs
are not installed on the worker, so the MultiKueueCluster stays
`ClientConnectionFailed: no matches for kind "XGBoostJob"`.

**Fix:** restrict `integrations.frameworks` on **both** clusters to only what's installed
(`batch/job`, `jobset.x-k8s.io/jobset`), then restart the controllers. The trimmed config
is in [`manifests/kueue-config.yaml`](./manifests/kueue-config.yaml).

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

Final controller state on both clusters:

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get pods -n kueue-system
NAME                                        READY   STATUS    RESTARTS   AGE
kueue-controller-manager-5c5c86454d-z8nn4   1/1     Running   0          8m53s
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get pods -n kueue-system
NAME                                        READY   STATUS    RESTARTS   AGE
kueue-controller-manager-5c5c86454d-4wtk6   1/1     Running   0          8m53s
```

---

## Step 9 — Install the OCM managed-serviceaccount addon on the hub

This addon creates a ServiceAccount on the **managed** cluster and syncs its token back
to a Secret on the **hub** — that's the credential MultiKueue will use.

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

## Step 10 — Mint the worker credential via `ManagedServiceAccount`

Create [`manifests/msa.yaml`](./manifests/msa.yaml) in the `cluster1` namespace on the hub.
OCM creates the SA on the worker and projects its token + CA into a hub Secret of the
same name.

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

## Step 11 — Grant MultiKueue RBAC to the worker SA

The OCM-created SA (`open-cluster-management-agent-addon/kueue-multikueue` on the worker)
has no permissions yet. Bind it to a ClusterRole that can manage Jobs/JobSets/Workloads.
Apply the **ClusterRole** and **ClusterRoleBinding** as two separate manifests:
[`manifests/managed-rbac.yaml`](./manifests/managed-rbac.yaml) and
[`manifests/crb.yaml`](./manifests/crb.yaml).

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

## Step 12 — Build the MultiKueue kubeconfig & store it as a Secret on the hub

The kubeconfig's `server` must be reachable **from the hub's Kueue pod** — use the docker
DNS name `https://managed-control-plane:6443` (it's in the managed cert SANs). Token and
CA come from the OCM-synced Secret.

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

## Step 13 — Create the MultiKueue resources on the hub

See [`manifests/hub-multikueue.yaml`](./manifests/hub-multikueue.yaml): a
`MultiKueueCluster` (points at the `multikueue1` Secret), a `MultiKueueConfig`, and an
`AdmissionCheck` wired to the controller `kueue.x-k8s.io/multikueue`.

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

`CONNECTED=True` means the hub successfully reached the worker with the OCM credential. 🎉

---

## Step 14 — Create the queues on both clusters

The hub's ClusterQueue references the MultiKueue AdmissionCheck (via
`spec.admissionChecksStrategy` in v1beta2); the worker's ClusterQueue is plain. See
[`manifests/hub-queues.yaml`](./manifests/hub-queues.yaml) and
[`manifests/worker-queues.yaml`](./manifests/worker-queues.yaml).

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

## Step 15 — Run the demo: submit a JobSet on the hub

Submit [`manifests/jobset-demo.yaml`](./manifests/jobset-demo.yaml) (labelled
`kueue.x-k8s.io/queue-name: user-queue`) to the **hub**.

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub apply -f manifests/jobset-demo.yaml
jobset.jobset.x-k8s.io/multikueue-demo created
```

**On the hub:** the Workload is admitted, but **no Pods run here** — execution is delegated.

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get workloads
NAME                           QUEUE        RESERVED IN     ADMITTED   FINISHED   AGE
jobset-multikueue-demo-6a2e2   user-queue   cluster-queue   True                  6s
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get pods
No resources found in default namespace.
```

**On the managed cluster:** MultiKueue mirrored the JobSet and the Pods actually run.

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get jobset
NAME              TERMINALSTATE   RESTARTS   COMPLETED   SUSPENDED   AGE
multikueue-demo                                          false       5s
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed get pods -o wide
NAME                                READY   STATUS    RESTARTS   AGE   IP            NODE                    NOMINATED NODE   READINESS GATES
multikueue-demo-workers-0-0-6h7ml   1/1     Running   0          5s    10.244.0.15   managed-control-plane   <none>           <none>
multikueue-demo-workers-0-1-76jj2   1/1     Running   0          5s    10.244.0.16   managed-control-plane   <none>           <none>
```

**Wait for completion**, then watch the status propagate back to the hub:

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed wait --for=condition=Completed jobset/multikueue-demo --timeout=120s
jobset.jobset.x-k8s.io/multikueue-demo condition met
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get jobset multikueue-demo -o jsonpath='{.status.terminalState}'
Completed
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-hub get workloads
NAME                           QUEUE        RESERVED IN     ADMITTED   FINISHED   AGE
jobset-multikueue-demo-6a2e2   user-queue   cluster-queue   True       True       52s
```

A sample worker Pod log (captured while it was running):

```console
gyliu-cary@Mac multikueue-ocm-demo % kubectl --context kind-managed logs multikueue-demo-workers-0-0-6h7ml
[multikueue-demo-workers-0-0] running on MultiKueue worker
done
```

> After completion, Kueue garbage-collects the worker-side JobSet/Workload — so the
> `managed` cluster's `workloads` list will be empty again. That is expected MultiKueue
> behavior; the authoritative record lives on the hub.

---

## Helper scripts

| Script | Purpose |
|---|---|
| [`setup-and-run.sh`](./setup-and-run.sh) | **One-shot**: tear-down not included — from empty kind clusters through a completed demo JobSet (retries flaky OCM accept / status sync) |
| [`status.sh`](./status.sh) | print OCM + MultiKueue health and the queues on both clusters |
| [`run-demo.sh`](./run-demo.sh) | (re)submit the sample JobSet and watch it execute on the worker |

For a clean re-run from scratch:

```console
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name hub 2>/dev/null || true
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name managed 2>/dev/null || true
gyliu-cary@Mac multikueue-ocm-demo % rm -f hub-ca.crt worker1.kubeconfig
gyliu-cary@Mac multikueue-ocm-demo % ./setup-and-run.sh
```

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

## Teardown

```console
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name hub
gyliu-cary@Mac multikueue-ocm-demo % kind delete cluster --name managed
```

---

## Gotchas recap

1. **OCM join on macOS** — host can't route to docker IPs; use host `127.0.0.1:<port>`
   for preflight **+ `--force-internal-endpoint-lookup`** so the klusterlet uses
   `hub-control-plane:6443`.
2. **`clusteradm accept` timing** — run it on the hub **after** join finishes; if CSR is
   not ready yet, wait a few seconds and retry.
3. **MultiKueue connection failure** — trim `integrations.frameworks` on both clusters to
   only the installed frameworks, otherwise it fails on missing CRDs (e.g. `XGBoostJob`).
4. **kubeconfig server address** — must be hub-pod-reachable: use
   `https://managed-control-plane:6443`.
5. **v1beta2 API changes** — `MultiKueueCluster.spec.clusterSource.kubeConfig` (nested),
   and `ClusterQueue.spec.admissionChecksStrategy.admissionChecks[].name` (the flat
   `spec.admissionChecks` was removed).
