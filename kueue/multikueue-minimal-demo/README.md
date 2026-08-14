# MultiKueue Minimal Demo

> 中文版：[README.zh-CN.md](README.zh-CN.md) · 分步操作手册：[WALKTHROUGH.md](WALKTHROUGH.md)

Four components — **kind + Kueue + JobSet + KubeRay** — build a MultiKueue environment
spanning 3 Kubernetes clusters on your laptop, and dispatch three kinds of workload
across them: **batch/Job, JobSet and RayJob**.

**No OCM, no Karmada, no ArgoCD, no multi-cluster management platform of any kind.**
MultiKueue is a complete multi-cluster scheduler on its own; the link between clusters
is a single kubeconfig.

---

## 1. Components

Installed on **every** cluster (manager and workers alike):

| Component | Version | Purpose | Required? |
|---|---|---|---|
| kind | v0.31.0 | creates the local clusters | yes |
| Kubernetes | v1.35.0 | node image | yes (≥ 1.32) |
| **Kueue** | v0.19.1 | queueing, quota, MultiKueue dispatch | **yes** |
| JobSet | v0.12.0 | JobSet workload type | only if you run JobSets |
| KubeRay | v1.6.2 | RayJob / RayCluster workload types | only if you run Ray |

These versions are not arbitrary: Kueue v0.19.1 pins jobset v0.12.0 and kuberay v1.6.2 in
its `go.mod`, so upstream e2e validates exactly this combination.

The `k8s ≥ 1.32` floor comes from the `JobManagedBy` feature gate. MultiKueue stamps
`spec.managedBy` on the Job so the manager's native Job controller keeps its hands off,
and that gate is only enabled by default from 1.32 onwards.

---

