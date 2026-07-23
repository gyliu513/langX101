# Kueue + KubeRay: RayJob Batch Queueing Demo (Step-by-Step Tutorial)

A **zero-to-working** end-to-end example: **Kueue** queues and admits a
**RayJob** on a local **kind** cluster. **No GPU needed — everything runs on
CPU** (the Ray image is multi-arch amd64+arm64, so it runs natively on Apple
Silicon too).

Every step below comes with the **real command and real output** (recorded on
macOS/Apple Silicon + Docker Desktop) — type along and you can reproduce the
whole thing.

The three components and their roles:

| Component | Role |
|-----------|------|
| **kind** | Local Kubernetes cluster (1 control-plane + 2 worker nodes) |
| **KubeRay operator** | Watches the RayJob CRD: creates an **ephemeral Ray cluster** (head + workers) plus a submitter pod per RayJob, and deletes the cluster when the job ends |
| **Kueue** | **Quota admission** via the RayJob's `spec.suspend` field: the job is only unsuspended when head + workers + submitter all fit at once |

The workload is a **Monte Carlo estimation of π**: 24 `@ray.remote` tasks fan
out across the 2 worker pods, and the driver prints how many tasks each pod
ran — visual proof the computation is actually distributed.

---

## Topology & lifecycle

```
kind cluster (kueue-rayjob-demo)
 ├─ control-plane
 ├─ worker-1 ─┐        RayJob "rayjob-pi" (admitted by Kueue, expanded by KubeRay)
 └─ worker-2 ─┴─►  ┌──────────────────────────────────────────────────┐
                   │  head pod      1 CPU / 5Gi   (GCS + dashboard,    │
                   │                num-cpus=0 — no compute tasks)     │
                   │  worker pod    1 CPU / 2Gi   ×2 (run the tasks)   │
                   │  submitter pod 0.5 CPU / 200Mi (ray job submit)   │
                   └──────────────────────────────────────────────────┘
                     Kueue charges:  3.5 CPU / ~9.2Gi total
                     (ClusterQueue quota: 4 CPU / 10Gi → exactly one job fits)
```

```
kubectl apply RayJob
   │
   ▼
Kueue: creates a Workload, spec.suspend=true (queued)
   │  does the ClusterQueue have 3.5 CPU / 9.2Gi free?
   ▼
Kueue: admit → spec.suspend=false
   │
   ▼
KubeRay operator: creates ephemeral RayCluster (1 head + 2 workers) + submitter pod
   │
   ▼
submitter: ray job submit -- python sample_code.py (driver runs on the head)
   │
   ▼
job finishes → shutdownAfterJobFinishes=true → RayCluster deleted
   │
   ▼
Kueue: quota released, next workload in the queue admitted automatically
```

This is the essential difference between RayJob and a long-lived "bare"
RayCluster: **ephemeral by design, quota keeps turning over**.

---

## Prerequisites

- `docker` (running; give Docker Desktop at least 6 CPUs / 12Gi memory)
- `kind`
- `kubectl`
- `helm` (to install the KubeRay operator)

Versions (verified working together): **KubeRay chart 1.6.2**,
**Kueue v0.18.0**, **Ray 2.46.0**. Kueue v0.18 ships with the
`ray.io/rayjob` integration **enabled by default** — no config changes.

Check the tools:

```bash
$ which docker kind kubectl helm
/usr/local/bin/docker
/usr/local/bin/kind
/usr/local/bin/kubectl
/opt/homebrew/bin/helm
```

---

## Two ways to run it

- **One-shot scripts** (just want to see it work): `./setup.sh && ./run.sh`,
  then `./cleanup.sh`.
- **Step by step** (recommended for first-timers): follow steps 1–10 below;
  each explains what is happening and which output field to look at.

---

## Step 1: Create the kind cluster

kind simulates a 3-node Kubernetes cluster (1 control-plane + 2 workers)
using 3 Docker containers.

