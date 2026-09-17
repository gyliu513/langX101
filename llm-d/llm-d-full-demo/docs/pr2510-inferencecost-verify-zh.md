# 验证 llm-d PR #2510：在 Kind 环境上跑 OpenCost 推理成本 recipe

- PR: <https://github.com/llm-d/llm-d/pull/2510> — `Added recipe for inference cost`（分支 `simanadler:cost-v1-small`，commit `717daa2`）
- 配套的 OpenCost 改动（已合并）: <https://github.com/opencost/opencost/pull/3845>
- 验证日期：2026-09-16，环境是本目录 [README](../README.md) 搭的 Kind 集群，环境保留着，见 [§7](#7-环境保留怎么看)
- English version: [pr2510-inferencecost-verify.md](pr2510-inferencecost-verify.md)

## 0. 一句话结论

**OpenCost 那一侧能用；PR 里的安装脚本按现在这个样子不能用。** 完全按 README 的命令跑
（`./install-opencost.sh --image ghcr.io/opencost/opencost:develop-latest@sha256:e0c0… -y`），脚本把 OpenCost
装上以后**悄悄退出**，自带的 5 项检查一项都没跑，还留下一个孤儿 `kubectl port-forward`；而且它刚打印并"确认"的价格
**被 Helm chart 的占位价格悄悄替换掉了**（$1.25/core·h，$0.50/GiB·h），所以它算出来的每一个 `$` 数字都差 40～120 倍。
两个问题都是一到五行的修法；打上补丁后脚本能跑完、检查能跑、OpenCost 对真实流量给出的 `llm_*` 指标和 REST 结果是对的。

| 验证点 | 结果 |
| --- | --- |
| `helm install` OpenCost，`INFERENCE_COST_ENABLED=true` | 正常，pod `2/2 Running` |
| 安装脚本跑完并执行 llm-d 配置检查 | **没有** — 在 `set -e` 下于第 300 行 `(( i++ ))` 处静默退出 |
| 脚本打印的价格 = OpenCost 实际用的价格 | **不是** — chart 的 `customPricing.costModel` 默认值生效；`node_cpu_hourly_cost` = **1.25** 而不是 0.031611 |
| 两个 sim pod（各 2 core、5 GiB）的 `llm_total_hourly_cost` | 原样 **$11.52/h** → 修复后 **$0.159/h** |
| 打 30 个请求后的 `llm_cost_per_million_tokens`、`/inferenceCost/total`、`/inferenceCost/timeseries` | 正常：1440 prompt / 3600 generation token（正好 30×48 / 30×120），`allocation_method=compute_time` |
| `llm_*` 通过 ServiceMonitor 进 Prometheus | 正常（`release: llmd` 标签匹配） |
| `metrics-config` 标签白名单 ConfigMap | 没有任何效果（key 格式错 **且** collector 根本没加载）；真要生效反而会把 join 弄坏 |
| 脚本的模型名检查（#4） | 在这个 guide 上被跳过（"Could not compare"）—— 它按一个本 guide 没打的标签筛 pod，于是漏掉了真实存在的 `Qwen/Qwen2.5-0.5B-Instruct` ≠ `Qwen2.5-0.5B-Instruct` |
| README 里关于 `install-prometheus-grafana.sh` 和 `--served-model-name` 的说法 | 在这个分支上不成立（这些改动属于 #1926，本 PR 特意去掉了） |

完整补丁：[pr2510-inferencecost-fix.diff](pr2510-inferencecost-fix.diff)（端到端验证过，见 [§5](#5-修法已验证)）。

## 1. PR 加了什么

8 个文件，+1320/−2，没有代码，只有一个 recipe：

| 文件 | 作用 |
| --- | --- |
| `guides/recipes/observability/inferencecost/install-opencost.sh` | 783 行的安装/校验脚本：探测 Prometheus、交互确认价格、写 2 个 ConfigMap、`helm install opencost-charts/opencost`，然后 port-forward 到 Prometheus 跑 5 项检查 |
| `…/manifests/metrics-config.yaml` | ConfigMap `metrics-config`，OpenCost `kube_pod_labels` 的标签白名单 |
| `…/values/opencost-base.yaml`、`opencost-with-prometheus.yaml` | "参考" values —— **安装脚本并不读它们**（脚本自己内联生成 values） |
| `…/values/prometheus-test.yaml`、`test-guide.md` | 用独立 `prometheus` chart 在 OpenShift 上隔离测试的方案（这里没测，没有 OpenShift） |
| `…/README.md` | recipe 文档 |
| `docs/operations/observability/metrics.md` | 记录三个 `llm_*` gauge；引用了一个 Grafana dashboard `llm-d-inference-cost.json`，**PR 里并没有这个文件** |

OpenCost 那侧（`INFERENCE_COST_ENABLED`、`INFERENCE_MODEL_LABEL=llm-d.ai/model` 等）把 vLLM 的
`vllm:*_tokens_total{model_name}` 和按 `llm-d.ai/model` 标签分组的 pod 分摊成本 join 起来，输出
`llm_total_hourly_cost`、`llm_cost_per_million_tokens`、`llm_cache_savings_fraction`。

## 2. 环境和版本

| 组件 | 值 |
| --- | --- |
| Kind 集群 `llm-d`，单节点（arm64，14 CPU，23 GiB） | Kubernetes v1.35.0 |
| kube-prometheus-stack | chart 91.2.1，release `llmd`，ns `llm-d-monitoring`，KSM v2.20.0，**没有** `metricLabelsAllowlist` |
| llm-d | `llm-d-router-gateway` chart，agentgateway v1.1.0，2× `precise-prefix-vllm`（vLLM sim，CPU），EPP，`PodMonitor decode` 抓 vLLM |
| vLLM pod 标签 | `llm-d.ai/model=Qwen2.5-0.5B-Instruct`、`llm-d.ai/role=decode` —— **没有** `llm-d.ai/inference-serving`，全集群没有 `llm-d.ai/inference-shared` |
| vLLM 指标标签 | `model_name="Qwen/Qwen2.5-0.5B-Instruct"`（sim 的 `--model`，没有 `--served-model-name`） |
| OpenCost | chart `opencost-2.5.31`，镜像按 README 指定 `ghcr.io/opencost/opencost:develop-latest@sha256:e0c09b26…`，UI `opencost-ui:1.121.2` |
| 工具 | helm 3、kubectl、jq、`/opt/homebrew/bin/bash` 5.3（也顺便试了 `/bin/bash` 3.2） |

## 3. 我是怎么测的

### 3.1 完全按文档跑安装脚本

```
$ git clone -b cost-v1-small https://github.com/simanadler/llm-d.git
$ ./guides/recipes/observability/inferencecost/install-opencost.sh \
    --image "ghcr.io/opencost/opencost:develop-latest@sha256:e0c09b268d8243c45323fffec8ceea1434e9f7e982905af651b1adebfc7e3135" -y
ℹ️  Found Prometheus: http://llmd-kube-prometheus-stack-prometheus.llm-d-monitoring.svc.cluster.local:9090
  CPU ($/core-hour):             0.031611
  RAM ($/GiB-hour):              0.004237
  GPU ($/GPU-hour):              0.95  <-- most important for llm-d
ℹ️  Prices: CPU=$0.031611  RAM=$0.004237  GPU=$0.95  Storage=$0.00005479452
configmap/opencost-custom-pricing created
configmap/metrics-config created
ℹ️  OpenCost image: opencost/opencost:develop-latest@sha256:e0c0…        ← 日志里把 registry 丢了
NAME: opencost-llm-d-monitoring … STATUS: deployed
✅ OpenCost installed.
ℹ️    kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9092:80   ← kube-prometheus-stack 是 9090
ℹ️  Starting temporary port-forward to Prometheus for config checks...
Forwarding from 127.0.0.1:19090 -> 9090
Forwarding from [::1]:19090 -> 9090
                                     ← 到此为止，再没有任何输出
```

bash 进程已经没了，但它的子进程还活着：

```
$ ps -eo pid,ppid,command | grep -E "install-opencost|port-forward"
37777     1 kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 19090:9090
```

孤儿进程握着 stdout 不放，所以 `./install-opencost.sh … | tee log` 会永远挂住。根因在
`start_prometheus_portforward`（第 300 行）：

```bash
set -euo pipefail
…
  while [[ $i -lt 15 ]]; do
    if curl -sf --max-time 2 "http://localhost:${PROM_LOCAL_PORT}/api/v1/query?query=up" …; then return 0; fi
    sleep 1
    (( i++ ))      # i==0 → 表达式值 0 → 退出码 1 → set -e 把整个脚本干掉
  done
```

第一次 `curl` 必然失败（`&` 之后 0 ms port-forward 还没起来），所以每次运行都会以 `i=0` 走到这行：

```
$ bash -c 'set -euo pipefail; i=0; echo before; (( i++ )); echo after'
before
$ echo $?
1
```

于是 `wait_for_prometheus_scrape`、`check_llmd_config`、`stop_prometheus_portforward` 从来没执行过。
README 里"脚本会检查 1…5…"这段，在任何机器上都没真正跑过。

### 3.2 OpenCost 拿到这个集群后做了什么

pod `2/2`，环境变量正确（`INFERENCE_COST_ENABLED=true`、`INFERENCE_MODEL_LABEL=llm-d.ai/model`、
`PROMETHEUS_SERVER_ENDPOINT=http://llmd-kube-prometheus-stack-prometheus…:9090`）。日志：

```
INF Inference Cost enabled: true
INF Found configmap opencost-custom-pricing, watching...
INF ERROR UPDATING opencost-custom-pricing CONFIG: error updating provider config:
    error setting custom pricing field: no such field: Default.json in obj
INF InferenceCost: collector started (interval=2m0s)
INF InferenceCost: collected allocation costs for 1 model/namespace combinations
WRN InferenceCost: remapping metric key "Qwen/Qwen2.5-0.5B-Instruct:llm-d" → "Qwen2.5-0.5B-Instruct:llm-d"
    (model-name mismatch with allocation label)
```

这里已经能看到两件事：价格 ConfigMap 被拒了；OpenCost `develop` 对 `model_name` ≠ pod 标签的情况有一个
**兜底 remap**，这也是为什么本 guide 能跑通（见 §4.5）。

`/metrics` 有这几个 gauge，`/inferenceCost/total` 也能答，但安装后没有流量所以 token 字段都是 0 ——
而两个 0.5B sim pod 的小时费率高得离谱：

```
llm_total_hourly_cost{cost_basis="allocation",model_name="Qwen2.5-0.5B-Instruct",namespace="llm-d"} 11.522528767585754
```

### 3.3 $11.52/h 是哪来的

```
$ curl -s $PROM/api/v1/query --data-urlencode 'query=node_cpu_hourly_cost'  → 1.25
$ curl -s $PROM/api/v1/query --data-urlencode 'query=node_ram_hourly_cost'  → 0.5
```

这不是脚本打印的 GCP 价格，而是 **opencost Helm chart 的占位 `customPricing.costModel`**
（`CPU: 1.25`、`RAM: 0.50`、`storage: 0.25`）。2 个 pod ×（2 core × 1.25 + 6.52 GiB × 0.50）= 11.52 ✓

原因：chart 的 `customPricing.createConfigmap` 默认是 **true**，所以 `helm install` 会用 `costModel` 渲染一份自己的
`ConfigMap/opencost-custom-pricing`（扁平 key）。脚本事先创建了同名 ConfigMap，只有一个 `default.json` key，
**并且**打上了 `meta.helm.sh/release-name` 让 Helm "收养"它 —— 于是 Helm 把两者合并了：

```
$ kubectl get cm -n llm-d-monitoring opencost-custom-pricing -o jsonpath='{.data}' | jq
{
  "CPU": "1.25", "RAM": "0.5", "GPU": "0.95", "storage": "0.25", …   ← chart 默认值，OpenCost 读的是这些
  "default.json": "{ \"CPU\": \"0.031611\", \"RAM\": \"0.004237\", … }"   ← 用户确认的价格，被忽略，
                                                                              还是 "no such field: Default.json" 的来源
}
```

OpenCost 的 ConfigMap watcher 会把每个 data key 当作一个价格字段去 set，所以扁平的 chart 默认值胜出，
`default.json` 报错。净效果：**用户确认的价格从来没被用过**，每次安装都这样，而且没有任何错误暴露给用户。
在真 GPU 集群上这个问题没那么显眼（GPU 价格 0.95 两边碰巧一样），但 CPU/RAM 差 40× / 118×，`storage` 差 4500×。

另外观察到：把 ConfigMap 原地改对以后 OpenCost 打了 `CustomPricing Config Updated: modified`，但
`node_cpu_hourly_cost` 仍然是 1.25，直到 pod 重启才变 —— 节点价格是启动时算的。所以价格必须在**第一次**启动时就对；
脚本自己提示的"以后用 `--pricing-config` 再改"不重启也不会生效。

### 3.4 只跑校验路径（打上那一行补丁）

把 `(( i++ ))` 改成 `i=$(( i + 1 ))` 后，第二次运行（OpenCost 已存在）能走到检查：

```
  [PASS] kube-state-metrics exposes llm-d.ai/model in kube_pod_labels (2 pod(s))
⚠️    [WARN] No pods found with llm-d.ai/inference-shared=true
  [PASS] vLLM token metrics (vllm:prompt_tokens_total) present in Prometheus (2 series)
⚠️    Could not compare model names (no metrics or no pods found)
  [PASS] INFERENCE_COST_ENABLED=true in OpenCost pod
✅ All checks passed — llm-d is correctly configured for OpenCost inference cost tracking.
```

其中两行在这个集群上是错的：

- 检查 #1 "kube-state-metrics exposes …" 通过了，但这个 KSM **没有** `--metric-labels-allowlist`。那条 series 来自
  OpenCost **自己**输出的 `kube_pod_labels`，被 ServiceMonitor 抓进来了：
  ```
  kube_pod_labels{label_llm_d_ai_model="Qwen2.5-0.5B-Instruct", job="opencost-llm-d-monitoring", instance="10.244.0.30:9003"}
  ```
- 检查 #4 用 `-l llm-d.ai/inference-serving=true` 选 pod。本 guide（以及仓库里 `precise-prefix-cache-routing`、
  `inference-scheduling` 等）都不打这个标签，所以检查静默跳过 —— 然后总结说 "All checks passed"，而实际上
  `model_name` 是 `Qwen/Qwen2.5-0.5B-Instruct` ≠ `Qwen2.5-0.5B-Instruct`。

### 3.5 打流量，读成本指标

```
$ kubectl run cost-drive --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d --command -- sh -c \
  'for i in $(seq 1 30); do curl -sS -o /dev/null -w "req$i http=%{http_code}\n" -X POST http://10.96.108.250:80/v1/chat/completions \
   -H "Content-Type: application/json" -d "{\"model\":\"Qwen/Qwen2.5-0.5B-Instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"Explain prefill vs decode …\"}],\"max_tokens\":120}"; done'
req1 http=200 … req30 http=200
```

等一个采集周期（2 分钟）：

```
$ curl -s localhost:9003/metrics | grep ^llm_
llm_cost_per_million_tokens{allocation_method="compute_time",cost_basis="allocation",phase="prompt",     …} 454.30
llm_cost_per_million_tokens{allocation_method="compute_time",cost_basis="allocation",phase="generation", …} 19.35
llm_cost_per_million_tokens{allocation_method="",            cost_basis="allocation",phase="",           …} 148.43
llm_cache_savings_fraction{model_name="Qwen2.5-0.5B-Instruct",namespace="llm-d",workload_type="inference"} 0
llm_total_hourly_cost{cost_basis="allocation",model_name="Qwen2.5-0.5B-Instruct",namespace="llm-d",…}    11.52

$ curl -s "localhost:9003/inferenceCost/total?window=1h" | jq '.data.inferenceCosts'
"Qwen2.5-0.5B-Instruct:llm-d": {
  "properties": { "modelName": "Qwen2.5-0.5B-Instruct", "namespace": "llm-d", "controller": "precise-prefix-vllm", "container": "modelserver", … },
  "promptTokens": 1440, "generationTokens": 3600, "totalTokens": 5040,
  "costPerMillionTokens": 338.26, "inputCostPerMillionTokens": 1032.75, "outputCostPerMillionTokens": 60.46,
  "allocationMethod": "compute_time", "cacheSavingsFraction": 0
}
```

token 数精确（30 个请求 × 48 个 prompt token，30 × 120 `max_tokens`），prompt/generation 的拆分用的是 vLLM 的
`request_prefill/decode_time` 直方图（`compute_time`），join key 被 remap 到了 pod 标签名。所以**功能本身在 Kind sim
环境上是能用的**，只是 `$` 输入错了（这里仍是 $1.25/$0.50 占位价，修正后的数字见 §5）。

`/inferenceCost/timeseries?…&aggregate=model_name&accumulate=hour` 也能用；注意 OpenCost 安装之前的那个小时是按
*指标*名（`Qwen/Qwen2.5-0.5B-Instruct`，没有分摊数据可 remap）返回的，之后的小时按*标签*名返回 —— 画图时要留意这个
OpenCost 小怪癖。

## 4. 问题清单（按严重程度）

### 4.1 阻塞 —— 脚本静默退出，留下孤儿 port-forward（脚本第 300 行）

`set -euo pipefail` 下 `i=0` 时的 `(( i++ ))`。症状：没有检查、没有总结、每跑一次多一个
`kubectl port-forward … 19090:9090`、接管道就挂死。修法：`i=$(( i + 1 ))`（或 `(( ++i ))` / `i+=1`）。

### 4.2 阻塞 —— 确认过的价格被 chart 占位价悄悄替换

见 §3.3。修法：不要预创建 `opencost-custom-pricing`，把确认过的价格渲染进 chart 本来就认的 values：

```yaml
  customPricing:
    enabled: true
    configmapName: opencost-custom-pricing
    createConfigmap: true
    provider: custom
    costModel:
      description: "llm-d on-prem pricing (configured during install)"
      CPU: "0.031611"
      spotCPU: "0.006655"
      RAM: "0.004237"
      …
```

脚本手里已经有 `${OPENCOST_PRICING_JSON}`，在现有 heredoc 里加一行 `jq` 就行（见 diff）。`--pricing-config FILE`
不用改。另外文档要写明：以后改价格需要 `helm upgrade … && kubectl rollout restart deploy/opencost-<ns>`。

### 4.3 `metrics-config` 白名单：key 格式错，而且现在完全没生效

OpenCost 用白名单去匹配原始的 `pod.Labels` key
（[`podlabelmetrics.go`](https://github.com/opencost/opencost/blob/develop/pkg/metrics/podlabelmetrics.go)：
`for lname := range pod.Labels { if _, ok := kpmc.labelsWhitelist[lname]; !ok { delete(...) } }`），即应该写
`"llm-d.ai/model": true`，而不是 PR 里 Prometheus 化的 `"llm_d_ai_model": true`。如果白名单真生效了，**所有**标签都会被删掉
—— 包括 `llm-d.ai/model`，也就是整个 recipe 赖以 join 的 key。

但它并没有生效：collector 注册时按值拷贝了一份 `MetricsConfig`，ConfigMap watcher 是之后才把
`/tmp/custom-config/metrics.json` 写下来的；文件在容器的 `/tmp` 里，重启也没了。刚重启完观察到：

```
kube_pod_labels{label_app_kubernetes_io_part_of="llm-d",label_llm_d_ai_guide="precise-prefix-cache-routing",
                label_llm_d_ai_model="Qwen2.5-0.5B-Instruct",label_llm_d_ai_role="decode",label_pod_template_hash="5bdc47b459",…} 1
```

建议要么删掉 `manifests/metrics-config.yaml`（OpenCost 默认输出全部标签，今天 join 能成正是靠这个），要么把 key
改成原始标签名并注明是 best-effort。

### 4.4 模型名检查（#4）用错了 pod 选择器

`-l llm-d.ai/inference-serving=true` → 改成 `-l llm-d.ai/model`（这才是 recipe 关心的标签）。改完以后在这个集群上
能正确报出：

```
  [FAIL] model_name mismatch between vLLM metrics and pod labels: Qwen/Qwen2.5-0.5B-Instruct
❌   Fix: add --served-model-name=<short-name> to vllm serve args, matching the llm-d.ai/model pod label
```

### 4.5 README 里在这个分支上不成立的说法

- "`install-prometheus-grafana.sh` … 会自动配置 kube-state-metrics 暴露 `llm-d.ai/*` pod 标签" —— 没有
  （`grep metricLabelsAllowlist` 在 `inferencecost/` 之外一无所获；这个改动在 #1926 里，本 PR 去掉了）。另外文档说
  allowlist 是 "OpenCost 按模型 join 分摊成本所必需的"，但 OpenCost 自己会输出带全部标签的 `kube_pod_labels`，
  没改 KSM 也 join 成功了。要么把 allowlist 接回来，要么把措辞放软。
- "所有 llm-d guide 都设置了 `--served-model-name=<short-name>`" —— 没有（只有 `gpt-oss`、`tiered-prefix-cache`、
  `agentic-serving`、`multimodal` 设了，而且设的是*长*名）。OpenCost `develop` 靠 `remapping metric key …` 兜底容忍了这点，
  README 应该说明这个，而不是写 "必须完全一致"。
- 共享基础设施标签 `llm-d.ai/inference-shared` 仓库里没有任何 guide 打，所以"共享成本分摊"这条路径目前从任何 guide
  都走不到（检查 #2 只是 WARN，没问题，但值得注一下）。
- 验证命令用 `svc/opencost`；实际 Service 叫 `opencost-<namespace>`（脚本用 namespace 派生 release 名），比如
  `svc/opencost-llm-d-monitoring`。`metrics.md` 里同样的问题。
- "File layout" 说 `values/opencost-base.yaml` 是 "applied by installer" —— 脚本从不读 `values/`。`test-guide.md` 和
  `values/prometheus-test.yaml` 没列进 layout。
- `metrics.md` 往 dashboard 表里加了 `llm-d-inference-cost.json`；PR 里没有这个文件。

### 4.6 `wait_for_prometheus_scrape` 在 kube-prometheus-stack 上必然超时

它轮询 `count(kube_state_metrics_build_info)`。KSM v2 把这个指标放在 telemetry 端口（8081），kube-prometheus-stack
的 ServiceMonitor 不抓那个端口，所以永远出不来，每次安装白等 120 秒。应该轮询检查真正需要的东西，比如
`count(kube_pod_labels)` 或 `count(kube_node_info)`。

### 4.7 脚本里的小问题

- 空数组的 `"${image_sets[@]}"` 在 bash < 4.4（macOS `/bin/bash` 3.2）的 `set -u` 下是致命错误 → 不带 `--image` 时死于
  `image_sets[@]: unbound variable`。用 `${image_sets[@]+"${image_sets[@]}"}`。
- `check_llmd_config; local check_rc=$?` —— `set -e` 下检查失败会在 `stop_prometheus_portforward` 之前退出，又留孤儿
  port-forward。用 `check_rc=0; check_llmd_config || check_rc=$?`。
- 安装后提示 `svc/${prom_svc_name} 9092:80` —— kube-prometheus-stack 的 Prometheus Service 是 `9090`
  （80 是 `test-guide.md` 里独立 `prometheus` chart 的端口）。
- `OpenCost image:` 日志行少了 registry。
- `helm repo list | grep -q https://opencost.github.io/opencost-helm-chart` 然后 `helm repo add opencost-charts …` ——
  如果用户已经用别的别名加过这个 repo，安装仍然引用 `opencost-charts/opencost` 会失败；小问题。

## 5. 修法（已验证）

补丁：[pr2510-inferencecost-fix.diff](pr2510-inferencecost-fix.diff)（对 `install-opencost.sh` 8 个 hunk，对
`manifests/metrics-config.yaml` 1 个）。在同一集群上卸了重装：

```
$ ./install-opencost.fixed.sh -u                              # 干净卸载：release + 两个 ConfigMap
$ ./install-opencost.fixed.sh --image ghcr.io/opencost/opencost:develop-latest@sha256:e0c0… -y
…
ℹ️  OpenCost image: ghcr.io/opencost/opencost:develop-latest@sha256:e0c09b26…
✅ OpenCost installed.
ℹ️    kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9092:9090
✅ Port-forward to Prometheus established on localhost:19090
⚠️  Timed out waiting for Prometheus scrape — running checks anyway.      ← §4.6，diff 里没改这个
  [PASS] kube-state-metrics exposes llm-d.ai/model in kube_pod_labels (2 pod(s))
⚠️    [WARN] No pods found with llm-d.ai/inference-shared=true
  [PASS] vLLM token metrics (vllm:prompt_tokens_total) present in Prometheus (2 series)
  [FAIL] model_name mismatch between vLLM metrics and pod labels: Qwen/Qwen2.5-0.5B-Instruct
❌ 1 check(s) failed. Resolve the issues above and re-run.
$ pgrep -f 'port-forward.*19090' | wc -l
0
```

数字也变成了脚本打印的那些：

```
$ curl -s localhost:9003/metrics | grep -E '^node_(cpu|ram)_hourly_cost'
node_cpu_hourly_cost 0.031611
node_ram_hourly_cost 0.004237
$ curl -s localhost:9003/metrics | grep ^llm_total_hourly_cost
llm_total_hourly_cost{cost_basis="allocation",model_name="Qwen2.5-0.5B-Instruct",…} 0.15929625316052876
```

2 个 pod ×（2 core × 0.031611 + 5 GiB × 0.004237）= 0.169 ≈ 0.159 ✓（之前是 11.52）。`kubectl logs` 里没有
`no such field` 了。切换价格那个小时的窗口总额仍然混着旧占位价的样本 —— 正常，分摊查询读的是 Prometheus 里
`node_*_hourly_cost` 的历史。

## 6. 给 PR 的 review 意见（可直接贴）

1. **`install-opencost.sh:300`** — `(( i++ ))` 在 `i` 为 0 时返回 1，脚本又跑在 `set -euo pipefail` 下，所以
   `start_prometheus_portforward` 第一次重试就把整个脚本杀了（第一次 `curl` 时 port-forward 永远还没好）。我每次运行
   都停在这里，留下一个孤儿 `kubectl port-forward`，配置检查一项都没执行。`i=$(( i + 1 ))` 即可。
2. **价格被静默忽略。** chart 的 `customPricing.createConfigmap` 默认 `true`，Helm 会渲染自己的
   `opencost-custom-pricing`（扁平 key，`CPU: 1.25`、`RAM: 0.50`、`storage: 0.25`），而预创建的 ConfigMap 带着 Helm
   收养注解，于是被合并覆盖。OpenCost 随后用的是 chart 占位价，并报 `no such field: Default.json`。在我的集群上就是
   `node_cpu_hourly_cost 1.25`（打印的是 0.031611），两个 0.5B sim pod 的 `llm_total_hourly_cost` 是 $11.52/h。建议去掉
   预创建的 ConfigMap，改由 `opencost.customPricing.costModel` 传价格（现有 heredoc 加一行 `jq`）；验证后得到 0.031611 /
   $0.159/h。另外改价格要重启 pod 才会影响 `node_*_hourly_cost`。
3. **`manifests/metrics-config.yaml`** — 白名单 key 必须是原始标签名（`llm-d.ai/model`）而不是 `llm_d_ai_model`；
   OpenCost 是拿 `pod.Labels` 去匹配的。按现在的 key，一旦生效会把 `llm-d.ai/model` 删掉、弄坏 join。实际上它从不生效
   （collector 启动时快照配置；watcher 之后才写 `/tmp/custom-config/metrics.json`）—— 建议删掉这个文件，或改对 key 并注明
   best-effort。
4. **检查 #4** 按 `llm-d.ai/inference-serving=true` 筛 pod，大多数 guide（包括这个）不打这个标签，所以它打印
   "Could not compare"，总结却说 "All checks passed"，而 `model_name` 实际是 `Qwen/Qwen2.5-0.5B-Instruct`。改成
   `-l llm-d.ai/model` 就能抓到。
5. **README** — 这个分支上 `install-prometheus-grafana.sh` 并不设置 `metricLabelsAllowlist`，guide 也没设
   `--served-model-name=<short-name>`（两者都在 #1926 里）。OpenCost `develop` 会 remap 名字
   （`WRN InferenceCost: remapping metric key …`），所以能用，但文档应该这么写，而不是 "必须完全一致"。
   `svc/opencost` → `svc/opencost-<namespace>`；`values/*.yaml` 脚本没用到；`metrics.md` 列了一个 PR 里没有的 dashboard。
6. **`wait_for_prometheus_scrape`** 轮询 `kube_state_metrics_build_info`，kube-prometheus-stack 不抓它（KSM v2 telemetry
   端口）—— 必然 120 秒超时。改轮询 `kube_pod_labels`。
7. 小问题：不带 `--image` 时 `"${image_sets[@]}"` 在 bash 3.2（macOS `/bin/bash`）上挂；`check_llmd_config; local check_rc=$?`
   在 `set -e` 下失败时会泄漏 port-forward；Prometheus 提示写的 `9092:80` 但 kube-prometheus-stack 监听 9090。

## 7. 环境保留：怎么看

OpenCost 现在是用**修复版**脚本装的（release `opencost-llm-d-monitoring`，ns `llm-d-monitoring`）。

```bash
kubectl config use-context kind-llm-d
kubectl get pods -n llm-d-monitoring -l app.kubernetes.io/name=opencost           # 2/2 Running

# gauge + REST
kubectl port-forward -n llm-d-monitoring svc/opencost-llm-d-monitoring 9003:9003 &
curl -s localhost:9003/metrics | grep ^llm_
curl -s "localhost:9003/inferenceCost/total?window=1h" | jq .
curl -s "localhost:9003/inferenceCost/timeseries?window=6h&aggregate=model_name&accumulate=hour" | jq .

# UI
kubectl port-forward -n llm-d-monitoring svc/opencost-llm-d-monitoring 9090:9090 &   # http://localhost:9090

# 再打点流量（sim 约 6 s/请求），然后最多等 2 分钟采集器跑一轮
GWIP=$(kubectl get svc -n llm-d llm-d-inference-gateway -o jsonpath='{.spec.clusterIP}')
kubectl run drive --rm -i --restart=Never --image=curlimages/curl:8.7.1 -n llm-d --command -- sh -c \
  "for i in \$(seq 1 10); do curl -sS -o /dev/null -w 'req\$i %{http_code}\n' -X POST http://$GWIP/v1/chat/completions \
   -H 'Content-Type: application/json' -d '{\"model\":\"Qwen/Qwen2.5-0.5B-Instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":64}'; done"

# Prometheus 里（ServiceMonitor 抓进来的）
kubectl port-forward -n llm-d-monitoring svc/llmd-kube-prometheus-stack-prometheus 9091:9090 &
curl -s localhost:9091/api/v1/query --data-urlencode 'query=llm_total_hourly_cost' | jq .

# 卸载
./install-opencost.fixed.sh -u        # 或：helm uninstall opencost-llm-d-monitoring -n llm-d-monitoring
```

想复现那两个阻塞问题，在任意集群上跑 PR 分支**未打补丁**的脚本：它会停在 `Forwarding from [::1]:19090 -> 9090` 之后，
而 `kubectl get cm opencost-custom-pricing -o yaml` 会看到 `CPU: "1.25"` 和一个 `default.json` key 并排。

## 8. 本次新增的文件

| 文件 | 内容 |
| --- | --- |
| `docs/pr2510-inferencecost-verify.md` | 英文版 |
| `docs/pr2510-inferencecost-verify-zh.md` | 本文 |
| `docs/pr2510-inferencecost-fix.diff` | §5 卸了重装时用的补丁（`install-opencost.sh` + `manifests/metrics-config.yaml`） |
