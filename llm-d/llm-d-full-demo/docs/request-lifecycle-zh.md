# llm-d 请求生命周期与 CRD/CR 详解（面向初学者）

> 本文档基于 **2026-08-28** 在 `llm-d-full-demo`（Gateway API / agentgateway 模式）上的一次**全新重跑**编写：
> Kind 集群从零创建，`llm-d-router`（EPP + routing-sidecar）与 `llm-d-inference-payload-processor`（IPP）三个镜像
> 均从各自仓库的 **`upstream/main`** 重新 `git fetch` + `docker build`（不是复用旧镜像）。文中出现的所有
> YAML、trace span、metric 数值，都是这次真实运行中 `kubectl get -o yaml` / Jaeger API / Prometheus API 抓取下来的
> 原始输出，不是手写示例。
>
> 目标读者：第一次接触 llm-d 的人。读完后你应该能回答：“我发一个 prompt 进去，这个请求依次经过了哪些
> 组件？每个组件在等哪个 CRD 的哪个字段？我怎么用 `kubectl` 看到它当前的状态？”
>
> 与主 [README.md](../README.md) 的关系：README 是**可执行的安装步骤**（第 3 节）和**串好的验证结果**
> （第 4 节）；本文是**原理讲解**——同一套集群，但重点讲“为什么”和“CR 里每个字段是什么意思”。建议先看
> README 把环境跑起来，再对照本文理解每一步。

---

## 目录