```bash
cd kueue-rayjob-demo
kind create cluster --config kind-cluster.yaml
```

Output:

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

Confirm all 3 nodes exist (`NotReady` right after creation is normal; they
turn `Ready` within a minute):

```bash
$ kubectl get nodes
NAME                              STATUS   ROLES           AGE   VERSION
kueue-rayjob-demo-control-plane   Ready    control-plane   1m    v1.35.0
kueue-rayjob-demo-worker          Ready    <none>          1m    v1.35.0
kueue-rayjob-demo-worker2         Ready    <none>          1m    v1.35.0
```

---

## Step 2: Pre-load the Ray image into the kind nodes

The Ray image is ~800MB compressed. Without pre-loading, every kind node
pulls it separately. Pull once locally, then inject into both worker nodes:

```bash
# Skip pull if the image is already local (Docker Desktop can hang re-verifying)
docker image inspect rayproject/ray:2.46.0 >/dev/null 2>&1 || docker pull rayproject/ray:2.46.0
docker save rayproject/ray:2.46.0 -o /tmp/ray.tar
for node in $(kind get nodes --name kueue-rayjob-demo | grep -v control-plane); do
  docker exec --privileged -i "$node" \
    ctr --namespace=k8s.io images import --digests --snapshotter=overlayfs - < /tmp/ray.tar
done
rm /tmp/ray.tar
```

Output (once per node):

```
docker.io/rayproject/ray:2.46.0         	saved
application/vnd.oci.image.index.v1+json sha256:764d7d4b...
Importing	elapsed: 12.2s
```

> **Why not `kind load docker-image`?** With Docker's containerd image store
> enabled (the default in recent Docker Desktop), `kind load` fails with
> `ctr: content digest ... not found` — its hardcoded `--all-platforms` flag
> trips over multi-arch attestation manifests. The manual import above
> (without that flag) works in both modes. The control-plane node is skipped:
> it is tainted and no Ray pods land there.

Verify the image is inside a node:

```bash
$ docker exec kueue-rayjob-demo-worker crictl images | grep rayproject
docker.io/rayproject/ray    2.46.0    8a6d155dff140    845MB
```

---

## Step 3: Install the KubeRay operator

The KubeRay operator is an ordinary Deployment. It registers the RayCluster /
RayJob / RayService CRDs and reconciles them. Install via Helm:

```bash
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm repo update kuberay
helm upgrade --install kuberay-operator kuberay/kuberay-operator \
  --version 1.6.2 --namespace kuberay-system --create-namespace
kubectl wait --for=condition=Available --timeout=300s \
  -n kuberay-system deploy/kuberay-operator
```

Verify the operator is running and the CRDs exist:

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

