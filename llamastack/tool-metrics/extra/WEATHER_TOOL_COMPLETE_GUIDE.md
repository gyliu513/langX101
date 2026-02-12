# Llama Stack 自定义天气工具完整指南

本文档详细记录了如何创建、注册和监控一个自定义的 llama-stack tool，包括遇到的问题和解决方案。

## 目录

1. [项目背景](#项目背景)
2. [创建自定义 Tool Provider](#创建自定义-tool-provider)
3. [注册 Provider 到 Registry](#注册-provider-到-registry)
4. [配置和启动 Server](#配置和启动-server)
5. [遇到的问题和解决方案](#遇到的问题和解决方案)
6. [Metrics 生成机制](#metrics-生成机制)
7. [完整 Workflow](#完整-workflow)
8. [验证和测试](#验证和测试)

---

## 项目背景

### 目标

创建一个自定义的天气工具，注册到 llama-stack server，让客户端可以：
- 通过 `llama-stack-client` CLI 查询到工具
- 通过 Python SDK 调用工具
- 自动记录工具调用的 OpenTelemetry metrics
- 在 Prometheus 和 Grafana 中可视化监控

### 需求

- 工具名称: `get_weather`
- 工具组: `weather`
- Provider ID: `weather-runtime`
- Provider 类型: `inline::weather`
- Metrics: 自动记录调用次数、延迟、成功率等

---

## 创建自定义 Tool Provider

### 文件结构

```
src/llama_stack/providers/inline/tool_runtime/weather/
├── __init__.py          # Provider 导出函数
├── config.py            # 配置类定义
└── weather.py           # 工具实现逻辑
```

### 1. 创建配置类 (config.py)

```python
# src/llama_stack/providers/inline/tool_runtime/weather/config.py

from typing import Any
from pydantic import BaseModel


class WeatherToolRuntimeConfig(BaseModel):
    """Configuration for the weather tool runtime provider."""

    @classmethod
    def sample_run_config(cls, __distro_dir__: str, **kwargs: Any) -> dict[str, Any]:
        return {}
```

**说明**：
- 使用 Pydantic BaseModel 定义配置
- `sample_run_config` 方法返回默认配置
- 可以添加配置参数（如 API key、默认单位等）

### 2. 实现 Provider 类 (weather.py)

```python
# src/llama_stack/providers/inline/tool_runtime/weather/weather.py

import random
from typing import Any

from llama_stack_api import (
    URL,
    ListToolDefsResponse,
    ToolDef,
    ToolGroup,
    ToolGroupsProtocolPrivate,
    ToolInvocationResult,
    ToolRuntime,
)

from .config import WeatherToolRuntimeConfig


class WeatherToolRuntimeImpl(ToolGroupsProtocolPrivate, ToolRuntime):
    """Weather tool runtime implementation."""

    def __init__(self, config: WeatherToolRuntimeConfig):
        self.config = config
        self.tool_name = "get_weather"
        self.toolgroup_id = "weather"

    async def initialize(self):
        """Initialize the weather tool provider."""
        pass

    async def shutdown(self):
        """Shutdown the weather tool provider."""
        pass

    async def register_toolgroup(self, toolgroup: ToolGroup) -> None:
        """Register a tool group (no-op for this provider)."""
        pass

    async def unregister_toolgroup(self, toolgroup_id: str) -> None:
        """Unregister a tool group (no-op for this provider)."""
        pass

    async def list_runtime_tools(
        self,
        tool_group_id: str | None = None,
        mcp_endpoint: URL | None = None,
        authorization: str | None = None,
    ) -> ListToolDefsResponse:
        """List available tools in this provider."""
        return ListToolDefsResponse(
            data=[
                ToolDef(
                    toolgroup_id=self.toolgroup_id,
                    name=self.tool_name,
                    description="Get current weather information for a city",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "city": {
                                "type": "string",
                                "description": "The city name to get weather for",
                            },
                            "units": {
                                "type": "string",
                                "enum": ["celsius", "fahrenheit"],
                                "description": "Temperature unit. Defaults to celsius.",
                            },
                        },
                        "required": ["city"],
                    },
                )
            ]
        )

    async def invoke_tool(
        self, tool_name: str, kwargs: dict[str, Any], authorization: str | None = None
    ) -> ToolInvocationResult:
        """Invoke the weather tool."""
        if tool_name != self.tool_name:
            return ToolInvocationResult(
                error_message=f"Unknown tool: {tool_name}",
                error_code=404,
            )

        city = kwargs.get("city")
        if not city:
            return ToolInvocationResult(
                error_message="Missing required parameter: city",
                error_code=400,
            )

        units = kwargs.get("units", "celsius")

        # Generate mock weather data
        weather_data = self._get_mock_weather(city, units)

        return ToolInvocationResult(
            content=weather_data,
            metadata={"provider": "weather-tool-inline"},
        )

    def _get_mock_weather(self, city: str, units: str) -> str:
        """Generate mock weather data."""
        conditions = ["Sunny", "Cloudy", "Rainy", "Snowy"]
        condition = random.choice(conditions)

        if units == "celsius":
            temp = round(random.uniform(-5, 35), 1)
            temp_unit = "°C"
        else:
            temp = round(random.uniform(23, 95), 1)
            temp_unit = "°F"

        humidity = random.randint(30, 95)
        wind_speed = round(random.uniform(0, 30), 1)

        return f"""Weather in {city}:
Temperature: {temp}{temp_unit}
Condition: {condition}
Humidity: {humidity}%
Wind Speed: {wind_speed} km/h"""
```

**关键点**：

1. **继承必需的协议**：
   - `ToolRuntime`: 工具运行时协议
   - `ToolGroupsProtocolPrivate`: 工具组管理协议

2. **实现必需方法**：
   - `initialize()` / `shutdown()`: 生命周期管理
   - `list_runtime_tools()`: 列出可用工具及其 schema
   - `invoke_tool()`: 执行工具逻辑
   - `register_toolgroup()` / `unregister_toolgroup()`: 工具组管理

3. **定义工具 Schema**：
   - `input_schema`: JSON Schema 定义输入参数
   - `output_schema`: (可选) 定义输出格式
   - `description`: 工具描述

4. **错误处理**：
   - 参数验证
   - 返回 `ToolInvocationResult` 带 `error_message` 和 `error_code`

### 3. 创建 Provider 导出 (__init__.py)

```python
# src/llama_stack/providers/inline/tool_runtime/weather/__init__.py

from typing import Any
from llama_stack_api import Api
from .config import WeatherToolRuntimeConfig


async def get_provider_impl(config: WeatherToolRuntimeConfig, deps: dict[Api, Any]):
    """Factory function to create the provider implementation."""
    from .weather import WeatherToolRuntimeImpl

    impl = WeatherToolRuntimeImpl(config)
    await impl.initialize()
    return impl
```

**说明**：
- `get_provider_impl` 是标准的 provider 工厂函数
- 接收配置和依赖
- 返回初始化后的 provider 实例

---

## 注册 Provider 到 Registry

### 修改 Tool Runtime Registry

```python
# src/llama_stack/providers/registry/tool_runtime.py

from llama_stack_api import Api, InlineProviderSpec


def available_providers() -> list[ProviderSpec]:
    return [
        # ... 其他 providers ...

        # 添加 Weather Provider
        InlineProviderSpec(
            api=Api.tool_runtime,
            provider_type="inline::weather",
            pip_packages=[],  # 无额外依赖
            module="llama_stack.providers.inline.tool_runtime.weather",
            config_class="llama_stack.providers.inline.tool_runtime.weather.config.WeatherToolRuntimeConfig",
            api_dependencies=[],  # 无依赖其他 API
            description="Weather tool for getting current weather information (mock).",
        ),
    ]
```

**关键字段**：

- `api`: API 类型 (`Api.tool_runtime`)
- `provider_type`: Provider 唯一标识符 (`inline::weather`)
- `module`: Python 模块路径
- `config_class`: 配置类的完整路径
- `pip_packages`: 需要的 Python 包（可选）
- `api_dependencies`: 依赖的其他 API（可选）

### 重新安装 llama-stack

```bash
pip install -e .
```

**作用**：
- 重新安装确保 registry 的修改被加载
- Provider 代码变更会被识别

---

## 配置和启动 Server

### 1. 创建配置文件

```yaml
# weather-stack-config.yaml

version: 2

# 使用的基础分发包
image_name: llamastack/distribution-together

providers:
  # 配置 Tool Runtime Provider
  tool_runtime:
    - provider_id: weather-runtime      # Provider 实例 ID
      provider_type: inline::weather    # 注册的 provider 类型
      config: {}                        # Provider 配置（空表示使用默认）

# 注册 Tool Groups
tool_groups:
  - toolgroup_id: weather               # Tool group ID
    provider_id: weather-runtime        # 关联的 provider
```

### 2. 启动 Server（带 Metrics）

**重要**：需要设置 OpenTelemetry 环境变量才能导出 metrics！

```bash
# 设置 OTEL 环境变量
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="llama-stack-server"
export OTEL_METRIC_EXPORT_INTERVAL="5000"  # 5秒导出一次

# 启动 server
llama stack run weather-stack-config.yaml --port 8321
```

**或使用自动化脚本**：

```bash
./start_weather_with_metrics.sh
```

### 3. 注册 Tool Group

**问题**：配置文件中的 `tool_groups` 有时不会自动注册。

**解决**：通过 API 手动注册一次：

```bash
curl -X POST http://localhost:8321/v1/toolgroups \
  -H "Content-Type: application/json" \
  -d '{
    "toolgroup_id": "weather",
    "provider_id": "weather-runtime"
  }'
```

---

## 遇到的问题和解决方案

### 问题 1: Tool Group 不显示

**现象**：
```bash
llama-stack-client toolgroups list
# 输出: 空表格，没有数据
```

**原因**：
- 配置文件中的 `tool_groups` 部分在某些情况下不会自动注册
- 可能是 server 启动顺序或配置加载的问题

**解决方案**：

手动通过 API 注册：

```bash
curl -X POST http://localhost:8321/v1/toolgroups \
  -H "Content-Type: application/json" \
  -d '{
    "toolgroup_id": "weather",
    "provider_id": "weather-runtime"
  }'
```

**验证**：

```bash
llama-stack-client toolgroups list
# 应该显示:
# ┃ identifier ┃ provider_id     ┃
# ┃ weather    ┃ weather-runtime ┃
```

### 问题 2: Python Client API 不匹配

**现象**：

```python
client = LlamaStackClient(base_url="http://localhost:8321")
result = client.tool_groups.list()  # AttributeError: no attribute 'tool_groups'
```

**原因**：
- Python SDK 的 API 命名与 CLI 不同
- 应该使用 `toolgroups` 而不是 `tool_groups`

**解决方案**：

```python
# ✅ 正确的 API
result = client.toolgroups.list()  # 注意是 toolgroups（全小写）

# 处理返回值（可能是 list 或带 .data 属性的对象）
tool_groups = result.data if hasattr(result, 'data') else result
```

### 问题 3: Prometheus 没有 Metrics

**现象**：

运行 `python test_weather_client.py` 后，Prometheus 查询返回空结果：

```bash
curl 'http://localhost:9090/api/v1/query?query=llama_stack_tool_runtime_invocations_total'
# {"data": {"result": []}}
```

**原因**：

Server 启动时**没有设置 OpenTelemetry 环境变量**，导致：

1. `src/llama_stack/telemetry/__init__.py` 中的 `setup_telemetry()` 检测到 `OTEL_EXPORTER_OTLP_ENDPOINT` 未设置
2. 跳过了 OTLP exporter 配置
3. 虽然代码中有 metrics 插桩，但 metrics 没有导出

**代码逻辑**：

```python
# src/llama_stack/telemetry/__init__.py

def setup_telemetry():
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

    if not otlp_endpoint:
        logger.debug("OTEL_EXPORTER_OTLP_ENDPOINT not set, metrics will not be exported")
        return  # ⚠️ 这里就返回了，不会配置 exporter

    # ... 配置 OTLP exporter ...
```

**解决方案**：

启动 server 前设置环境变量：

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="llama-stack-server"
export OTEL_METRIC_EXPORT_INTERVAL="5000"

llama stack run weather-stack-config.yaml --port 8321
```

**验证 Telemetry 已初始化**：

检查 server 日志：

```bash
grep -i "OpenTelemetry metrics exporter configured" /tmp/llama-stack-weather-metrics.log
# 应该输出: INFO ... OpenTelemetry metrics exporter configured: http://localhost:4318
```

### 问题 4: OTLP Collector 不健康

**现象**：

```bash
docker-compose ps
# otel-collector 显示 unhealthy
```

**原因**：

之前的 `otel-collector-config.yaml` 配置错误，同时使用了 `loglevel` 和 `verbosity`。

**解决方案**：

```yaml
# otel-collector-config.yaml

exporters:
  logging:
    # loglevel: info  ❌ 删除这行
    verbosity: detailed  # ✅ 只保留 verbosity
```

---

## Metrics 生成机制

### Metrics 流程图

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Client 调用工具                                          │
│    client.tool_runtime.invoke_tool(                         │
│        tool_name="get_weather",                             │
│        kwargs={"city": "Tokyo"}                             │
│    )                                                        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. ToolRuntimeRouter.invoke_tool (已插桩!)                  │
│    - src/llama_stack/core/routers/tool_runtime.py          │
│                                                             │
│    async def invoke_tool(self, tool_name, kwargs, ...):    │
│        start_time = time.perf_counter()  # 开始计时        │
│                                                             │
│        try:                                                 │
│            # 调用实际的 provider                            │
│            result = await provider.invoke_tool(...)        │
│                                                             │
│            # 记录成功 metrics                               │
│            duration = time.perf_counter() - start_time     │
│            tool_invocations_total.add(1, {                 │
│                "tool_name": "get_weather",                 │
│                "tool_group": "weather",                    │
│                "provider": "weather-runtime",              │
│                "status": "success"                         │
│            })                                              │
│            tool_duration.record(duration, {...})           │
│                                                             │
│        except Exception:                                    │
│            # 记录失败 metrics                               │
│            tool_invocations_total.add(1, {                 │
│                "status": "error"                           │
│            })                                              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. WeatherToolRuntimeImpl.invoke_tool                       │
│    - 执行实际的天气查询逻辑                                 │
│    - 返回 ToolInvocationResult                              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. OpenTelemetry MeterProvider                              │
│    - 收集 metrics 数据                                      │
│    - 每 5 秒 (OTEL_METRIC_EXPORT_INTERVAL) 导出一次        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. OTLP Exporter                                            │
│    - 通过 HTTP 发送到 http://localhost:4318/v1/metrics     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. OTLP Collector (Docker)                                  │
│    - 接收 OTLP 格式的 metrics                               │
│    - 暴露 Prometheus 格式在 port 8889                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. Prometheus                                               │
│    - 每 15 秒抓取 otel-collector:8889/metrics              │
│    - 存储时间序列数据                                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 8. Grafana Dashboard                                        │
│    - 查询 Prometheus                                        │
│    - 可视化 metrics                                         │
└─────────────────────────────────────────────────────────────┘
```

### Metrics 插桩代码

**位置**: `src/llama_stack/core/routers/tool_runtime.py`

```python
from llama_stack.telemetry.metrics import (
    tool_invocations_total,
    tool_duration,
    create_tool_metric_attributes,
)

class ToolRuntimeRouter:
    async def invoke_tool(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        authorization: str | None = None
    ) -> Any:
        start_time = time.perf_counter()
        metric_attrs = None

        try:
            # 获取 provider 和 tool group 信息
            provider = await self.routing_table.get_provider_impl(tool_name)
            tool_group = self.routing_table.tool_to_toolgroup.get(tool_name)

            # 创建 metric 属性
            metric_attrs = create_tool_metric_attributes(
                tool_group=tool_group,
                tool_name=tool_name,
                provider=getattr(provider, "__provider_id__", None),
            )

            # 调用实际的 provider
            result = await provider.invoke_tool(
                tool_name=tool_name,
                kwargs=kwargs,
                authorization=authorization,
            )

            # 记录成功 metrics
            duration = time.perf_counter() - start_time
            success_attrs = {**metric_attrs, "status": "success"}

            tool_invocations_total.add(1, success_attrs)  # Counter +1
            tool_duration.record(duration, metric_attrs)  # Histogram 记录延迟

            return result

        except Exception as e:
            # 记录失败 metrics
            duration = time.perf_counter() - start_time
            error_attrs = {**metric_attrs, "status": "error"} if metric_attrs else {
                "tool_name": tool_name,
                "status": "error",
            }

            tool_invocations_total.add(1, error_attrs)
            tool_duration.record(duration, error_attrs)

            raise
```

### Metrics 定义

**位置**: `src/llama_stack/telemetry/metrics.py`

```python
from opentelemetry import metrics
from llama_stack.telemetry.constants import (
    TOOL_INVOCATIONS_TOTAL,
    TOOL_DURATION,
)

# 获取 Meter
meter = metrics.get_meter("llama_stack.tool_runtime", version="1.0.0")

# 定义 Counter: 调用总数
tool_invocations_total = meter.create_counter(
    name=TOOL_INVOCATIONS_TOTAL,  # "llama_stack.tool_runtime.invocations_total"
    description="Total number of tool invocations processed by the runtime",
    unit="1",
)

# 定义 Histogram: 调用延迟
tool_duration = meter.create_histogram(
    name=TOOL_DURATION,  # "llama_stack.tool_runtime.duration_seconds"
    description="Duration of tool invocations from start to completion",
    unit="s",
)
```

### Metric 属性 (Labels)

每个 metric 都会带上这些标签用于过滤和聚合：

```python
{
    "tool_name": "get_weather",        # 工具名称
    "tool_group": "weather",           # 工具组
    "provider": "weather-runtime",     # Provider ID
    "status": "success" | "error",     # 调用状态
    "service_name": "llama-stack-server",  # 服务名
}
```

### 生成的 Metrics

在 Prometheus 中会看到：

```promql
# Counter: 调用次数
llama_stack_tool_runtime_invocations_total{
    tool_name="get_weather",
    tool_group="weather",
    provider="weather-runtime",
    status="success"
} = 3

# Histogram: 延迟分布
llama_stack_tool_runtime_duration_seconds_bucket{
    tool_name="get_weather",
    le="0.005"  # <= 5ms
} = 0

llama_stack_tool_runtime_duration_seconds_bucket{
    tool_name="get_weather",
    le="0.01"   # <= 10ms
} = 3  # 所有3次调用都在 10ms 内

llama_stack_tool_runtime_duration_seconds_sum{
    tool_name="get_weather"
} = 0.025  # 总耗时

llama_stack_tool_runtime_duration_seconds_count{
    tool_name="get_weather"
} = 3  # 总次数
```

---

## 完整 Workflow

### 开发 Workflow

```
1. 创建 Provider 文件
   ├── config.py         (配置类)
   ├── weather.py        (实现逻辑)
   └── __init__.py       (导出函数)

2. 注册到 Registry
   └── 修改 src/llama_stack/providers/registry/tool_runtime.py

3. 重新安装
   └── pip install -e .

4. 创建配置文件
   └── weather-stack-config.yaml

5. 启动 Server (带 OTEL 环境变量)
   └── 设置 OTEL_* 环境变量
   └── llama stack run weather-stack-config.yaml

6. 注册 Tool Group
   └── curl POST /v1/toolgroups

7. 测试调用
   └── python test_weather_client.py

8. 查看 Metrics
   └── Prometheus: http://localhost:9090
   └── Grafana: http://localhost:3000
```

### 运行时 Workflow

```
┌─────────────────────────────────────────────────────────────┐
│ 用户操作                                                    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 1. 启动监控栈                                               │
│    cd examples/metrics-demo                                 │
│    docker-compose up -d                                     │
│                                                             │
│    启动服务:                                                │
│    ├── OTLP Collector (port 4318, 8889)                    │
│    ├── Prometheus (port 9090)                              │
│    └── Grafana (port 3000)                                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. 配置环境变量                                             │
│    export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318" │
│    export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"      │
│    export OTEL_SERVICE_NAME="llama-stack-server"           │
│    export OTEL_METRIC_EXPORT_INTERVAL="5000"               │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. 启动 Llama Stack Server                                  │
│    llama stack run weather-stack-config.yaml --port 8321   │
│                                                             │
│    Server 初始化:                                           │
│    ├── 加载配置文件                                         │
│    ├── 注册 providers (inline::weather)                    │
│    ├── 初始化 telemetry (setup_telemetry())                │
│    │   └── 配置 OTLP exporter → localhost:4318            │
│    └── 启动 HTTP server (port 8321)                        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. 注册 Tool Group                                          │
│    curl POST http://localhost:8321/v1/toolgroups           │
│                                                             │
│    注册信息:                                                │
│    ├── toolgroup_id: "weather"                             │
│    └── provider_id: "weather-runtime"                      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Client 调用工具                                          │
│    client = LlamaStackClient("http://localhost:8321")      │
│    result = client.tool_runtime.invoke_tool(               │
│        tool_name="get_weather",                            │
│        kwargs={"city": "Tokyo", "units": "celsius"}        │
│    )                                                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. Server 处理请求                                          │
│                                                             │
│    HTTP Request                                             │
│    POST /v1/tool-runtime/invoke                            │
│    Body: {                                                 │
│        "tool_name": "get_weather",                         │
│        "kwargs": {"city": "Tokyo"}                         │
│    }                                                       │
│         ↓                                                  │
│    ToolRuntimeRouter.invoke_tool()                         │
│         ├── start_time = perf_counter()                   │
│         ├── 查找 provider (weather-runtime)                │
│         ├── 查找 tool_group (weather)                      │
│         ├── 创建 metric_attrs                              │
│         │   {                                              │
│         │       "tool_name": "get_weather",               │
│         │       "tool_group": "weather",                  │
│         │       "provider": "weather-runtime"             │
│         │   }                                              │
│         ↓                                                  │
│    WeatherToolRuntimeImpl.invoke_tool()                    │
│         ├── 验证参数 (city, units)                         │
│         ├── 生成 mock 天气数据                             │
│         └── 返回 ToolInvocationResult                      │
│         ↓                                                  │
│    返回到 ToolRuntimeRouter                                 │
│         ├── duration = perf_counter() - start_time        │
│         ├── tool_invocations_total.add(1, {               │
│         │       ...metric_attrs,                          │
│         │       "status": "success"                       │
│         │   })                                            │
│         └── tool_duration.record(duration, metric_attrs)  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. Metrics 导出 (每 5 秒一次)                               │
│                                                             │
│    OpenTelemetry MeterProvider                              │
│         ↓                                                  │
│    收集所有 metrics 数据                                    │
│         ↓                                                  │
│    OTLPMetricExporter                                       │
│         ↓                                                  │
│    HTTP POST http://localhost:4318/v1/metrics              │
│    (OTLP Protocol Buffer 格式)                             │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 8. OTLP Collector 接收和转换                                │
│                                                             │
│    OTLP Receiver (port 4318)                                │
│         ↓                                                  │
│    解析 OTLP 格式                                           │
│         ↓                                                  │
│    Prometheus Exporter                                      │
│         ↓                                                  │
│    暴露 Prometheus 格式 (port 8889/metrics)                │
│                                                             │
│    格式示例:                                                │
│    llama_stack_tool_runtime_invocations_total{             │
│        tool_name="get_weather",                            │
│        status="success"                                    │
│    } 1                                                     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 9. Prometheus 抓取 (每 15 秒)                               │
│                                                             │
│    Scrape Job: otel-collector                              │
│    Target: otel-collector:8889                             │
│         ↓                                                  │
│    GET http://otel-collector:8889/metrics                  │
│         ↓                                                  │
│    解析 Prometheus 文本格式                                 │
│         ↓                                                  │
│    存储时间序列数据到 TSDB                                  │
│         ↓                                                  │
│    可通过 PromQL 查询:                                      │
│    http://localhost:9090/api/v1/query?query=...           │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 10. Grafana 可视化                                          │
│                                                             │
│    用户访问: http://localhost:3000                         │
│         ↓                                                  │
│    打开 Dashboard: "Tool Runtime Metrics"                  │
│         ↓                                                  │
│    Panel 查询 Prometheus:                                  │
│    ├── Tool Invocation Rate                                │
│    │   rate(llama_stack_tool_runtime_invocations_total[1m])│
│    ├── Success vs Error Rate                               │
│    │   sum by(status)(rate(...[5m]))                       │
│    ├── P95 Latency                                         │
│    │   histogram_quantile(0.95, rate(..._bucket[1m]))      │
│    └── Total Invocations                                   │
│        sum(llama_stack_tool_runtime_invocations_total)     │
│         ↓                                                  │
│    渲染图表和面板                                           │
│         ↓                                                  │
│    用户看到实时 metrics! 📊                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 验证和测试

### 1. 验证 Provider 已注册

```bash
python -c "
from llama_stack.providers.registry.tool_runtime import available_providers
providers = available_providers()
for p in providers:
    if 'weather' in str(p.provider_type):
        print(f'✅ Found: {p.provider_type}')
        print(f'   Module: {p.module}')
"
```

**预期输出**：
```
✅ Found: inline::weather
   Module: llama_stack.providers.inline.tool_runtime.weather
```

### 2. 验证 Server 启动

```bash
# 检查健康状态
curl http://localhost:8321/v1/health

# 检查 telemetry 初始化
grep "OpenTelemetry metrics exporter configured" /tmp/llama-stack-weather-metrics.log
```

**预期输出**：
```
INFO ... OpenTelemetry metrics exporter configured: http://localhost:4318 (interval: 5.0s)
```

### 3. 验证 Tool Group 注册

```bash
llama-stack-client toolgroups list
```

**预期输出**：
```
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ identifier ┃ provider_id     ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ weather    │ weather-runtime │
└───────────┴─────────────────┘
```

### 4. 测试工具调用

```python
# test_weather_client.py
from llama_stack_client import LlamaStackClient

client = LlamaStackClient(base_url="http://localhost:8321")

result = client.tool_runtime.invoke_tool(
    tool_name="get_weather",
    kwargs={"city": "Tokyo", "units": "celsius"}
)

print(result.content)
```

**预期输出**：
```
Weather in Tokyo:
Temperature: 22.1°C
Condition: Sunny
Humidity: 65%
Wind Speed: 12.3 km/h
```

### 5. 验证 Metrics 生成

```bash
# 等待几秒让 metrics 导出
sleep 10

# 查询 OTLP Collector
curl -s http://localhost:8889/metrics | grep llama_stack_tool_runtime_invocations_total
```

**预期输出**：
```
llama_stack_tool_runtime_invocations_total{
    tool_name="get_weather",
    tool_group="weather",
    provider="weather-runtime",
    status="success",
    service_name="llama-stack-server"
} 1
```

### 6. 验证 Prometheus 数据

```bash
# 等待 Prometheus 抓取 (15秒间隔)
sleep 20

# 查询 Prometheus
curl -s 'http://localhost:9090/api/v1/query?query=llama_stack_tool_runtime_invocations_total' | \
  python -m json.tool | grep -A 5 '"tool_name"'
```

**预期输出**：
```json
{
    "tool_name": "get_weather",
    "status": "success",
    "provider": "weather-runtime"
}
```

### 7. 验证 Grafana Dashboard

1. 打开浏览器: http://localhost:3000
2. 登录: admin / admin
3. 导航: Dashboards → Llama Stack → Tool Runtime Metrics
4. 查看面板:
   - Tool Invocation Rate
   - Success vs Error Rate
   - Tool Latency P50/P95/P99
   - Total Invocations

---

## 常用命令速查

```bash
# 启动完整系统 (推荐)
./start_weather_with_metrics.sh

# 手动启动 server (带 metrics)
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="llama-stack-server"
export OTEL_METRIC_EXPORT_INTERVAL="5000"
llama stack run weather-stack-config.yaml --port 8321

# 注册 tool group
curl -X POST http://localhost:8321/v1/toolgroups \
  -H "Content-Type: application/json" \
  -d '{"toolgroup_id": "weather", "provider_id": "weather-runtime"}'

# 列出 tool groups
llama-stack-client toolgroups list

# 测试工具
python test_weather_client.py

# 查看 metrics (OTLP Collector)
curl http://localhost:8889/metrics | grep llama_stack_tool

# 查询 Prometheus
curl 'http://localhost:9090/api/v1/query?query=llama_stack_tool_runtime_invocations_total'

# 查看 server 日志
tail -f /tmp/llama-stack-weather-metrics.log

# 停止 server
ps aux | grep "llama stack" | grep -v grep
kill <PID>
```

---

## 总结

### 关键要点

1. **Provider 结构**：
   - `config.py`: 配置类
   - `weather.py`: 实现逻辑（继承 ToolRuntime 和 ToolGroupsProtocolPrivate）
   - `__init__.py`: 导出 `get_provider_impl` 函数

2. **Registry 注册**：
   - 在 `src/llama_stack/providers/registry/tool_runtime.py` 中添加 `InlineProviderSpec`
   - 指定 `provider_type`, `module`, `config_class`

3. **Tool Group 注册**：
   - 配置文件中的 `tool_groups` 可能不自动生效
   - 需要通过 API 手动注册一次

4. **Metrics 关键**：
   - **必须设置** OTEL 环境变量才能导出 metrics
   - Metrics 在 `ToolRuntimeRouter` 中自动插桩
   - 无需修改 provider 代码即可获得 metrics

5. **调试技巧**：
   - 检查 server 日志确认 telemetry 初始化
   - 先查询 OTLP Collector (port 8889) 再查 Prometheus
   - 注意 Prometheus 抓取间隔 (15秒)

### 文件清单

```
llama-stack/
├── src/llama_stack/providers/
│   ├── inline/tool_runtime/weather/     # Weather Provider
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── weather.py
│   └── registry/
│       └── tool_runtime.py              # 已修改
│
├── weather-stack-config.yaml            # Server 配置
├── start_weather_with_metrics.sh        # 启动脚本
├── test_weather_client.py               # 测试客户端
└── WEATHER_TOOL_COMPLETE_GUIDE.md       # 本文档
```

---

**祝你使用愉快！🦙🌤️📊**