1. [核心概念：5 分钟建立心智模型](#1-核心概念5-分钟建立心智模型)
2. [整体架构图与组件表](#2-整体架构图与组件表)
3. [涉及的所有 CRD/CR 速查手册](#3-涉及的所有-crdcr-速查手册)
4. [一次请求的完整生命周期 —— 走 precise-prefix 路径](#4-一次请求的完整生命周期--走-precise-prefix-路径)
5. [第二条路径：P/D（Prefill/Decode）分离](#5-第二条路径pd-prefilldecode-分离)
6. [可观测性是怎么串起来的](#6-可观测性是怎么串起来的)
7. [本次重跑踩到的 upstream 破坏性变更（附修复）](#7-本次重跑踩到的-upstream-破坏性变更附修复)
8. [常见问题速查](#8-常见问题速查)

---

## 1. 核心概念：5 分钟建立心智模型

在深入细节之前，先建立几个关键概念，后面所有内容都是围绕它们展开的：

- **Gateway API 是"声明式"的**：你不是直接告诉 Envoy/agentgateway "把 `/v1/chat/completions` 转发到哪个
  Pod"，而是创建一堆 CR（`Gateway`、`HTTPRoute`、`InferencePool`……），agentgateway 的**控制面**持续 watch
  这些 CR，把它们编译成实际的转发规则（xDS 配置），推给**数据面**代理。这就是为什么你会看到大量
  `status.conditions` —— 那是控制面在告诉你"我看到你的 CR 了，而且已经生效"。
- **EPP（Endpoint Picker）不是 Kubernetes 自带的东西，是 llm-d 加的"大脑"**。标准的 Gateway API Inference
  Extension 只定义了 `InferencePool` 这个"一组可路由的 Pod"的概念；真正"选哪个 Pod"这件事，是通过
  `ext_proc`（gRPC 外部处理器）协议，把决策权交给一个叫 EPP 的进程。agentgateway 每收到一个请求，都会先
  经过一次到 EPP 的 gRPC 往返，问它"这个请求该发去哪个 Pod"，EPP 回答后，agentgateway 才真正转发。
- **CRD 定义"形状"，CR 是"一个实例"，`status` 字段是"实际状态"**。比如 `InferencePool`（CRD）定义了
  "一组可路由的推理 Pod长什么样"；`llm-d`（CR，具体的一个 `InferencePool` 对象）就是"精确前缀缓存这个池
  子"；它的 `status.parents[].conditions` 就是 agentgateway 告诉你"我已经把这个池子接进路由了"。
- **一个请求 = 一条分布式 trace**。因为所有组件（agentgateway、IPP、EPP、routing-sidecar）都用 OpenTelemetry
  导出 span 到同一个 `otel-collector` → `jaeger`，并且互相传递 W3C `traceparent`，所以你可以在 Jaeger 里
  把"这一个 prompt 都经过了谁、每一步做了什么、花了多久"看得清清楚楚。**本文后面几乎所有的"输入/输出"都是
  直接从真实 trace 的 span 属性里截出来的**。

---

## 2. 整体架构图与组件表

本次验证的完整拓扑（精确前缀缓存池 + P/D 分离池，共用一个 Gateway）：

```text
                                          ┌─────── 默认路由(PathPrefix /) ───────▶ InferencePool "llm-d"
                                          │              (EPP: precise-prefix)        │
                                          │                                           ├──▶ vLLM 副本 1 ┐ KV 事件
 客户端 ─HTTP─▶ agentgateway ─ext_proc─▶ IPP ─▶(路由决策)                              └──▶ vLLM 副本 2 ┘ (ZMQ :5556)
              (Gateway API 数据面,        (PreRouting 阶段)   │                                          │
               trace 的根 span)                              └─ header x-llm-d-pool:pd ──▶ InferencePool "llm-d-pd"
                                                                     (EPP: P/D 插件链)         │         │
                                                                                               ▼         │
                                                                    routing-sidecar ──prefill──▶ pd-prefill
                                                                     (跑在 pd-decode 里)  ──decode───▶ pd-decode
   trace ────────────────────────────── OTLP gRPC :4317 ─────▶ otel-collector ──▶ jaeger
   metric ─────────────────── ServiceMonitor / PodMonitor ──▶ Prometheus ──────▶ Grafana ◀────────────────┘
```

| 组件 | 命名空间 | 作用 | 由哪个 CR 驱动 |
| --- | --- | --- | --- |
| `agentgateway`（控制面） | `agentgateway-system` | 实现 Gateway API + Gateway API Inference Extension 的控制器；watch `Gateway`/`HTTPRoute`/`InferencePool`/`AgentgatewayPolicy`，把它们编译成数据面配置并通过 xDS 下发 | `GatewayClass` |
| `llm-d-inference-gateway`（数据面） | `llm-d` | 真正处理 HTTP 流量的代理进程；trace **根 span** 是 `POST /*`；把 W3C `traceparent` 注入到每一次 `ext_proc` 调用里 | `Gateway` |
| `payload-processor`（IPP） | `llm-d` | llm-d 的 **Inference Payload Processor**，作为 `PreRouting` 阶段的 `ext_proc` 挂载。本次验证：本环境没有配置任何 payload 转换插件，它的实际作用是解析/校验请求体、设置 `Content-Length`，**并把上游 trace 上下文透传下去**（因此它是 Jaeger 里独立的一个 service） | `AgentgatewayPolicy`(`traffic.extProc`) |
| `llm-d-epp` | `llm-d` | precise-prefix 池的 **Endpoint Picker**：打分、选 Pod，发出 `request` 等一系列 span，暴露 `llm_d_epp_*` 指标 | `InferencePool` "llm-d" |
| `llm-d-pd-epp` | `llm-d` | **第二个** EPP，运行 P/D（disaggregation）插件链，发出 `pick_disagg_profile`/`prepare_disaggregation` 等 span | `InferencePool` "llm-d-pd" |
| `precise-prefix-vllm`（×2） | `llm-d` | 真实 **vLLM CPU** 模型服务（`Qwen2.5-0.5B-Instruct`）；两副本是为了让"前缀打分器"真正有得选；通过 ZMQ `:5556` 发布 KV 事件 | 无专属 CRD，普通 `Deployment`，被 `InferencePool.spec.selector` 选中 |
| `pd-prefill` / `pd-decode` | `llm-d` | P/D 池，跑在 `llm-d-inference-sim`（模拟器）上；`pd-decode` 里带了 **`llm-d-routing-sidecar`** 原生 sidecar，负责真正驱动 prefill→decode 的两段代理 | 同上 |
| `otel-collector` + `jaeger` | `llm-d` | Trace 管道（OTLP gRPC → Jaeger） | 无 CRD，普通 Deployment |
| `kube-prometheus-stack`（`llmd` release） | `llm-d-monitoring` | Prometheus + Grafana + Operator；发现并抓取 `ServiceMonitor`/`PodMonitor` | `ServiceMonitor`/`PodMonitor` |
| `HTTPRoute` / `InferencePool` | `llm-d` | 一个 Gateway 上挂两条路由：chart 默认的 `/` → 池 `llm-d`；header 匹配的路由 → 池 `llm-d-pd` | 见第 3 节 |

镜像来源（本次全部从 `upstream/main` 重新构建，arm64）：

```console
$ docker images | grep main
ghcr.io/llm-d/llm-d-router-endpoint-picker-dev   main   ff7ff69bf604   commit ead3e86f (llm-d-router upstream/main)
ghcr.io/llm-d/llm-d-routing-sidecar              main   f2c645d6af4b   commit ead3e86f (同上，同一仓库)
ghcr.io/llm-d/llm-d-inference-payload-processor  main   a6a68d4ebbba   commit ff85c3d  (llm-d-inference-payload-processor upstream/main)
```

---

## 3. 涉及的所有 CRD/CR 速查手册

这一节是"字典"：每种 CRD 讲清楚——它是谁定义的、谁创建 CR、谁消费（watch）它、`spec` 里关键字段是什么
意思、`status` 里的 condition 都代表什么。**所有示例 YAML 都是本次真实集群里 `kubectl get -o yaml` 的原始
输出**（省略了 `resourceVersion`/`uid` 等噪音字段）。

### 3.1 `GatewayClass`（`gateway.networking.k8s.io/v1`）

- **谁创建**：`agentgateway` Helm chart 自己创建（不是你手工 apply 的）。
- **谁消费**：你自己的 `Gateway` CR 通过 `spec.gatewayClassName` 引用它，告诉 Kubernetes "这个 Gateway 该
  由谁来实现"。
- **关键字段**：`spec.controllerName` = `agentgateway.dev/agentgateway`，是控制器用来"认领"匹配的
  `Gateway`/`HTTPRoute` 的身份标识。

```console
$ kubectl get gatewayclass agentgateway
NAME           CONTROLLER                      ACCEPTED   AGE
agentgateway   agentgateway.dev/agentgateway   True       3s
```

`ACCEPTED=True` 就是控制器在说"我认领了这个 class，我会去实现所有指向它的 Gateway"。

### 3.2 `Gateway`（`gateway.networking.k8s.io/v1`）—— 数据面的"入口"

- **谁创建**：`kubectl apply -k $LLMD_REPO/guides/recipes/gateway/agentgateway -n llm-d`（README 3.5）。
- **谁消费**：agentgateway 控制器 watch 到它后，会真正**起一个数据面 Pod**（也叫
  `llm-d-inference-gateway`），并把 `spec.listeners` 编译成监听端口。
- **关键字段**：
  - `spec.gatewayClassName`：指回 3.1 的 GatewayClass。
  - `spec.listeners[].port` / `.protocol`：本例是 `80/HTTP`。
  - `spec.listeners[].allowedRoutes.namespaces.from: All`：允许任意命名空间的 `HTTPRoute` 挂载到这个监听器上。

真实抓取（本次运行）：

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: llm-d-inference-gateway
  namespace: llm-d
spec:
  gatewayClassName: agentgateway
  listeners:
  - allowedRoutes:
      namespaces:
        from: All
    name: default
    port: 80
    protocol: HTTP
status:
  attachedListenerSets: 0
  conditions:
  - reason: Accepted
    status: "True"
    type: Accepted
  - message: Successfully programmed Gateway
    reason: Programmed
    status: "True"
    type: Programmed
  listeners:
  - attachedRoutes: 2          # 本次有 2 条 HTTPRoute 挂在这个监听器上（llm-d + llm-d-pd）
    conditions:
    - reason: Accepted
      status: "True"
      type: Accepted
    - reason: NoConflicts
      status: "False"          # False 是"没有冲突"的意思(Conflicted 这个 type 为 False 才是好事)
      type: Conflicted
    - reason: Programmed
      status: "True"
      type: Programmed
    - reason: ResolvedRefs
      status: "True"
      type: ResolvedRefs
```

**怎么读 `status.conditions`**：Gateway API 的 condition 遵循 Kubernetes 通用约定——`type` 是"检查项"，
`status` 是这一项的真假。这里 4 个 condition 都是"好"状态：`Accepted`=True（语法/权限没问题）、
`Programmed`=True（xDS 配置已经下发到数据面）、`ResolvedRefs`=True（所有它引用的对象，比如
`InferencePool`，都能找到）、`Conflicted`=**False**（唯一一个"False 才是好事"的 condition，意思是"没有
冲突"）。`attachedRoutes: 2` 直接告诉你有几条 `HTTPRoute` 真正挂上了这个监听器——如果你新建了一条
`HTTPRoute` 但这个数字没涨，说明路由没匹配上（比如 `parentRefs` 写错了）。

### 3.3 `HTTPRoute`（`gateway.networking.k8s.io/v1`）—— "匹配规则 → 转发到哪个池子"

- **谁创建**：precise-prefix 那条由 `llm-d-router-gateway` chart 自动创建（`httpRoute.create=true`）；
  P/D 那条是我们手工 `kubectl apply -f manifests/optional/pd/httproute-pd.yaml`。
- **谁消费**：agentgateway 控制面把它编译进路由表；**匹配到某个请求后，`backendRefs` 决定转发到哪个
  `InferencePool`**（注意：不是转发到某个具体 Pod，而是转发到一个"池子"，具体选哪个 Pod 是 EPP 的工作，
  见 3.4）。

precise-prefix 池的默认路由（真实抓取）：

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm-d
  namespace: llm-d
spec:
  parentRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: llm-d-inference-gateway
  rules:
  - backendRefs:
    - group: inference.networking.k8s.io
      kind: InferencePool
      name: llm-d
      weight: 1
    matches:
    - path: {type: PathPrefix, value: /}
    timeouts:
      request: 300s
status:
  parents:
  - conditions:
    - reason: Accepted
      status: "True"
      type: Accepted
    - reason: ResolvedRefs
      status: "True"
      type: ResolvedRefs
```

P/D 池的 header 匹配路由（真实抓取，注意 `matches[].headers`）：

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm-d-pd
  namespace: llm-d
spec:
  parentRefs:
  - {group: gateway.networking.k8s.io, kind: Gateway, name: llm-d-inference-gateway}
  rules:
  - backendRefs:
    - {group: inference.networking.k8s.io, kind: InferencePool, name: llm-d-pd, weight: 1}
    matches:
    - headers:
      - {name: x-llm-d-pool, type: Exact, value: pd}
      path: {type: PathPrefix, value: /}
```

两条路由都匹配 `PathPrefix: /`，但带 header 精确匹配的规则优先级更高（Gateway API 规范：更具体的匹配
优先），所以**带 `x-llm-d-pool: pd` 请求头的请求走 P/D 池，其余所有请求走默认的 precise-prefix 池**。

### 3.4 `InferencePool`（`inference.networking.k8s.io/v1`）—— "一组可路由的推理 Pod + 谁来决策"

这是整个体系里**最核心**的 CRD，它把两件事绑在一起：① 用 label selector 圈出一组 Pod；② 指定由哪个
Service 来做 `ext_proc` 决策（也就是 EPP）。

- **谁创建**：`llm-d-router-gateway` Helm chart（每次 `helm install` 一个 release 就会创建一个
  `InferencePool`，release 名就是池名）。
- **谁消费**：`HTTPRoute.backendRefs` 引用它来决定转发目标；agentgateway 控制面 watch 它的
  `spec.endpointPickerRef` 后，在数据面为**这个池子的所有流量**挂一个到 EPP 的 `ext_proc` 调用。

真实抓取（precise-prefix 池）：

```yaml
apiVersion: inference.networking.k8s.io/v1
kind: InferencePool
metadata:
  name: llm-d
  namespace: llm-d
spec:
  appProtocol: http
  endpointPickerRef:
    failureMode: FailOpen        # ← 关键字段，见下方解释
    kind: Service
    name: llm-d-epp
    port: {number: 9002}
  selector:
    matchLabels:
      llm-d.ai/guide: precise-prefix-cache-routing
  targetPorts:
  - number: 8000
status:
  parents:
  - conditions:
    - reason: Accepted
      status: "True"
      message: InferencePool has been accepted by controller agentgateway.dev/agentgateway
      type: Accepted
    - reason: ResolvedRefs
      status: "True"
      message: All InferencePool references have been resolved
      type: ResolvedRefs
    controllerName: agentgateway.dev/agentgateway
```

字段逐个讲：

- **`spec.selector.matchLabels`**：这个池子里包含哪些 Pod。本例是 `llm-d.ai/guide:
  precise-prefix-cache-routing`——两个 `precise-prefix-vllm-*` Pod 都带这个 label（`kubectl get pod
  --show-labels` 可以验证）。**加一个新副本只需要让新 Pod 带上同样的 label，`InferencePool` 会自动纳入**，
  不需要改任何 CR。
- **`spec.targetPorts`**：Pod 上真正服务模型请求的端口（vLLM 的 `:8000`）。
- **`spec.endpointPickerRef`**：指向做决策的 EPP Service（`llm-d-epp:9002`，这是 gRPC `ext_proc` 端口）。
  **`failureMode: FailOpen`** 是个很容易被忽略但很重要的字段——如果 EPP 挂了/超时，`FailOpen` 表示"放行，
  让 agentgateway 自己随便选一个健康 Pod 转发"，代价是丢失 KV-cache 感知路由；对照第 7 节会看到 IPP 那边
  故意配的是 `FailClosed`（默认值），一旦 IPP 挂了会导致**所有流量 500**——这是本次重跑真实踩过的坑。
- **`status.parents[].conditions`**：`Accepted=True` 代表 agentgateway 已经把这个池子接进了路由表；
  `ResolvedRefs=True` 代表 `endpointPickerRef` 指向的 Service（`llm-d-epp`）真实存在且能解析。**如果你的
  vLLM 副本迟迟收不到流量，第一步永远是先看这两个 condition 是不是 True。**

P/D 池（`llm-d-pd`）结构完全一样，只是 `selector.matchLabels: llm-d.ai/guide: pd-disaggregation`，
`endpointPickerRef.name: llm-d-pd-epp`——**这就是为什么 P/D 需要"自己的一整套 router release"**：一个 EPP
进程只能加载一份插件配置，precise-prefix 和 P/D 的调度逻辑完全不同（打分器 vs. disaggregation 决策器），
所以只能用两个独立的 `helm install`（`llm-d` 和 `llm-d-pd`），对应两个 `InferencePool`。

### 3.5 `InferenceObjective`（`llm-d.ai/v1alpha2`）—— 请求优先级

- **谁创建**：本 demo 里手工 `kubectl apply -f manifests/02-inferenceobjective.yaml`（可选，chart 默认不
  创建）。
- **谁消费**：EPP 的公平性/排队逻辑，用来给不同优先级的请求分配调度权重。

```yaml
apiVersion: llm-d.ai/v1alpha2
kind: InferenceObjective
metadata:
  name: llm-d-standard
  namespace: llm-d
spec:
  poolRef:
    group: inference.networking.k8s.io
    kind: InferencePool
    name: llm-d       # 指向 3.4 的 InferencePool，把这个"优先级策略"绑定到具体的池子
  priority: 0          # 数值越大优先级越高；同一个 poolRef 下可以创建多个不同 priority 的 InferenceObjective
```

注意这个 CR **没有 `status` 字段**——它是纯配置型的 CR，不需要控制器回填状态，EPP 只是在调度时读取它。

### 3.6 `AgentgatewayPolicy`（`agentgateway.dev/v1alpha1`）—— agentgateway 特有的"策略挂载点"

这是 agentgateway（而不是标准 Gateway API）自己扩展的 CRD，用来做 Gateway API 规范没覆盖的事情：挂
`ext_proc`、开 tracing 等。`spec.targetRefs` 决定这个策略作用在哪个对象上（本例都是整个 `Gateway`）。

**用途 A：给 Gateway 开自己的 trace 导出**（否则没有上游 `traceparent` 的请求，agentgateway 自己不会起
根 span）：

```yaml
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: gateway-tracing
  namespace: llm-d
spec:
  targetRefs:
  - {group: gateway.networking.k8s.io, kind: Gateway, name: llm-d-inference-gateway}
  frontend:
    tracing:
      backendRef: {kind: Service, name: otel-collector, port: 4317}
      protocol: GRPC
      randomSampling: "true"   # 100% 采样，demo 环境用；生产环境应调低
status:
  ancestors:
  - ancestorRef: {group: gateway.networking.k8s.io, kind: Gateway, name: llm-d-inference-gateway}
    conditions:
    - {reason: Valid, status: "True", type: Accepted}
    - {reason: Attached, status: "True", type: Attached, message: Attached to all targets}
```

**用途 B：把 IPP 挂成 `PreRouting` 阶段的 `ext_proc`**（这是 IPP 能进 trace、能在 EPP 之前拦截请求的唯一
方式——IPP 自己的 Helm chart 只认 `provider.name: istio|gke|none`，没有 agentgateway 的模板，必须靠这个
CR 手动接线）：

```yaml
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: ipp-extproc
  namespace: llm-d
spec:
  targetRefs:
  - {group: gateway.networking.k8s.io, kind: Gateway, name: llm-d-inference-gateway}
  traffic:
    phase: PreRouting          # ← 在路由决策(HTTPRoute匹配)之前就拦截
    extProc:
      backendRef: {kind: Service, name: payload-processor, port: 9004}
status:
  ancestors:
  - conditions:
    - {reason: Valid, status: "True", type: Accepted}
    - {reason: Attached, status: "True", type: Attached}
```

`status.ancestors[].conditions` 里的 `Attached=True` 是排障时最该看的字段：如果这里是 False 或者干脆没有
`ancestors`，说明这个策略压根没生效，不管你怎么发请求都不会经过 IPP。

### 3.7 `PodMonitor` / `ServiceMonitor`（`monitoring.coreos.com/v1`）—— 指标怎么被发现

- **谁创建**：`ServiceMonitor`（叫 `llm-d-epp-monitor`）由 router chart 自动创建；`PodMonitor`（叫
  `decode`）由 `kubectl apply -k .../modelserver/components/monitoring/` 创建，抓 vLLM 的 `/metrics`。
- **谁消费**：Prometheus Operator watch 这些 CR，自动生成 Prometheus 的 scrape 配置——**你完全不需要手改
  Prometheus 的配置文件**，这就是 Operator 模式的意义。

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: decode
  namespace: llm-d
  labels: {llm-d.ai/role: decode}
spec:
  podMetricsEndpoints:
  - {interval: 30s, path: /metrics, port: modelserver}
  selector:
    matchLabels: {llm-d.ai/role: decode}
```

真实验证：

```console
$ curl -s "http://localhost:9091/api/v1/targets?state=active" | grep -o 'serviceMonitor/llm-d/llm-d-epp-monitor\|podMonitor/llm-d/decode'
serviceMonitor/llm-d/llm-d-epp-monitor
podMonitor/llm-d/decode
```

两个都出现说明 Prometheus 真的发现并且在抓这两类目标——这是 `PodMonitor`/`ServiceMonitor` 这类 CRD 唯一
需要验证的事：**它有没有让 Prometheus 找到目标**，没有独立的业务语义。

---

## 4. 一次请求的完整生命周期 —— 走 precise-prefix 路径

以下是这次真实发送的请求：

```console
$ GWIP=$(kubectl get svc llm-d-inference-gateway -n llm-d -o jsonpath='{.spec.clusterIP}')
$ curl -X POST http://$GWIP:80/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","messages":[{"role":"user","content":"..."}],"max_tokens":16}'
```

在把同一个长 prompt（>64 token，正好超过 vLLM 的 block size，才能真正命中一个 KV block）连续发送 6 次后，
Jaeger 里抓到的完整 trace 长这样（**这是真实 trace 的原始 span 树，3 个 service，15 个 span**——比旧版本
文档记录的 11 span 多，第 7 节会解释为什么）：

```text
[llm-d-inference-gateway] POST /*                                            ← trace 根 span
  [payload-processor]      gateway.request
    [llm-d-router/epp]     request
      [llm-d-router/epp]     request_orchestration
        [llm-d-router/epp]       tokenize_render /v1/chat/completions/render
        [llm-d-router/epp]       produce_precise_prefix_cache
          [llm-d-router/epp]         index_lookup
        [llm-d-router/epp]       run_scheduler_profile
          [llm-d-router/epp]         filter_endpoints
          [llm-d-router/epp]         scoring
            [llm-d-router/epp]           scorer.kv-cache-utilization-scorer
            [llm-d-router/epp]           scorer.queue-scorer
            [llm-d-router/epp]           scorer.prefix-cache-scorer
          [llm-d-router/epp]         pick_endpoints
        [llm-d-router/epp]       index_add
```

下面按时间顺序把每一跳拆开讲，**每一步都配真实抓到的 span 属性**。

### Step 1 — 客户端 → agentgateway（数据面）

- **组件**：`llm-d-inference-gateway` Pod（由 3.2 的 `Gateway` CR 驱动起来的数据面代理）。
- **输入**：客户端的裸 HTTP POST（`Content-Type: application/json`，body 是 OpenAI 兼容的 chat completions
  请求）。
- **它做的事**：
  1. 用 `Gateway.status.listeners[].attachedRoutes` 里编译好的路由表匹配请求路径/header，决定走哪条
     `HTTPRoute`（本例：没带 `x-llm-d-pool` header → 走默认路由 → 目标是 `InferencePool: llm-d`）。
  2. 开启这次请求的**根 span** `POST /*`（因为配置了 3.6 用途 A 的 `AgentgatewayPolicy`，`randomSampling:
     "true"` 让它对没有上游 trace 的请求也主动起根），生成一个新的 W3C `traceparent`。
  3. 按 3.6 用途 B 的 `AgentgatewayPolicy`（`phase: PreRouting`），先把请求（连同刚生成的 `traceparent`
     header）通过 gRPC `ext_proc` 发给 IPP，**在真正做路由决策之前**。
- **输出**：一次到 IPP 的 `ext_proc` gRPC 调用，带着请求头/体和 trace 上下文。

### Step 2 — IPP（PreRouting 阶段的 ext_proc）

- **组件**：`payload-processor` Pod。
- **输入**：agentgateway 转发来的完整请求（headers + body），以及 header 里的 `traceparent`。
- **它做的事**（源码 `pkg/handlers/server.go` / `request.go`，本次验证过 `main` 分支行为）：
  1. `extractTraceContext()` 用 W3C propagator 从请求头里把 `traceparent` 解出来，**以它为父**开一个新
     span `gateway.request`——这就是为什么 EPP 后面能成为 IPP 的子节点，而不是 agentgateway 的子节点。
  2. 把 body 解析成 JSON（`HandleRequestBody`），运行配置好的 `preProcessors`/`profiles` 插件链——**本次
     部署没有配置任何自定义插件**，所以这里实际上是"验证 body 合法 + 重算 `Content-Length`"，没有做真正
     的字段改写。
  3. 把（可能被修改过的）headers 通过 `HeaderMutation` 返回给 agentgateway；同时把 trace 上下文
     `Inject` 回转发出去的 headers 里。
- **输出**：`ClearRouteCache: true` + 一组 header mutation，交回给 agentgateway，agentgateway 据此重新
  计算路由（然后才真正匹配到 `HTTPRoute`）。

> **务实的说明**：README 的旧版本把 IPP 描述成"把 body 字段 `model` 改写成 `X-Gateway-Model-Name`
> header"——那是 IPP 作为通用 payload 处理框架的**能力**，不是本次这套 `helm install ipp` 命令实际配置出
> 来的行为（本次只开了 `tracing.enabled=true` 和 `secure-serving=false`，没挂任何转换插件）。本次验证到的
> IPP 真实作用是：**校验请求体 + 在 trace 里占一跳 + 透传 trace 上下文**。想要它做 body/header 改写，需要
> 在 `payloadProcessor.pluginsCustomConfig` 里显式配置处理器插件。

### Step 3 — EPP（Endpoint Picker，precise-prefix 插件链）

这是整条链路里逻辑最复杂的一跳，对应 3.4 里 `InferencePool.spec.endpointPickerRef` 指向的 Service。EPP 收
到的也是一次 `ext_proc` gRPC 调用（这次是 agentgateway 因为 `HTTPRoute` 匹配到 `InferencePool: llm-d` 而
自动发起的，不需要额外的 `AgentgatewayPolicy`——这一点和 IPP 不同，`InferencePool.spec.endpointPickerRef`
本身就是"接线说明"）。EPP 内部按顺序做了这些事，每一步都是一个真实 span：

**3a. `tokenize_render /v1/chat/completions/render`** —— EPP Pod 里的 `vllm-render` sidecar 用真实的
Qwen tokenizer 把 messages 渲染 + 分词（这也是为什么 `2/2 Running` 的 EPP Pod 里有两个容器：`epp` +
`vllm-render`）。**输入**：chat messages 数组；**输出**：token 数组，用来判断 prompt 落在哪些 KV block 里。

**3b. `produce_precise_prefix_cache` → `index_lookup`** —— EPP 维护了一份**它自己内存里的 KV block 索引**
（不是 vLLM 自己知道，是 EPP 通过订阅 vLLM 在 ZMQ `:5556` 发布的 KV 事件，自己建的一份镜像索引）。用上一步
得到的 token 序列去查这份索引，看哪些 Pod 已经缓存了匹配的前缀 block。第 6 次重复请求时的真实属性：

```text
index_lookup                    llm_d.kv_cache.lookup.block_count = 1
                                 llm_d.kv_cache.lookup.blocks_found = 1
                                 llm_d.kv_cache.lookup.cache_hit = True      ← 真正命中了
                                 llm_d.kv_cache.lookup.pod_filter_count = 2
produce_precise_prefix_cache    llm_d.epp.producer.candidate_endpoints = 2
                                 llm_d.epp.producer.max_match_blocks = 1
                                 llm_d.epp.producer.total_blocks = 1
```

**输入**：token 序列；**输出**：`cache_hit=True` 这样的判定结果，会作为后面 `prefix-cache-scorer` 打分的
依据，写进请求的 `CycleState`（跨插件共享的临时状态，不落 CR，只存在于这一次请求的内存里）。

**3c. `run_scheduler_profile` → `filter_endpoints`** —— 从 `InferencePool.spec.selector` 圈出的所有 Pod
里，先做一轮硬性过滤（比如排除不健康的 Pod），本例两个副本都健康，全部保留进入打分阶段。

**3d. `scoring`（新增的子树，逐个打分器）** —— 这是本次重跑发现的**结构性变化**：现在每个打分器（scorer）
都单独出一个 span，而不是像旧版本那样只留一个笼统的汇总 span。真实抓到的三个打分器（都是配置在
`precise-prefix-router.values.yaml` 里的 `schedulingProfiles`）：

```text
scorer.kv-cache-utilization-scorer   weight=2   score.avg=1     score.max=1
scorer.queue-scorer                  weight=2   score.avg=1     score.max=1
scorer.prefix-cache-scorer           weight=3   score.avg=0.5   score.max=1
```

**输入**：`filter_endpoints` 过滤后剩下的候选 Pod 列表 + 上一步的 `cache_hit` 结果；**输出**：每个 Pod 在
每个维度上的分数。`prefix-cache-scorer` 的权重最高（3.0），因为它是这条路径的核心卖点——命中前缀的 Pod 会
拿到更高分。

**3e. `pick_endpoints`** —— 把每个打分器的 `score × weight` 加总，选出总分最高的 Pod。真实结果：

```text
pick_endpoints    llm_d.epp.picker.top_endpoints = ["...-6zdgq-rank-0", "...-rvx8s-rank-0"]
                  llm_d.epp.picker.top_scores    = [7, 4]
```

`7 = prefix-cache-scorer(命中时 1分 × 权重3) + kv-cache-utilization-scorer(1×2) + queue-scorer(1×2)`；没
命中前缀的那个副本只拿 4 分（缺了 prefix 那 3 分）。**这就是"KV-cache 感知路由"在数字上的样子**——两个副本
第一次都是冷的、打平分，从第二次开始命中过前缀的那个副本分数持续领先，后续同样内容的请求会一直粘在它
身上。

**3f. `index_add`** —— 请求转发出去之后，EPP 把这次请求新产生的 KV block 也加进自己的内存索引，供下一次
请求复用。**输出**：无 API 返回值，纯粹是索引的副作用更新。

**EPP 这一整段的输出**：一个 `ext_proc` 响应，告诉 agentgateway "把这次请求转发到
`precise-prefix-vllm-...-6zdgq`"（`InferencePool.spec.targetPorts` 里定义的 `:8000`）。

### Step 4 — agentgateway 转发到选中的 vLLM Pod

agentgateway 拿到 EPP 的决策后，直接把（可能已被 IPP 修改过 header 的）原始请求代理到那个 Pod 的
`:8000/v1/chat/completions`。**这一跳本身不产生新的 span**——vLLM CPU 镜像默认没有接自己的 OTel 导出器，
所以 trace 到 `pick_endpoints` 这里事实上就结束了（trace 记录的是"决策过程"，不是"推理过程"）。vLLM 生成
完成后把 completion 原路返回给 agentgateway，再原路返回给客户端。

### Step 5（背景任务，不在这次请求的 trace 里）—— vLLM 发布 KV 事件

vLLM 在处理请求的同时，通过 ZMQ `:5556` 把"我缓存了哪些 block"以事件的形式广播出去。EPP 有一个独立的
后台订阅协程持续消费这些事件，更新 3b 提到的那份内存索引。**这个机制和 HTTP 请求路径是解耦的**——即使
从来没有人发过第二个请求，只要 vLLM 在跑，这个事件流也一直在推。

---

## 5. 第二条路径：P/D（Prefill/Decode）分离

给请求加一个 header 就会走完全不同的池子：

```console
$ curl -X POST http://$GWIP:80/v1/chat/completions -H 'Content-Type: application/json' \
  -H 'x-llm-d-pool: pd' -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","messages":[...],"max_tokens":16}'
```

这次真实抓到的 trace 是 **4 个 service、28 个 span**（旧文档记录的是 21 span——本次多出的部分同样来自
"打分器拆分成独立 span"这个结构性变化）：

```text
[llm-d-inference-gateway] POST /*
  [payload-processor]        gateway.request
    [llm-d-router/epp]         request
      [llm-d-router/epp]         request_orchestration
        [llm-d-router/epp]           pick_disagg_profile          # 第1次：决定要不要跑 decode
        [llm-d-router/epp]           run_scheduler_profile        # decode 池内打分
          [llm-d-router/epp]             filter_endpoints
          [llm-d-router/epp]             scoring
            [llm-d-router/epp]               scorer.active-request-scorer
            [llm-d-router/epp]               scorer.prefix-cache-scorer
          [llm-d-router/epp]             pick_endpoints
        [llm-d-router/epp]           pick_disagg_profile          # 第2次：决定要不要跑 prefill
        [llm-d-router/epp]           run_scheduler_profile        # prefill 池内打分
          [llm-d-router/epp]             filter_endpoints
          [llm-d-router/epp]             scoring
            [llm-d-router/epp]               scorer.prefix-cache-scorer
            [llm-d-router/epp]               scorer.queue-scorer
            [llm-d-router/epp]               scorer.kv-cache-utilization-scorer
          [llm-d-router/epp]             pick_endpoints
        [llm-d-router/epp]           pick_disagg_profile          # 第3次：汇总，两段都选完了
        [llm-d-router/epp]           prepare_disaggregation       # 组装 prefill 侧的转发信息
        [llm-d-router/epp]           prepare_disaggregation       # 组装 decode 侧的转发信息
    [llm-d-routing-sidecar]    POST /v1/chat/completions
      [llm-d-routing-sidecar]      forward_request
        [llm-d-routing-sidecar]        prefill
          [llm-d-routing-sidecar]          HTTP POST               # → pd-prefill
          [llm-d-routing-sidecar]          decode
            [llm-d-routing-sidecar]            HTTP POST           # → pd-decode
```

### 5.1 为什么这次是"另一个 EPP"

`x-llm-d-pool: pd` 这个 header 让 3.3 的 `HTTPRoute(llm-d-pd)` 匹配上，`backendRefs` 指向
`InferencePool: llm-d-pd`，它的 `endpointPickerRef` 指向的是**另一个 Service**：`llm-d-pd-epp`（3.4 已
讲过为什么必须是两个独立的 EPP release）。这个 EPP 加载的插件配置完全不同——本次真实生效的配置（修复过
的版本，见第 7 节）：

```yaml
apiVersion: llm-d.ai/v1alpha1
kind: EndpointPickerConfig
plugins:
- type: disagg-headers-handler
- type: always-disagg-pd-decider     # 只要走到这个池子，就总是决定要做 P/D 分离
- type: disagg-profile-handler
  parameters:
    profiles: {decode: decode, prefill: prefill}
    deciders: {prefill: always-disagg-pd-decider}
- type: prefill-filter
- type: decode-filter
- type: prefix-cache-scorer
- type: queue-scorer
- type: kv-cache-utilization-scorer
- type: active-request-scorer
schedulingProfiles:
- name: prefill
  plugins: [prefill-filter, {prefix-cache-scorer, weight: 3}, {queue-scorer, weight: 2}, {kv-cache-utilization-scorer, weight: 2}]
- name: decode
  plugins: [decode-filter, {active-request-scorer, weight: 2}, {prefix-cache-scorer, weight: 3}]
```

### 5.2 `disagg-profile-handler` 在做什么（对应 3 次 `pick_disagg_profile`）

真实抓到的 3 次 `llm_d.epp.profile_handler.decision`：

```text
第1次: run_decode              → 先跑 "decode" scheduling profile，选出一个 decode Pod
第2次: run_prefill              → 再跑 "prefill" scheduling profile，选出一个 prefill Pod
第3次: complete_prefill-decode  → 两段都选完了，汇总决策
```

也就是说，`disagg-profile-handler` 本质是个**状态机**：先跑一遍 `decode` profile 里定义的
`filter_endpoints`/`scoring`/`pick_endpoints`（选出 decode 侧 Pod），再跑一遍 `prefill` profile（选出
prefill 侧 Pod），最后调用 `always-disagg-pd-decider` 插件确认"这次要不要真的做分离"（本例插件名字就叫
"always"，所以永远是 True）。

两次 `pick_endpoints` 的真实结果：

```text
decode 池打分:  candidate_endpoints=1  top_endpoints=["pd-decode-...-rank-0"]   top_scores=[2]
prefill 池打分: candidate_endpoints=1  top_endpoints=["pd-prefill-...-rank-0"]  top_scores=[4]
```

（本例 P/D 池每种角色只有 1 个副本，所以"打分"退化成"确认存在"，分数本身意义不大——**这跟第 4 节
precise-prefix 池 2 副本时分数才有区分度是同一个道理**。）

### 5.3 `prepare_disaggregation`（两次）

选完 Pod 后，EPP 需要把"prefill 该发去哪"这个信息编码进转发给 routing-sidecar 的请求里（因为真正发起
prefill→decode 两段调用的不是 EPP 自己，是下一跳的 routing-sidecar）：

```text
prepare_disaggregation   llm_d.epp.pd.disaggregation_used = True
                          llm_d.epp.pd.prefill_pod_address = 10.244.0.21
                          llm_d.epp.pd.prefill_pod_port = 8000
                          llm_d.epp.encode.disaggregation_used = False        ← 本例没有多模态，encode 分离用不到
                          llm_d.epp.encode.reason = no_encode_profile_result
```

**EPP 这一段的输出**：转发目标定为 `pd-decode` Pod（因为 decode 侧承载了对外的 HTTP 入口），并且把
`prefill_pod_address`/`prefill_pod_port` 塞进转发请求的 header 里，交给下一跳的 routing-sidecar。

### 5.4 `llm-d-routing-sidecar` —— 真正执行两段代理的角色

`pd-decode` Pod 是 `2/2 Running`——第二个容器就是 `llm-d-routing-sidecar`（Kubernetes 原生 sidecar，跟主
容器 `llm-d-inference-sim` 共享网络命名空间）。它是 trace 里**第四个、也是唯一非 EPP 家族的 service**：

```text
forward_request   llm_d.pd_proxy.connector = nixlv2              # KV 传输连接器类型（本例被 sim 模拟）
                   llm_d.pd_proxy.disaggregation_used = True
                   llm_d.pd_proxy.prefill_target = 10.244.0.21:8000
prefill            llm_d.pd_proxy.prefill.duration_ms = 1
                    llm_d.pd_proxy.prefill_target = 10.244.0.21:8000
decode              llm_d.pd_proxy.decode.target = localhost:8200   # decode 走本地环回，因为同 Pod
                     llm_d.pd_proxy.true_ttft_ms = 1
                     llm_d.pd_proxy.total_duration_ms = 1
```

**输入**：EPP 传下来的、带 `prefill_pod_address` 的请求；**它做的事**：先 `HTTP POST` 到
`pd-prefill:8000` 发起 prefill（只算 prompt 的 KV，不生成 token），KV 结果通过 `nixlv2` connector "传输"
给 decode 侧（本例是模拟器 `llm-d-inference-sim`，真实握手了协议但没有真的传输 KV 数据——第 4 节已经解释
过 CPU vLLM 没有 `nixl` 模块，做不了真实的 P/D）；再 `HTTP POST` 到本地 `localhost:8200`（同 Pod 内的
`llm-d-inference-sim` 主容器）发起 decode，拿到最终 completion 返回。**输出**：合并后的 OpenAI 格式
响应，原路返回给客户端。

---

## 6. 可观测性是怎么串起来的

### 6.1 一条 trace 是怎么"接力"传下去的

核心是 [W3C Trace Context](https://www.w3.org/TR/trace-context/) 标准的 `traceparent` header，每一跳都
做同一件事：**从收到的请求头里 `Extract` 出父 span，把自己的新 span 挂在它下面作为子节点，再 `Inject` 回
转发出去的请求头里**。四个组件依次是：

```
agentgateway (起根 span，Inject traceparent)
  → IPP (Extract 父=gateway根span, 起 gateway.request, Inject)
    → EPP (Extract 父=IPP的span, 起 request, Inject)
      → routing-sidecar (仅 P/D 路径; Extract 父=EPP的span, 起 forward_request)
```

**这也是为什么 IPP 挂载的 `phase` 很关键**：3.6 里 IPP 配的是 `PreRouting`（路由决策之前），所以 EPP 是
IPP 的子节点，不是 agentgateway 的直接子节点——如果换成其他 phase，trace 树的形状会变。所有 span 最终都
经同一个 OTLP gRPC 端点 `otel-collector:4317` 导出，`otel-collector` 转发给 `jaeger`，因为它们共享同一个
`trace_id`，Jaeger 才能把跨 4 个进程的 span 拼成一棵树。

### 6.2 指标是怎么被抓到的

跟 trace 是完全独立的两条链路。EPP 和 vLLM 分别把 `/metrics`（Prometheus 文本格式）暴露在各自的端口上，
3.7 讲过的 `ServiceMonitor`/`PodMonitor` 告诉 Prometheus Operator "去抓这些目标"，Operator 生成实际的
scrape 配置。真实抓到的指标：

```console
$ curl -s ".../api/v1/query?query=llm_d_epp_request_total"
llm-d-epp     job=llm-d-epp     value=7   # precise-prefix 路径本次发了 7 个请求（1+6）
llm-d-pd-epp  job=llm-d-pd-epp  value=1   # P/D 路径发了 1 个请求
```

两个 EPP release 的指标带不同的 `job` label，这样 Grafana 里可以分开画（或者用 `sum by` 合并）。

---

## 7. 本次重跑踩到的 upstream breaking changes（附修复）

这是本次**全新从 `upstream/main` 构建镜像**的重跑中，真实遇到、真实修复过的两个问题，供后来者对照：

### 7.1 Router Helm chart 改名

`llm-d-router` 仓库把 Gateway 模式的 chart 从 `llm-d-router-gateway-dev` 改成了 **`llm-d-router-gateway`**
(去掉了 `-dev` 后缀，standalone 模式的 chart 同理从 `llm-d-router-standalone-dev` 变成
`llm-d-router-standalone`)。README 里旧的 `oci://ghcr.io/llm-d/charts/llm-d-router-gateway-dev` 现在会
`403 denied`（chart artifact 已经不存在，不是权限问题）：

```console
$ helm pull oci://ghcr.io/llm-d/charts/llm-d-router-gateway-dev --version v0
Error: ... response status code 403: denied: requested access to the resource is denied
$ helm pull oci://ghcr.io/llm-d/charts/llm-d-router-gateway --version v0     # 去掉 -dev 就好
Pulled: ghcr.io/llm-d/charts/llm-d-router-gateway:v0
```

**验证方法**：`llm-d` 仓库自己的 `guides/env.sh` 是最权威的来源——它把默认值定义为
`ROUTER_GATEWAY_CHART=oci://ghcr.io/llm-d/charts/llm-d-router-gateway`，跟仓库里几十个 `guides/*/README.md`
的用法交叉印证过。

### 7.2 `disagg-profile-handler` 插件参数格式改了

旧格式（README 原文、`llm-d` 仓库 `guides/pd-disaggregation/` 等大量 guide **目前仍然**在用，尚未同步）：

```yaml
- type: disagg-profile-handler
  parameters:
    deciderPluginName: always-disagg-pd-decider
```

`llm-d-router` 的 `main` 分支已经把这个插件的参数结构改成了嵌套格式（`pkg/epp/framework/plugins/
scheduling/profilehandler/disagg/disagg_profile_handler.go`），旧格式直接导致 EPP **`CrashLoopBackOff`**：

```text
"error":"failed to load the configuration - plugin instantiation failed: failed to build plugin
dependency graph: failed to parse plugin parameters for disagg-profile-handler (type:
disagg-profile-handler): failed to parse parameters of the disagg-profile-handler - json: unknown
field \"deciderPluginName\""
```

新格式（本次验证过，见第 5.1 节完整配置）：

```yaml
- type: disagg-profile-handler
  parameters:
    profiles:
      decode: decode        # 对应 schedulingProfiles 里 name=decode 的那个 profile
      prefill: prefill       # 对应 schedulingProfiles 里 name=prefill 的那个 profile
    deciders:
      prefill: always-disagg-pd-decider   # 用哪个插件来决定"要不要做 P/D 分离"
```

对照来源是 `llm-d-router` 仓库自带的 `deploy/config/sim-pd-epp-config.yaml`（专门给 sim 模式配的样例，跟
本 demo 场景一致）。已经把这个修复同步进了 `manifests/optional/pd/pd-router.values.yaml`。

> **给读者的启示**：`llm-d-router-gateway-dev` chart 只发布一个浮动的 `v0` tag，**没有任何 pinned
> release**（本次拉到的 digest 是 `sha256:c4a778aa...`）。这意味着"chart 版本"完全不能保证跟"你从
> `upstream/main` 编译的 EPP 镜像"匹配——本次这两个坑就是 chart 里的默认 `values.yaml`（或者你手写的
> `values.yaml`）落后于 `main` 分支代码导致的。**如果你也在跟着 `upstream/main` 走，EPP 一旦
> `CrashLoopBackOff`，第一反应应该是 `kubectl logs` 看 "unknown field" 这类 JSON 解析错误，去对应仓库的
> `deploy/config/*.yaml` 里找最新的参数格式，而不是怀疑自己的 YAML 缩进。**

### 7.3 其它变化（非 breaking，但值得记录）

- Grafana 的 llm-d Performance Dashboard 内部技术名从 `llm-d-performance-dashboard` 变成了
  `llm-d-performance-kv-cache`，展示标题不变（还是"llm-d Performance Dashboard"）。
- `kube-prometheus-stack` 从 88.1.3（operator v0.93.0）涨到了 **88.5.4**（operator v0.93.1）。
- EPP 的 trace span 命名从 `gateway.request`/`gateway.request_orchestration` 简化成了 `request`/
  `request_orchestration`（去掉了 `gateway.` 前缀——但 IPP 那一跳自己的 span 名仍然叫
  `gateway.request`，两者不要搞混）；`HTTP POST`（token-producer 调 vllm-render）改名成了更语义化的
  `tokenize_render /v1/chat/completions/render`；打分从一个笼统 span 拆成了 `scoring` + 每个
  `scorer.<name>` 子 span（第 4、5 节已详细展开）。
- HF 模型下载这次全程只花了 **39 秒**（不同上次记录的 ~22 分钟），可能是 CDN/带宽波动导致，不代表这个
  耗时已经稳定变快，仍建议按 README 3.8 的做法预先在宿主机拉取模型缓存。

---

## 8. 常见问题速查

| 现象 | 先看哪个 CR / 字段 | 本文对应章节 |
| --- | --- | --- |
| 发请求没反应/连不上 | `Gateway.status.conditions[Programmed]`、`.status.listeners[].attachedRoutes` | 3.2 |
| 请求 500，日志里有 `ext_proc ... connection reset` | 对应的 `AgentgatewayPolicy.status.ancestors[].conditions[Attached]`；再查该 `ext_proc` backend 的 `secure-serving` 是否和 agentgateway 的明文/TLS 期望一致 | 3.6 |
| 新副本一直不接流量 | `Pod` 的 label 是否匹配 `InferencePool.spec.selector.matchLabels`；`InferencePool.status.parents[].conditions[Accepted/ResolvedRefs]` | 3.4 |
| 两个池子流量分不开 | `HTTPRoute` 的 `matches`（尤其 header 匹配）有没有被更宽泛的规则抢先匹配 | 3.3 |
| 想看某次请求具体选中了谁、为什么 | Jaeger 里搜这次请求的 trace，看 `pick_endpoints` span 的 `llm_d.epp.picker.top_scores`/`top_endpoints` | 4 / 5 |
| EPP `CrashLoopBackOff`，日志里有 `unknown field` | 你的 `pluginsCustomConfig` 参数格式落后于镜像里编译进去的 EPP 代码；去对应 commit 的 `deploy/config/*.yaml` 找最新格式 | 7.2 |
| Prometheus 里查不到某个 `ServiceMonitor`/`PodMonitor` 抓到的指标 | 先确认 `.../api/v1/targets` 里这个目标是 `up`；如果 CR 刚创建就是空，八成是跟 Operator 重新生成配置撞了时间点，annotate 一下强制重新同步 | 3.7 |

---

*本文所有 YAML/日志/trace/metric 均为 2026-08-28 在本地 Kind 集群（`kindest/node:v1.35.0`）上真实运行
`README.md` 第 3 节全部步骤后抓取，供教学参考；具体数值（Pod 名、IP、span 耗时）每次重跑都会变化，但
CRD 的字段结构和组件间的调用关系是稳定的。*