## 2. Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│  MANAGER CLUSTER   (kind: mk-manager)          Business pods here: ZERO     │
│                                                                             │
│    kubectl apply  Job / JobSet / RayJob   (label: kueue.x-k8s.io/queue-name)│
│                              │                                              │
│                              ▼                                              │
│    ┌──────────────────────────────────────────────────────────────────┐    │
│    │  LocalQueue        user-queue                                     │    │
│    │       │                                                           │    │
│    │       ▼                                                           │    │
│    │  ClusterQueue      cluster-queue          quota: 10 CPU / 20Gi    │    │
│    │       │                                   (gate #1 — dispatch)    │    │
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
             │  (docker "kind" network)  │
             ▼                           ▼
┌───────────────────────────────┐ ┌───────────────────────────────┐
│ WORKER CLUSTER   mk-worker1   │ │ WORKER CLUSTER   mk-worker2   │
│                               │ │                               │
│  LocalQueue    user-queue     │ │  LocalQueue    user-queue     │ ← names MUST
│       │                       │ │       │                       │   match the
│       ▼                       │ │       ▼                       │   manager
│  ClusterQueue  cluster-queue  │ │  ClusterQueue  cluster-queue  │
│       quota: 2 CPU / 4Gi      │ │       quota: 2 CPU / 4Gi      │ ← gate #2
│       (the REAL admission)    │ │       (the REAL admission)    │   real capacity
│                               │ │                               │
│  ▶▶ Pods actually run here    │ │  ▶▶ Pods actually run here    │
└───────────────────────────────┘ └───────────────────────────────┘
```

### Three rules to memorise

1. **Worker namespaces and LocalQueue names must match the manager exactly.**
   MultiKueue copies the Workload verbatim; a missing same-named LocalQueue stalls it.

2. **`integrations.frameworks` must match the operators actually installed on the workers.**
   The manager opens a watch per enabled framework on every worker; a missing CRD kills the
   whole connection. See [pitfall #1](WALKTHROUGH.md#pitfall-1-a-missing-jobset-crd-breaks-the-connection).

3. **The manager never runs a business pod.** This is the most direct proof that
   MultiKueue is working.

---

## 3. Workflow

```
  USER              MANAGER CLUSTER                 WORKER w1        WORKER w2
   │                       │                            │                │
   │ ① kubectl apply job   │                            │                │
   │   (queue-name label)  │                            │                │
   ├──────────────────────>│                            │                │
   │                       │                            │                │
   │            ┌──────────┴──────────┐                 │                │
   │            │ ② Kueue webhook     │                 │                │
   │            │   suspend = true    │                 │                │
   │            │   managedBy =       │                 │                │
   │            │   .../multikueue    │                 │                │
   │            └──────────┬──────────┘                 │                │
   │                       │  native Job controller     │                │
   │                       │  sees managedBy ≠ itself   │                │
   │                       │  → does nothing            │                │
   │                       │                            │                │
   │            ┌──────────┴──────────┐                 │                │
   │            │ ③ Workload created  │                 │                │
   │            │   GATE #1: manager  │                 │                │
   │            │   ClusterQueue quota│                 │                │
   │            │   → QuotaReserved   │                 │                │
   │            └──────────┬──────────┘                 │                │
   │                       │                            │                │
   │            ┌──────────┴──────────┐                 │                │
   │            │ ④ AdmissionCheck    │                 │                │
   │            │   fires dispatcher  │                 │                │
   │            │   AllAtOnce → both  │                 │                │
   │            │ status.nominated    │                 │                │
   │            │   ClusterNames      │                 │                │
   │            └──────────┬──────────┘                 │                │
   │                       │                            │                │
   │                       │ ⑤ create remote Workload   │                │
   │                       ├───────────────────────────>│                │
   │                       ├────────────────────────────────────────────>│
   │                       │                            │                │
   │                       │        ⑥ GATE #2: worker ClusterQueue quota │
   │                       │           w1 admits FIRST  │                │
   │                       │<───────────────────────────┤                │
   │                       │                            │                │
   │            ┌──────────┴──────────┐                 │                │
   │            │ ⑦ w1 wins:          │                 │                │
   │            │  • delete the copy  │                 │                │
   │            │    on w2  ──────────┼─────────────────┼───────────────>│ ✗
   │            │  • status.cluster   │                 │                │
   │            │    Name = w1        │                 │                │
   │            │    (immutable)      │                 │                │
   │            └──────────┬──────────┘                 │                │
   │                       │                            │                │
   │                       │ ⑧ create the real Job on w1│                │
   │                       │   label: prebuilt-workload-name             │
   │                       ├───────────────────────────>│                │
   │                       │                            │                │
   │                       │           ⑨ Job controller on w1 unsuspends │
   │                       │              → PODS RUN HERE ◀◀             │
   │                       │                            │                │
   │                       │ ⑩ continuous status sync   │                │
   │                       │<══════════════════════════>│                │
   │                       │                            │                │
   │ kubectl get job       │                            │                │
   │<──────────────────────┤  status reflects w1's real execution        │
   │                       │                            │                │
   │                       │ ⑪ Workload Finished → final sync,           │
   │                       │    then delete remote objects on w1         │
   │                       ├───────────────────────────>│ ✗              │
```

### Observed Workload status

```yaml
status:
  clusterName: mk-worker2            # where it ran (immutable once set)
  admissionChecks:
  - name: multikueue-check
    state: Ready
    message: The workload was admitted on "mk-worker2"
  conditions:
  - type: QuotaReserved              # GATE #1 — manager let it through
    status: "True"
    message: Quota reserved in ClusterQueue cluster-queue
  - type: Admitted                   # GATE #2 — a worker took it
    status: "True"
  - type: PodsReady
    status: "True"
```

---

## 4. Quota enforcement

The most commonly misunderstood part of MultiKueue: **there are two levels of quota, and
they mean completely different things.**

### Level 1 — manager ClusterQueue: a dispatch throttle, not an execution gate

The manager's quota decides **how many Workloads may enter the dispatch pipeline at once**.
A Workload must reach `QuotaReserved` on the manager before the MultiKueue AdmissionCheck
is even triggered.

This level is **notional accounting**: no pod ever consumes resources on the manager. It is
purely an admission throttle.

### Level 2 — worker ClusterQueue: the real execution gate

The worker's quota is **real accounting**, mapping to that cluster's physical capacity. The
remote Workload copy goes through a complete, standard Kueue admission there — quota,
ResourceFlavor matching, borrowing, preemption, all of it. If the worker says no, nothing runs.

### How to size the two levels

Upstream guidance: **manager quota ≈ the sum of all worker quotas.**

| Configuration | Consequence |
|---|---|
| manager quota **much lower** than the worker total | workers sit idle — the manager is throttling |
| manager quota **much higher** than the worker total | the manager dispatches Workloads nobody can accept, creating and monitoring remote objects for nothing |
| manager quota ≈ worker total | healthy |

This demo **deliberately breaks that rule**: the manager gets 10 CPU while the two workers
hold 2 CPU each (4 total). That is a teaching choice — it removes the manager as a
bottleneck so you can see clearly that **the workers are the ones making the real admission
decision**.

### What that looks like

Submitting 3 Jobs of 2 CPU each:

```
MANAGER — Workloads
WORKLOAD               ADMITTED   DISPATCHED-TO
job-demo-job-1-a9067   <none>     <none>          ← both workers full, waiting
job-demo-job-2-dd6ff   True       mk-worker2
job-demo-job-3-53d6e   True       mk-worker1

WORKER mk-worker1: cluster-queue   PENDING 1   ADMITTED 1
WORKER mk-worker2: cluster-queue   PENDING 1   ADMITTED 1
```

Read it like this: the manager's 10 CPU is enough for all 3 Jobs to reach `QuotaReserved`,
so all 3 got dispatched to both workers (`PENDING 1` is the losing copy still queued). But
each worker only has 2 CPU, so each admits exactly one. The third Job hangs —
**the decision belongs to the workers, not the manager**.

### Related features

- `MultiKueueManagerQuotaAutomation` (v0.18, alpha, off by default) — lets the manager
  aggregate quota from the workers automatically, removing the manual alignment work.
- `ResourceFlavor` names must line up between manager and worker, or the copied Workload
  cannot be admitted. Both sides here use `default-flavor`.

---

## 5. Dispatch strategy

The logic that picks *which* workers get a Workload is the **dispatcher**, configured under
`multiKueue.dispatcherName` in the Kueue configuration. Available since Kueue v0.13.

| Strategy | Name | Behaviour |
|---|---|---|
| **AllAtOnce** (default) | `kueue.x-k8s.io/multikueue-dispatcher-all-at-once` | Nominates **every** cluster in the MultiKueueConfig at once, creates a remote Workload on each, **first to admit wins**, the rest are deleted |
| **Incremental** | `kueue.x-k8s.io/multikueue-dispatcher-incremental` | Nominates in waves of `stepSize` (default 3). If nobody admits within 5 minutes, the next wave is added, until admitted or all clusters are nominated |
| **Custom** | any controller name | Kueue only manages the remote copies; your controller picks the target clusters |

### What this demo uses

**AllAtOnce**, stated explicitly in `manifests/kueue-config.yaml`:

```yaml
multiKueue:
  dispatcherName: kueue.x-k8s.io/multikueue-dispatcher-all-at-once
  # only honoured by the incremental dispatcher:
  # incrementalDispatcherConfig:
  #   stepSize: 1
  workerLostTimeout: 15m
  gcInterval: 1m
```

With only 2 workers, AllAtOnce and Incremental (default stepSize 3) behave identically.
It is written out to make the knob visible and easy to change.

### Choosing between them

- **AllAtOnce** — fastest start (all clusters compete simultaneously), at the cost of
  briefly creating a remote object on N clusters. Use it for small fleets.
- **Incremental** — gentler at scale, avoiding a burst of objects across dozens of clusters.
  And since v0.19, the `MultiKueueIncrementalDispatcherRespectConfigOrder` gate (beta, on
  by default) makes waves follow the order in `MultiKueueConfig.spec.clusters` — which
  effectively **turns that list into a preference list**, enabling policies like "prefer
  the on-prem cluster, overflow to cloud".

### Observing dispatch

```bash
# clusters currently nominated, decision still open
kubectl --context kind-mk-manager -n default get workloads \
  -o custom-columns='WL:.metadata.name,NOMINATED:.status.nominatedClusterNames'

# the winner (immutable once set; nominatedClusterNames is cleared)
kubectl --context kind-mk-manager -n default get workloads \
  -o custom-columns='WL:.metadata.name,WINNER:.status.clusterName'
```

---

## 6. Layout

```
multikueue-minimal-demo/
├── README.md                       # this file — architecture (English)
├── README.zh-CN.md                 # architecture (Chinese)
├── WALKTHROUGH.md                  # step-by-step commands + real output (English)
├── WALKTHROUGH.zh-CN.md            # step-by-step commands + real output (Chinese)
├── manifests/
│   ├── kueue-config.yaml           # Kueue config: integrations + dispatch strategy
│   ├── worker-queues.yaml          # worker-side queues (applied to every worker)
│   ├── worker-multikueue-rbac.yaml # worker-side SA/RBAC the manager authenticates as
│   └── manager-multikueue.yaml     # manager-side queues + MultiKueue wiring
├── examples/
│   ├── jobs.yaml                   # example 1: three batch/v1 Jobs
│   ├── jobset.yaml                 # example 2: JobSet
│   └── rayjob.yaml                 # example 3: RayJob
└── scripts/
    ├── common.sh                   # versions, cluster names, shared helpers
    ├── 0-create-clusters.sh        # create the 3 kind clusters
    ├── 1-install-frameworks.sh     # JobSet + KubeRay (MUST run before Kueue)
    ├── 2-install-kueue.sh          # Kueue + configuration
    ├── 3-setup-workers.sh          # worker queues
    ├── 4-connect.sh                # build kubeconfigs, store as manager Secrets
    ├── 5-setup-manager.sh          # manager MultiKueue wiring
    ├── run-demo-job.sh             # example 1
    ├── run-demo-jobset.sh          # example 2
    ├── run-demo-rayjob.sh          # example 3
    ├── clean-workloads.sh          # wipe all demo workloads
    ├── ctx.sh                      # switch kubectl context between the 3 clusters
    ├── status.sh                   # "submitted where vs. running where"
    ├── up.sh                       # steps 0–5 in one go
    └── down.sh                     # delete the clusters
```

---

## 7. Quick start

```bash
cd multikueue-minimal-demo

./scripts/up.sh                  # build the environment (~8–12 min)

./scripts/run-demo-job.sh        # example 1: batch/Job
./scripts/run-demo-jobset.sh     # example 2: JobSet
./scripts/run-demo-rayjob.sh     # example 3: RayJob

./scripts/status.sh              # check state at any time
./scripts/down.sh                # tear down
```

Different Kueue version (v0.16.4 also supports MultiKueue and already uses the v1beta2 API):

```bash
KUEUE_VERSION=v0.16.4 JOBSET_VERSION=v0.10.1 KUBERAY_VERSION=1.5.1 ./scripts/up.sh
```

---

## 8. When you actually do need OCM or a similar platform

This demo proves MultiKueue needs no multi-cluster management platform. These cases,
however, are where bare MultiKueue is genuinely not enough:

| Scenario | Bare MultiKueue | Needs an external platform |
|---|---|---|
| Workers behind a firewall/NAT; the manager has no routable API server address | ✗ push model, does not work | ✓ OCM is pull model |
| Registering and rotating credentials for dozens or hundreds of clusters | ✗ manual SA + Secret does not scale | ✓ automatic registration and sync |
| Dynamic placement based on cluster labels/capabilities | ✗ MultiKueueConfig is a static list | ✓ placement policies |
| A handful of clusters with routable networking | ✓ sufficient | unnecessary |

The middle ground is `MultiKueueClusterProfile` (alpha, Kueue v0.15), which sources
credentials from the standard [Cluster Inventory API](https://multicluster.sigs.k8s.io/)
`ClusterProfile` object — vendor-neutral, producible by OCM, or created by hand.
