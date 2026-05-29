# llm-d 可观测性端到端演示（无 GPU 环境）

本指南介绍如何在**无 GPU** 的本地 Kind 集群上完成 llm-d 可观测性的完整搭建。使用 [llm-d-inference-sim](https://github.com/llm-d/llm-d-inference-sim) 模拟 vLLM prefill（预填充）和 decode（解码）Pod，暴露真实的 Prometheus 兼容指标，并由监控栈自动抓取。

> **英文版本：** [README.md](./README.md)

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│  Kind 集群                                                   │
│                                                             │
│  ┌─────────────────┐     ┌──────────────────────────────┐  │
│  │  llm-d-demo ns  │     │  llm-d-monitoring ns          │  │
│  │                 │     │                              │  │
│  │  [prefill Pod]  │◄────│  Prometheus（HTTPS/TLS）     │  │
│  │  [decode Pod 1] │◄────│  Grafana                     │  │
│  │  [decode Pod 2] │◄────│  Alertmanager                │  │
│  │  [流量生成器]    │     │                              │  │
│  │                 │     │  PodMonitor CRDs             │  │
│  │  PodMonitors    │────►│  （自动发现）                 │  │
│  └─────────────────┘     └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 组件说明

| 组件 | 命名空间 | 描述 |
|---|---|---|
| `llm-d-sim-prefill` | `llm-d-demo` | 模拟 prefill 推理 Pod（1 副本） |
| `llm-d-sim-decode` | `llm-d-demo` | 模拟 decode 推理 Pod（2 副本） |
| `llm-d-traffic-gen` | `llm-d-demo` | 持续流量生成器 |
| `PodMonitor` (×2) | `llm-d-demo` | Prometheus 抓取配置 |
| Prometheus（HTTPS） | `llm-d-monitoring` | 指标存储（预装） |
| Grafana | `llm-d-monitoring` | 可视化（预装） |

---

## 前提条件

- **Kind 集群**（已在 Kind v0.31.0、Kubernetes v1.35 上验证）
- **kubectl** 已配置并指向 Kind 集群
- **Helm** v3.10+
- **Docker**（或兼容的容器运行时）
- **Prometheus + Grafana** 已安装在 `llm-d-monitoring` 命名空间（参见 [prometheus-grafana-stack.md](../prometheus-grafana-stack.md)）

### 验证前提条件

```bash
kubectl cluster-info
kubectl get pods -n llm-d-monitoring
# 应该看到 prometheus 和 grafana Pod 处于 Running 状态
```

---

## 第 1 步：拉取并加载模拟器镜像

推理模拟器镜像需要加载到 Kind 集群节点中。在 Apple Silicon（arm64）主机上，需要拉取特定架构的镜像：

```bash
# 拉取 Apple Silicon Kind 节点所需的 arm64 manifest
docker pull ghcr.io/llm-d/llm-d-inference-sim:v0.8.0
ARM64_DIGEST=$(docker manifest inspect ghcr.io/llm-d/llm-d-inference-sim:v0.8.0 2>/dev/null | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  [print(m['digest']) for m in d.get('manifests',[]) \
  if m.get('platform',{}).get('architecture')=='arm64']")

docker pull ghcr.io/llm-d/llm-d-inference-sim@${ARM64_DIGEST}
docker tag ghcr.io/llm-d/llm-d-inference-sim@${ARM64_DIGEST} \
  ghcr.io/llm-d/llm-d-inference-sim:v0.8.0-arm64
```

> **注意：** 在 x86_64 主机上，直接使用 `v0.8.0` 标签，无需 `-arm64` 后缀，也不需要解析 manifest。

将镜像加载到所有 Kind 节点（将 `kueue-demo` 替换为您的 Kind 集群名称）：

```bash
kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.8.0-arm64 \
  --name kueue-demo
```

---

## 第 2 步：部署模拟器 Pod

在 `manifests/` 目录中依次应用清单文件：

```bash
cd docs/monitoring/no-gpu-demo/manifests

# 创建命名空间
kubectl apply -f 00-namespace.yaml

# 部署 prefill 模拟器（1 副本）
kubectl apply -f 01-prefill.yaml

# 部署 decode 模拟器（2 副本）
kubectl apply -f 02-decode.yaml

# 创建 PodMonitor（Prometheus 抓取配置）
kubectl apply -f 03-podmonitors.yaml

# 部署流量生成器
kubectl apply -f 04-traffic-generator.yaml
```

等待所有 Pod 就绪：

```bash
kubectl wait --for=condition=Ready pods --all -n llm-d-demo --timeout=120s
kubectl get pods -n llm-d-demo
```

预期输出：

```
NAME                                 READY   STATUS    RESTARTS   AGE
llm-d-sim-decode-76b759d585-2zkh8    1/1     Running   0          60s
llm-d-sim-decode-76b759d585-l6tbk    1/1     Running   0          60s
llm-d-sim-prefill-658677fd5c-vngsv   1/1     Running   0          60s
llm-d-traffic-gen-69c68bdfd4-x9x8j   1/1     Running   0          60s
```

---

## 第 3 步：验证指标端点

模拟器在 8000 端口的 `/metrics` 路径暴露 Prometheus 兼容指标：

```bash
# 端口转发到 prefill Pod
kubectl port-forward -n llm-d-demo deploy/llm-d-sim-prefill 18000:8000 &

# 查看可用指标列表
curl -s http://localhost:18000/metrics | grep '^# HELP'
```

预期指标（列举部分）：

```
# HELP vllm:cache_config_info LLMEngine 缓存配置信息
# HELP vllm:e2e_request_latency_seconds 端到端请求延迟直方图（秒）
# HELP vllm:generation_tokens_total 生成 Token 总数
# HELP vllm:inter_token_latency_seconds Token 间延迟直方图（秒）
# HELP vllm:kv_cache_usage_perc KV 缓存块使用率（0 到 1）
# HELP vllm:num_requests_running 当前运行中的请求数
# HELP vllm:num_requests_waiting 等待处理的请求数
# HELP vllm:prompt_tokens_total Prompt Token 总数
# HELP vllm:request_success_total 成功请求总数
# HELP vllm:time_to_first_token_seconds 首 Token 延迟（TTFT）直方图
```

完成检查后停止端口转发：

```bash
kill %1
```

---

## 第 4 步：验证 Prometheus 抓取

Prometheus（已启用 TLS）会自动发现 PodMonitor 并开始抓取：

```bash
# 端口转发 Prometheus（HTTPS）
kubectl port-forward -n llm-d-monitoring \
  svc/llmd-kube-prometheus-stack-prometheus 19090:9090 &

# 检查 targets（-k 参数忽略自签名证书验证）
curl -sk https://localhost:19090/api/v1/targets | python3 -c "
import sys, json
d = json.load(sys.stdin)
targets = d.get('data',{}).get('activeTargets',[])
llmd = [t for t in targets if 'llm-d-demo' in str(t)]
print(f'llm-d-demo 抓取目标数: {len(llmd)}')
for t in llmd:
    print(f'  {t[\"labels\"][\"job\"]} | {t[\"labels\"][\"pod\"]} | {t[\"health\"]}')
"
```

预期输出：

```
llm-d-demo 抓取目标数: 3
  llm-d-demo/llm-d-sim-decode | llm-d-sim-decode-xxx-yyy | up
  llm-d-demo/llm-d-sim-decode | llm-d-sim-decode-xxx-zzz | up
  llm-d-demo/llm-d-sim-prefill | llm-d-sim-prefill-xxx-yyy | up
```

---

## 第 5 步：加载 Grafana 仪表盘

```bash
# 从仓库根目录执行
cd docs/monitoring/scripts
bash load-llm-d-dashboards.sh llm-d-monitoring
```

该命令将以下仪表盘导入 Grafana：

| 仪表盘名称 | 描述 |
|---|---|
| `llm-d-vllm-overview` | vLLM 总览：请求速率、Token 吞吐量、延迟 |
| `llm-d-failure-saturation-dashboard` | 错误率、队列饱和度、抢占事件 |
| `llm-d-diagnostic-drilldown-dashboard` | 按 Pod 细粒度诊断指标 |
| `llm-performance-kv-cache` | KV 缓存使用率时间序列 |
| `pd-coordinator-metrics` | Prefill/Decode 分离（P/D 解聚）指标 |

---

## 第 6 步：访问 Grafana

```bash
kubectl port-forward -n llm-d-monitoring svc/llmd-grafana 3000:80 &
```

在浏览器中打开 [http://localhost:3000](http://localhost:3000)。

- **用户名：** `admin`
- **密码：** `admin`

进入 **Dashboards** → 选择任意 `llm-d` 仪表盘，即可看到来自 3 个模拟 Pod 的实时指标。

---

## 第 7 步：访问 Prometheus

```bash
kubectl port-forward -n llm-d-monitoring \
  svc/llmd-kube-prometheus-stack-prometheus 19090:9090 &
```

在浏览器中打开 [https://localhost:19090](https://localhost:19090)（接受自签名证书）。

---

## 测试用例

### 测试用例 1：Token 吞吐量

**目标：** 验证 Token 生成指标正常流入 Prometheus。

**PromQL 查询：**

```promql
sum by(pod) (rate(vllm:generation_tokens_total[5m]))
```

**预期结果：** 3 个 Pod 均有非零值；decode Pod 的吞吐量应高于 prefill Pod。

**验证命令：**

```bash
curl -sk "https://localhost:19090/api/v1/query?query=sum+by(pod)+(rate(vllm%3Ageneration_tokens_total%5B5m%5D))" | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
for r in d['data']['result']:
    print(f'{r[\"metric\"].get(\"pod\",\"\")}: {float(r[\"value\"][1]):.3f} tok/s')
"
```

---

### 测试用例 2：KV 缓存使用率

**目标：** 监控 prefill 和 decode Pod 的 KV 缓存使用情况。

**PromQL 查询：**

```promql
avg by(pod) (vllm:kv_cache_usage_perc)
```

**预期结果：** 所有 Pod 返回 0 到 1 之间的值；流量增加时，缓存使用率上升。

---

### 测试用例 3：请求延迟 P99

**目标：** 测量端到端请求延迟的第 99 百分位数。

**PromQL 查询：**

```promql
histogram_quantile(0.99, sum by(le, pod) (rate(vllm:e2e_request_latency_seconds_bucket[5m])))
```

**预期结果：** prefill Pod 的 P99 ≈ TTFT（仅预填充阶段）；decode Pod 显示完整的 E2E 延迟。

---

### 测试用例 4：Prefill 与 Decode 吞吐量对比

**目标：** 对比 prefill 和 decode Pod 的行为差异。

**PromQL 查询：**

```promql
# 仅 prefill Pod
sum by(pod) (rate(vllm:prompt_tokens_total[5m]))

# 仅 decode Pod
sum by(pod) (rate(vllm:generation_tokens_total[5m]))
```

---

### 测试用例 5：请求队列深度

**目标：** 检测请求排队情况（容量不足的预警信号）。

**PromQL 查询：**

```promql
sum by(pod) (vllm:num_requests_waiting)
```

**预期结果：** 正常情况下接近 0；在高负载下，decode Pod 可能先出现排队。

---

### 测试用例 6：首 Token 延迟（TTFT）

**目标：** 测量首 Token 延迟的分布。

**PromQL 查询：**

```promql
histogram_quantile(0.90, sum by(le, pod) (rate(vllm:time_to_first_token_seconds_bucket[5m])))
```

---

### 测试用例 7：错误率

**目标：** 验证错误请求的指标正常出现。流量生成器每隔 7 个请求注入一次错误请求。

**PromQL 查询：**

```promql
rate(vllm:request_success_total{finished_reason!="stop"}[5m])
```

**手动注入错误请求：**

```bash
kubectl port-forward -n llm-d-demo svc/llm-d-sim-decode-svc 18000:8000 &
curl -s -X POST http://localhost:18000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"nonexistent","messages":[{"role":"user","content":"test"}],"max_tokens":10}'
kill %1 2>/dev/null
```

---

### 测试用例 8：多 Pod 请求分发

**目标：** 验证负载在两个 decode 副本之间均匀分布。

**PromQL 查询：**

```promql
sum by(pod) (rate(vllm:request_success_total[5m]))
```

**预期结果：** 两个 decode Pod 的请求速率大致相等。

---

## 流量生成说明

`llm-d-traffic-gen` Deployment 持续运行，每隔 3 秒发送一次请求：

- **正常请求** → decode Pod（返回 HTTP 200）
- **Prefill 请求** → 每 3 个请求向 prefill Pod 发送 1 个（模拟 P/D 路由）
- **错误请求** → 每 7 个请求注入 1 个不存在的模型请求（生成错误指标）

查看流量生成日志：

```bash
kubectl logs -n llm-d-demo deploy/llm-d-traffic-gen -f
```

### 手动流量生成

也可以使用现有的流量生成脚本对模拟器进行测试：

```bash
kubectl port-forward -n llm-d-demo svc/llm-d-sim-decode-svc 18000:8000 &

ENDPOINT=http://localhost:18000/v1 \
MODEL_NAME=Qwen/Qwen2.5-0.5B-Instruct \
docs/monitoring/scripts/generate-traffic-basic.sh 5

kill %1 2>/dev/null
```

---

## 指标观测总结

完成演示后，您应该能观察到以下指标的正常变化：

| 指标名称 | 取值范围 | 说明 |
|---|---|---|
| `vllm:kv_cache_usage_perc` | 0–1 | 随流量增加而升高 |
| `vllm:generation_tokens_total` | 单调递增 | 计数器；使用 `rate()` 计算吞吐量 |
| `vllm:num_requests_running` | 0–N | 活跃请求期间出现峰值 |
| `vllm:num_requests_waiting` | 0–N | 高负载下增加 |
| `vllm:e2e_request_latency_seconds` | 直方图 | 通过 `histogram_quantile()` 获取 P50/P90/P99 |
| `vllm:time_to_first_token_seconds` | 直方图 | Prefill 阶段耗时 |
| `vllm:request_success_total` | 计数器 | 按 `finished_reason` 标签分类 |

---

## 清理

```bash
# 删除演示工作负载
kubectl delete namespace llm-d-demo

# 停止所有端口转发
pkill -f "port-forward" 2>/dev/null || true
```

如需同时卸载监控栈：

```bash
docs/monitoring/scripts/install-prometheus-grafana.sh --uninstall
```

---

## 故障排查

### Pod 卡在 `ImagePullBackOff`

镜像必须预先加载到 Kind 节点：

```bash
kind load docker-image ghcr.io/llm-d/llm-d-inference-sim:v0.8.0-arm64 \
  --name <您的集群名称>
```

### Prometheus 未抓取 Pod

检查 PodMonitor 配置：

```bash
kubectl get podmonitors -n llm-d-demo
# Prometheus 必须配置 podMonitorNamespaceSelector: {}（监听所有命名空间）
kubectl get prometheus -n llm-d-monitoring -o yaml | grep -A5 podMonitor
```

### 指标端点返回空内容

检查模拟器是否正常运行：

```bash
kubectl logs -n llm-d-demo deploy/llm-d-sim-prefill
kubectl port-forward -n llm-d-demo deploy/llm-d-sim-prefill 18000:8000 &
curl http://localhost:18000/health
```

### Grafana 显示 "No data"

等待仪表盘加载至少 1 分钟（Grafana sidecar 需要时间同步 ConfigMap）。检查仪表盘数据源是否设置为 **Prometheus**。
