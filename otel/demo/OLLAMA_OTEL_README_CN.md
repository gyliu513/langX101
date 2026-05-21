# Ollama + OpenTelemetry Demo（中文文档）

本文档说明如何配置环境、运行测试程序，以及如何通过 Jaeger 和 Prometheus 查看观测数据。

---

## 目录

- [架构说明](#架构说明)
- [前置条件](#前置条件)
- [环境配置](#环境配置)
- [运行测试程序](#运行测试程序)
- [查看结果](#查看结果)
- [两种方式对比](#两种方式对比)

---

## 架构说明

```
Python 程序
(ollama_otel.py / ollama_otel_auto.py)
        │
        │ OTLP gRPC (port 4317)
        ▼
OTel Collector (localhost:4317)
        ├── Traces ──► Jaeger (localhost:16686)
        ├── Traces ──► Zipkin (localhost:9411)
        └── Metrics ► Prometheus (localhost:9090)
                              └── Grafana (localhost:3000)

Ollama (localhost:11434)  ◄── OpenAI-compatible API 调用
```

**数据流：**

1. Python 程序通过 OpenAI-compatible API 向本地 Ollama 发送 chat completion 请求。
2. OTel SDK（或 `opentelemetry-instrument` CLI）自动/手动采集 trace 和 metrics，通过 OTLP gRPC 发送给 OTel Collector。
3. OTel Collector 将 trace 转发给 Jaeger 和 Zipkin，将 metrics 暴露给 Prometheus 抓取。

---

## 前置条件

| 组件 | 说明 |
|------|------|
| Python 3.12+ | 本地已安装 |
| Ollama | 本地运行，已拉取模型 |
| Docker & Docker Compose | 用于运行后端服务 |

确认 Ollama 已运行并有可用模型：

```bash
curl http://localhost:11434/api/tags
```

本示例使用 `llama3.2:3b`，如未安装请先拉取：

```bash
ollama pull llama3.2:3b
```

---

## 环境配置

### 1. 启动后端基础设施

```bash
cd otel/demo
docker compose up -d
```

启动后各服务端口如下：

| 服务 | 端口 | 说明 |
|------|------|------|
| OTel Collector | 4317 (gRPC), 4318 (HTTP) | 接收 OTLP 数据 |
| Jaeger | 16686 | Trace 可视化 UI |
| Zipkin | 9411 | Trace 可视化 UI（备用） |
| Prometheus | 9090 | Metrics 查询 |
| Grafana | 3000 | Metrics 可视化 Dashboard |

验证服务正常运行：

```bash
docker ps
# 确认所有容器均为 Up 状态
```

### 2. 创建 Python 虚拟环境

```bash
cd otel/demo
python3 -m venv .venv
```

### 3. 安装依赖

**手动插桩版本（`ollama_otel.py`）：**

```bash
.venv/bin/pip install \
  openai \
  opentelemetry-sdk \
  opentelemetry-exporter-otlp-proto-grpc \
  opentelemetry-api
```

**自动插桩版本（`ollama_otel_auto.py`），在手动版本基础上额外安装：**

```bash
.venv/bin/pip install \
  opentelemetry-instrumentation-openai \
  opentelemetry-distro
```

包说明：

- `opentelemetry-instrumentation-openai`：由 Traceloop 维护，自动拦截 OpenAI SDK 的所有 API 调用，按 GenAI 语义规范生成 span，无需修改业务代码。
- `opentelemetry-distro`：提供 `opentelemetry-instrument` CLI 工具，进程启动时自动注入 TracerProvider 和 MeterProvider，无需在代码中手写 SDK 初始化。

---

## 运行测试程序

### 方式一：手动插桩

**文件：`ollama_otel.py`**

OTel SDK 的初始化、span 创建、metrics 记录全部在代码内显式完成，无需任何环境变量，直接运行即可。

```bash
cd otel/demo
.venv/bin/python ollama_otel.py
```

代码中关键配置项：

```python
OTEL_ENDPOINT    = "http://localhost:4317"    # OTel Collector gRPC 地址
OLLAMA_BASE_URL  = "http://localhost:11434/v1" # Ollama OpenAI-compatible API
MODEL            = "llama3.2:3b"
SERVICE_NAME     = "ollama-chat-demo"          # Jaeger 中显示的服务名
```

手动采集的 metrics：

| Metric | 类型 | 说明 |
|--------|------|------|
| `ollama.chat.requests` | Counter | 请求总数 |
| `ollama.chat.latency_ms` | Histogram | 响应延迟（毫秒） |
| `ollama.chat.prompt_tokens` | Counter | 输入 token 数 |
| `ollama.chat.completion_tokens` | Counter | 输出 token 数 |

手动采集的 span attributes：

| Attribute | 说明 |
|-----------|------|
| `model` | 使用的模型名 |
| `latency_ms` | 本次请求耗时 |
| `llm.usage.prompt_tokens` | 输入 token 数 |
| `llm.usage.completion_tokens` | 输出 token 数 |
| `llm.usage.total_tokens` | 总 token 数 |

---

### 方式二：自动插桩

**文件：`ollama_otel_auto.py`**

Python 代码中没有任何 OTel 相关代码，由 `opentelemetry-instrument` CLI 在进程启动时自动注入所有插桩逻辑。

**第一步：设置环境变量**

```bash
export OTEL_SERVICE_NAME=ollama-chat-auto
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_TRACES_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=otlp
```

**第二步：通过 CLI 运行**

```bash
.venv/bin/opentelemetry-instrument python ollama_otel_auto.py
```

`opentelemetry-instrument` 启动时会自动发现并加载所有已安装的 instrumentation 包（包括 `opentelemetry-instrumentation-openai`），并根据环境变量配置 TracerProvider 和 MeterProvider。

自动采集的 span attributes（GenAI 语义规范）：

| Attribute | 说明 |
|-----------|------|
| `gen_ai.system` | AI 系统标识 |
| `gen_ai.request.model` | 请求的模型名 |
| `gen_ai.usage.prompt_tokens` | 输入 token 数 |
| `gen_ai.usage.completion_tokens` | 输出 token 数 |

---

## 查看结果

### Jaeger — 查看 Trace

打开浏览器：**http://localhost:16686**

1. 在 **Service** 下拉框中选择 `ollama-chat-demo`（手动插桩）或 `ollama-chat-auto`（自动插桩）。
2. 点击 **Find Traces** 查看 trace 列表。
3. 点击任意一条 trace 可查看 span 详情及所有 attributes。

### Prometheus — 查看 Metrics

打开浏览器：**http://localhost:9090**

手动插桩版本可查询以下指标：

```promql
# 请求总数
ollama_chat_requests_total

# P99 延迟分布
histogram_quantile(0.99, rate(ollama_chat_latency_ms_bucket[5m]))

# Token 消耗
ollama_chat_prompt_tokens_total
ollama_chat_completion_tokens_total
```

### Grafana — Dashboard

打开浏览器：**http://localhost:3000**  
默认账号密码：`admin` / `admin`

数据源已通过 Prometheus 预配置，可基于上述指标创建自定义 dashboard。

---

## 两种方式对比

| | 手动插桩 `ollama_otel.py` | 自动插桩 `ollama_otel_auto.py` |
|---|---|---|
| **运行命令** | `.venv/bin/python ollama_otel.py` | `.venv/bin/opentelemetry-instrument python ollama_otel_auto.py` |
| **配置方式** | 代码内硬编码 | 环境变量 |
| **OTel 代码量** | 多（显式初始化 + span 管理） | 零（无任何 OTel import） |
| **Span 命名** | `ollama.chat.completion`（自定义） | `openai.chat`（框架标准） |
| **Span 属性规范** | 自定义字段 | GenAI 语义规范 |
| **适用场景** | 需要自定义 span、精细控制 | 快速集成、零侵入 |
| **额外依赖** | 无 | `opentelemetry-instrumentation-openai`, `opentelemetry-distro` |
