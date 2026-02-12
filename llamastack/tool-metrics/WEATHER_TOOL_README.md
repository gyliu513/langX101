# Custom Weather Tool with Metrics

这是一个演示如何创建自定义 llama-stack 工具并监控其 metrics 的完整示例。

## 📋 概述

本示例包含：

1. **自定义天气工具** - 一个简单的 mock 天气查询工具
2. **Tool Runtime Metrics** - 自动记录工具调用的 metrics
3. **测试客户端** - 调用天气工具并生成 metrics 的脚本
4. **监控栈** - Prometheus + Grafana 可视化 metrics

## 🏗️ 架构

```
test_weather_tool.py (Client)
  ↓ invoke_tool("get_weather", {"city": "Tokyo"})
WeatherToolProvider
  ↓ 通过 ToolRuntimeRouter (已插桩!)
  ↓ 记录 metrics: invocations_total, duration_seconds
返回天气数据
  ↓
Metrics 导出到 OTLP Collector
  ↓ 每 5 秒
Prometheus 抓取 metrics
  ↓ 每 15 秒
Grafana 显示在 dashboard
```

## 📁 文件说明

```
examples/metrics-demo/
  ├── weather_tool/
  │   ├── __init__.py               - Package 初始化
  │   └── weather_provider.py       - 天气工具实现
  ├── test_weather_tool.py          - 测试客户端
  ├── quick-test-weather-tool.sh    - 一键启动脚本
  ├── weather-tool-config.yaml      - Server 模式配置 (可选)
  └── WEATHER_TOOL_README.md        - 本文档
```

## 🚀 快速开始

### 方法 1: 一键启动 (推荐)

```bash
cd examples/metrics-demo
./quick-test-weather-tool.sh
```

这个脚本会：
- 检查并启动 Docker 监控栈
- 配置环境变量
- 使用 library 模式运行测试 (无需 server)
- 打开 Grafana 和 Prometheus UI

### 方法 2: 手动运行

```bash
cd examples/metrics-demo

# 1. 启动监控栈
docker-compose up -d

# 2. 配置环境变量
export USE_SERVER_MODE="false"
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="llama-stack-weather-tool"

# 3. 运行测试
python test_weather_tool.py
```

## 🔧 工具实现详解

### WeatherToolProvider 类

```python
class WeatherToolProvider(ToolGroupsProtocolPrivate, ToolRuntime):
    """自定义天气工具 provider"""

    async def list_runtime_tools(self, ...) -> ListToolDefsResponse:
        """定义工具的 schema"""
        return ListToolDefsResponse(data=[
            ToolDef(
                name="get_weather",
                description="Get current weather for a city",
                input_schema={
                    "properties": {
                        "city": {"type": "string"},
                        "units": {"type": "string", "enum": ["celsius", "fahrenheit"]}
                    },
                    "required": ["city"]
                }
            )
        ])

    async def invoke_tool(self, tool_name, kwargs, ...) -> ToolInvocationResult:
        """执行工具逻辑"""
        city = kwargs.get("city")
        units = kwargs.get("units", "celsius")

        # 生成 mock 天气数据
        weather_data = self._get_mock_weather(city, units)

        return ToolInvocationResult(content=weather_data)
```

### 关键特性

1. **输入验证** - 检查 city 参数，验证 units
2. **错误处理** - 返回 ToolInvocationResult 带 error_code
3. **Mock 数据** - 生成随机温度、湿度、风速等
4. **Metrics 自动记录** - 通过 ToolRuntimeRouter 的插桩代码

## 📊 查看 Metrics

### Prometheus (http://localhost:9090)

查询示例：

```promql
# 天气工具调用总数
llama_stack_tool_runtime_invocations_total{tool_name="get_weather"}

# 每秒调用率
rate(llama_stack_tool_runtime_invocations_total{tool_name="get_weather"}[1m])

# 成功率
sum(rate(llama_stack_tool_runtime_invocations_total{tool_name="get_weather",status="success"}[1m]))
/
sum(rate(llama_stack_tool_runtime_invocations_total{tool_name="get_weather"}[1m]))

# P95 延迟
histogram_quantile(0.95,
  rate(llama_stack_tool_runtime_duration_seconds_bucket{tool_name="get_weather"}[1m])
)
```

### Grafana (http://localhost:3000)

1. 登录: `admin` / `admin`
2. 导航到: **Dashboards → Llama Stack → Tool Runtime Metrics**
3. 查看面板：
   - Tool Invocation Rate
   - Success vs Error Rate
   - Tool Latency (P50, P95, P99)
   - Invocations by Tool Group

你应该能看到 `get_weather` 工具的调用数据。

## 🎯 预期输出

### 控制台输出