(KubeRay 1.6 registers 4 CRDs — `raycronjobs` is the scheduled-job type
added in 1.6; this demo doesn't use it.)

---

## Step 4: Install Kueue

```bash
kubectl apply --server-side -f \
  "https://github.com/kubernetes-sigs/kueue/releases/download/v0.18.0/manifests.yaml"
kubectl wait --for=condition=Available --timeout=300s \
  -n kueue-system deploy/kueue-controller-manager
```

Verify:

```bash
$ kubectl get pods -n kueue-system
NAME                                        READY   STATUS    RESTARTS   AGE
kueue-controller-manager-5cc7bd8db4-jxnkq   1/1     Running   0          1m
```

> Kueue's webhooks take ~15 more seconds to start serving after the
> Deployment turns `Available`. If the next step fails with a webhook
> connection error, wait a few seconds and retry.

---

## Step 5: Create the Kueue quota objects

This is the **administrator's** step. Three layers:

- **ResourceFlavor**: a "model" of resources (this demo uses one untyped
  default flavor matching all nodes);
- **ClusterQueue**: the cluster-wide quota pool — **4 CPU / 10Gi**;
- **LocalQueue**: the namespaced submission entry point users point their
  RayJobs at.

```bash
kubectl apply -f 00-kueue-resources.yaml
```

```
resourceflavor.kueue.x-k8s.io/default-flavor created
clusterqueue.kueue.x-k8s.io/rayjob-cluster-queue created
localqueue.kueue.x-k8s.io/rayjob-user-queue created
```

Verify:

```bash
$ kubectl get clusterqueue,localqueue
NAME                                               COHORT   PENDING WORKLOADS
clusterqueue.kueue.x-k8s.io/rayjob-cluster-queue            0

NAME                                          CLUSTERQUEUE           PENDING WORKLOADS   ADMITTED WORKLOADS
localqueue.kueue.x-k8s.io/rayjob-user-queue   rayjob-cluster-queue   0                   0
```

**How the quota math works.** Kueue splits one RayJob into 3 PodSets:

| PodSet | Request |
|--------|---------|
| head | 1 CPU + 5Gi |
| cpu-workers ×2 | 2 CPU + 4Gi |
| submitter | 0.5 CPU + 200Mi |
| **Total** | **3.5 CPU + ~9.2Gi** |

Note that **the submitter pod is charged too** — a real gotcha we hit: with
an 8Gi quota the job stayed `Suspended`, short by exactly 200Mi.

---

## Step 6: Submit the RayJob (user's view)

From here on it's the **user's view**: all it takes is one label naming the
queue.

```yaml
metadata:
  name: rayjob-pi
  labels:
    kueue.x-k8s.io/queue-name: rayjob-user-queue   # without this, Kueue ignores the job
```

Submit the driver script (ConfigMap) and the RayJob:

```bash
kubectl apply -f 01-ray-code-configmap.yaml
kubectl apply -f 02-rayjob.yaml
```

```
configmap/rayjob-pi-code created
rayjob.ray.io/rayjob-pi created
```

Watch Kueue react immediately — it creates a Workload object and reserves
quota for the whole gang (`ADMITTED=True`):

```bash
$ kubectl get workloads -o wide
NAME                     QUEUE               RESERVED IN            ADMITTED   FINISHED   AGE
rayjob-rayjob-pi-665b4   rayjob-user-queue   rayjob-cluster-queue   True                  5s

$ kubectl get rayjob
NAME        JOB STATUS   DEPLOYMENT STATUS   RAY CLUSTER NAME   START TIME             AGE
rayjob-pi                Initializing        rayjob-pi-5hsrj    2026-07-23T16:00:03Z   5s
```

Reading the fields:

- Workload `ADMITTED=True`: quota fits, Kueue flipped `spec.suspend` to
  `false` — the job is released;
- RayJob `DEPLOYMENT STATUS: Initializing`: KubeRay took over and is building
  the ephemeral cluster `rayjob-pi-5hsrj`.

If the quota did NOT fit, the RayJob would sit in `Suspended` with an empty
`ADMITTED` column — step 10 stages exactly that scenario.

---

## Step 7: Watch the ephemeral Ray cluster come up

```bash
$ kubectl get pods -o wide
NAME                                       READY   STATUS    AGE   NODE
rayjob-pi-5hsrj-cpu-workers-worker-dsl7b   0/1     Running   12s   kueue-rayjob-demo-worker2
rayjob-pi-5hsrj-cpu-workers-worker-k8h7v   0/1     Running   12s   kueue-rayjob-demo-worker2
rayjob-pi-5hsrj-head-qktbh                 1/1     Running   12s   kueue-rayjob-demo-worker
```

- **head pod**: runs `ray start --head` — GCS (cluster metadata) and the
  dashboard (port 8265, which is also the job submission API);
- **worker pods**: an init container `wait-gcs-ready` blocks until the head
  is up (that's why `READY 0/1` at first), then
  `ray start --address=<head>:6379` registers them;
- once the head is Ready, KubeRay creates a **submitter pod** (a k8s Job)
  that runs `ray job submit --address http://<head-svc>:8265 -- python
  /home/ray/samples/sample_code.py`.

Wait for the head:

```bash
kubectl wait --for=condition=Ready pod -l ray.io/node-type=head --timeout=600s
```

---

## Step 8: Stream the job logs

The driver output is relayed through the submitter pod:

```bash
kubectl logs -f -l job-name=rayjob-pi
```

Real output (trimmed):

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

Notes:

- `CPU: 2.0`: the cluster has 2 logical CPUs total — the head runs with
  `num-cpus: "0"` (best practice: control-plane only), so only the 2 workers
  contribute 1 CPU each;
- the 24 tasks land on the two workers only, 0 on the head. The exact split
  varies a little between runs (12/12, 14/10, ...) depending on scheduling
  timing — that's normal.

---

## Step 9: Completion and automatic teardown

```bash
$ kubectl get rayjob
NAME        JOB STATUS   DEPLOYMENT STATUS   RAY CLUSTER NAME   START TIME             END TIME               AGE
rayjob-pi   SUCCEEDED    Complete            rayjob-pi-5hsrj    2026-07-23T16:00:03Z   2026-07-23T16:00:33Z   31s
```

~30 seconds after completion (`ttlSecondsAfterFinished: 30`), the ephemeral
RayCluster is deleted, the Workload is marked finished, and the quota is
released:

```bash
$ kubectl get raycluster
No resources found in default namespace.

$ kubectl get workloads -o wide
NAME                     QUEUE               RESERVED IN            ADMITTED   FINISHED   AGE
rayjob-rayjob-pi-665b4   rayjob-user-queue   rayjob-cluster-queue   True       True       71s
```

`FINISHED=True` + no RayCluster = **the quota is back in the pool**.

---

## Step 10: The queueing experiment (Kueue's whole point)

The quota (4 CPU / 10Gi) fits exactly one RayJob (3.5 CPU / 9.2Gi). Submit a
second one while the first is still running:

```bash
kubectl delete rayjob rayjob-pi        # delete the finished job from step 9 first!
sleep 5
kubectl apply -f 02-rayjob.yaml        # resubmit the first job (starts running)
sleep 10
kubectl apply -f 03-rayjob-second.yaml # submit the second while the first runs
```

> **Why delete first?** Re-applying a RayJob that is already `Complete` does
> **not** re-run it (it stays Complete and holds no quota), so the second job
> would be admitted immediately and you'd never see it queue.

The second one can't get in — it **queues** (real output):

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

Ask Kueue why it's holding the job back:

```bash
$ kubectl describe workload rayjob-rayjob-pi-2-e6da8
...
Message:  couldn't assign flavors to pod set head: insufficient unused quota
          for cpu in flavor default-flavor, 500m more needed, insufficient
          unused quota for memory in flavor default-flavor, 4296Mi more needed; ...
Reason:   Pending
```

Then **do nothing** — just wait for the first job to finish. Look at the
timestamps:

```bash
$ kubectl get rayjob
NAME          JOB STATUS   DEPLOYMENT STATUS   START TIME             END TIME
rayjob-pi     SUCCEEDED    Complete            2026-07-23T16:02:31Z   2026-07-23T16:03:00Z
rayjob-pi-2   SUCCEEDED    Complete            2026-07-23T16:03:01Z   2026-07-23T16:03:31Z
```

The first job ended at **16:03:00**; the second was admitted at
**16:03:01** — one second after the quota came back. That's the whole loop:
**ephemeral clusters → quota turnover → the queue advances by itself**.

---

## Step 11: Cleanup

```bash
kind delete cluster --name kueue-rayjob-demo
```

---

## Files

| File | Contents |
|------|----------|
| `kind-cluster.yaml` | kind cluster: 1 control-plane + 2 workers |
| `00-kueue-resources.yaml` | ResourceFlavor / ClusterQueue (4 CPU / 10Gi) / LocalQueue |
| `01-ray-code-configmap.yaml` | Driver script (Monte Carlo π), mounted into the head pod |
| `02-rayjob.yaml` | The RayJob: queue-name label + ephemeral cluster spec |
| `03-rayjob-second.yaml` | Second RayJob for the step-10 queueing experiment |
| `setup.sh` | Steps 1–5 in one shot |
| `run.sh` | Steps 6–9 in one shot |
| `cleanup.sh` | Step 11 |

---

## Key fields cheat sheet

- `metadata.labels."kueue.x-k8s.io/queue-name"` — which LocalQueue to submit
  to; **without it Kueue ignores the RayJob entirely**.
- `spec.suspend` — Kueue's control point: `true` while queued, flipped to
  `false` on admission. **Never set it by hand.**
- `spec.shutdownAfterJobFinishes: true` — required with Kueue: the ephemeral
  cluster must be deleted at the end so its quota is released (RayJobs cannot
  reuse existing RayClusters).
- `resources.requests` — what Kueue charges, per head + worker groups +
  **submitter**; `limits` is what Ray uses to size the node.
- `rayStartParams.num-cpus: "0"` (head) — keep compute tasks off the head;
  it is control-plane only.
- At most **17 worker groups** (a Workload allows 18 PodSets; the head takes
  one).

---

## Gotchas (real problems hit while building this demo)

All of these were actually encountered; the fixes are baked into the
YAML/scripts:

1. **`docker pull` hangs with no output (image already local)**
   On Docker Desktop, re-running `docker pull` for an image that is already
   present can sit silently for a long time while it re-checks metadata against
   the registry. Skip the pull if you already have `rayproject/ray:2.46.0`
   (`setup.sh` checks this automatically).

2. **`kind load docker-image` fails with `ctr: content digest ... not found`**
   Known issue when Docker's containerd image store is enabled
   (`--all-platforms` vs. multi-arch attestation manifests). Fix: the manual
   `ctr import` shown in step 2.

3. **Head pod OOMKilled (2Gi and 3Gi both insufficient)**
   The Ray 2.46 head idles at **~3.8GB** (GCS + dashboard spawn ~10 python
   subprocesses at ~300MB each; measured `memory.peak` 3.78GB). Give the
   head at least **5Gi**.

4. **`ValueError: Attempting to cap object store memory usage at ... bytes`**
   Ray auto-sizes the object store from cgroup `memory.current`, which
   **includes page cache**; right after image unpack that leaves almost
   nothing and the store gets 3MB (below the 75MB minimum) → crash. Fix:
   set `object-store-memory: "268435456"` explicitly in `rayStartParams`.

5. **Job killed by Ray: `Task was killed due to the node running low on memory`**
   With a 4Gi head the idle usage was 3.81/4.00GB = 95.2% — just over Ray's
   memory-monitor kill threshold (95%), so the job driver got killed. Same
   fix as #2: 5Gi head for headroom.

6. **RayJob stuck `Suspended`; `describe workload` says 200Mi short**
   Kueue **also charges the submitter pod** (0.5 CPU / 200Mi). A quota sized
   only for head+workers (8Gi) is not enough. Size the quota for all three
   PodSets plus headroom.

---

## Switching to GPU

1. Replace kind with a real GPU cluster (or kind + a GPU device plugin).
2. `00-kueue-resources.yaml`: add `"nvidia.com/gpu"` to `coveredResources`
   with a quota; add the GPU nodes' `nodeLabels` to the ResourceFlavor.
3. `02-rayjob.yaml`: add `nvidia.com/gpu: "1"` to the worker requests/limits
   and switch the image to `rayproject/ray:2.46.0-gpu`.
4. Ray registers GPUs automatically; tasks claim them with
   `@ray.remote(num_gpus=1)`.