```
==============================================================
🦙 Llama Stack - Weather Tool Metrics Test
==============================================================

🔧 Configuration:
   Mode: Library (Direct)

✅ OTLP Export: http://localhost:4318

📚 Initializing library mode (no server needed)
✅ Library client initialized with weather tool

📋 Listing available tools...
   Found 1 tool(s):
   - get_weather: Get current weather information for a city

==============================================================
🚀 Starting weather tool invocation tests
==============================================================
Duration: 120 seconds
Rate: 1.0 requests/second
Total expected requests: ~120

✅ get_weather(Tokyo): 0.01s
   Weather in Tokyo:
✅ get_weather(London): 0.01s
   Weather in London:
✅ get_weather(Paris): 0.01s
   Weather in Paris:

⏱️  10s | Requests: 10 | Success: 10 | Failed: 0 | Rate: 100.0%
...
```

### Grafana Dashboard

应该看到：
- **Invocation Rate**: ~1 req/s
- **Success Rate**: ~100%
- **Latency**: P95 < 0.1s (因为是 mock 数据)
- **Total Invocations**: 逐渐增加到 ~120

## 🔄 两种运行模式

### Library 模式 (默认)

```bash
export USE_SERVER_MODE="false"
python test_weather_tool.py
```

**优点:**
- 无需启动 llama-stack server
- 更快的启动时间
- 更简单的 setup

**用途:**
- 快速测试和开发
- 单元测试
- Demo 和教学

### Server 模式

```bash
# 1. 启动 server
llama stack run weather-tool-config.yaml

# 2. 运行测试
export USE_SERVER_MODE="true"
export LLAMA_STACK_URL="http://localhost:5001"
python test_weather_tool.py
```

**优点:**
- 更接近生产环境
- 可以从多个 client 连接
- 支持完整的 API

**用途:**
- 生产部署
- 集成测试
- 多客户端场景

**注意:** Server 模式需要在 llama-stack 中正确注册 provider (需要修改 provider registry)

## 🛠️ 自定义你的工具

### 1. 修改工具逻辑

编辑 `weather_tool/weather_provider.py`:

```python
async def invoke_tool(self, tool_name, kwargs, ...) -> ToolInvocationResult:
    # 替换 mock 数据为真实 API 调用
    city = kwargs.get("city")

    # 例如：调用 OpenWeatherMap API
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.json()

    return ToolInvocationResult(content=format_weather(data))
```

### 2. 添加新工具

在 `list_runtime_tools` 中添加：

```python
return ListToolDefsResponse(data=[
    ToolDef(name="get_weather", ...),
    ToolDef(
        name="get_forecast",
        description="Get 5-day weather forecast",
        input_schema={...}
    ),
])
```

在 `invoke_tool` 中处理：

```python
if tool_name == "get_weather":
    return await self._get_current_weather(kwargs)
elif tool_name == "get_forecast":
    return await self._get_forecast(kwargs)
```

### 3. 修改测试参数

编辑 `test_weather_tool.py` 的 `main()` 函数：

```python
await tester.run_weather_tests(
    duration_seconds=300,  # 5 分钟
    requests_per_second=2.0,  # 2 req/s
)
```

## 🐛 故障排除

### 导入错误: "No module named 'examples'"

```bash
# 确保从项目根目录运行
cd /path/to/llama-stack
python examples/metrics-demo/test_weather_tool.py
```

或设置 PYTHONPATH:

```bash
export PYTHONPATH=/path/to/llama-stack:$PYTHONPATH
```

### OTLP Collector 连接被拒绝

```bash
# 检查 Docker stack
docker-compose ps

# 重启 collector
docker-compose restart otel-collector

# 检查日志
docker-compose logs otel-collector
```

### Grafana 中没有数据

1. 检查时间范围: 设置为 "Last 15 minutes"
2. 启用自动刷新: 5s
3. 检查 Prometheus 是否有数据: http://localhost:9090
4. 验证 metric 名称: `llama_stack_tool_runtime_invocations_total`

## 📚 扩展阅读

- [llama-stack Tool Runtime API](https://llama-stack.com/docs/tool-runtime)
- [OpenTelemetry Metrics](https://opentelemetry.io/docs/concepts/signals/metrics/)
- [Prometheus PromQL](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana Dashboards](https://grafana.com/docs/grafana/latest/dashboards/)

## 🎓 学习要点

通过这个示例，你学会了：

1. ✅ 如何创建自定义 llama-stack tool provider
2. ✅ 如何定义工具的 input/output schema
3. ✅ 如何实现 `invoke_tool` 逻辑
4. ✅ 如何使用 library 模式测试工具
5. ✅ 如何自动记录和导出 metrics
6. ✅ 如何在 Prometheus 和 Grafana 中可视化 metrics

## 🚀 下一步

现在你可以：

1. **集成真实 API** - 替换 mock 数据为真实的天气 API
2. **添加更多工具** - 创建工具组，如搜索、计算、数据库查询
3. **部署到生产** - 使用 server 模式，配置负载均衡
4. **监控告警** - 在 Grafana 中设置告警规则
5. **优化性能** - 使用 metrics 发现瓶颈并优化

Happy coding! 🦙📊
