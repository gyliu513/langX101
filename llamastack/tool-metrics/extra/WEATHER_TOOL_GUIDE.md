# 天气工具注册和使用指南

本指南说明如何将自定义天气工具注册到 llama-stack 并通过 client 调用。

## 📁 已创建的文件

### 1. Provider 实现 (src/llama_stack/providers/inline/tool_runtime/weather/)

```
src/llama_stack/providers/inline/tool_runtime/weather/
  ├── __init__.py          - Provider 导出
  ├── config.py            - 配置类定义
  └── weather.py           - 天气工具实现
```

### 2. Provider 注册

- **文件**: `src/llama_stack/providers/registry/tool_runtime.py`
- **修改**: 添加了 `InlineProviderSpec` 注册 `inline::weather` provider

### 3. 配置和测试文件

- `weather-stack-config.yaml` - Server 启动配置
- `test_weather_client.py` - 客户端测试脚本

## 🚀 使用步骤

### 步骤 1: 停止当前的 llama-stack server

如果你当前有 llama-stack server 在运行，先停止它：

```bash
# 找到进程
ps aux | grep "llama stack"

# 杀掉进程
kill <PID>
```

### 步骤 2: 启动包含天气工具的 server

```bash
# 在项目根目录
cd /Users/gualiu/go/src/github.com/llamastack/llama-stack

# 启动 server (使用你之前的端口 8321)
llama stack run weather-stack-config.yaml --port 8321
```

你应该看到类似的输出：

```
🦙 Starting llama-stack server...
   Tool Runtime: inline::weather
   Tool Groups: weather

Listening on http://0.0.0.0:8321
```

### 步骤 3: 使用 llama-stack-client 验证注册

在另一个终端窗口：

```bash
# 列出 tool groups
llama-stack-client toolgroups list

# 应该看到:
# ┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
# ┃ identifier ┃ provider_id     ┃
# ┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
# │ weather    │ weather-runtime │
# └───────────┴─────────────────┘
```

```bash
# 列出 tools
llama-stack-client tools list

# 应该看到:
# ┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ name         ┃ description                             ┃
# ┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
# │ get_weather  │ Get current weather information for... │
# └─────────────┴─────────────────────────────────────────┘
```

### 步骤 4: 通过 Python client 调用天气工具

```bash
python test_weather_client.py
```

预期输出：

```
======================================================================
🦙 Testing Weather Tool Registration
======================================================================

📋 Listing tool groups...
Found 1 tool group(s):
  - weather (provider: weather-runtime)

🔧 Listing tools...
Found 1 tool(s):
  - get_weather: Get current weather information for a city

🌤️  Invoking weather tool...

✅ San Francisco:
   Weather in San Francisco:
   Temperature: 18.5°C

✅ New York:
   Weather in New York:
   Temperature: 12.3°C

✅ Tokyo:
   Weather in Tokyo:
   Temperature: 22.1°C

======================================================================
✅ Test completed!
======================================================================
```

### 步骤 5: 查看 Metrics (可选)

如果你启动了监控栈，可以在 Grafana 中看到天气工具的调用 metrics：

```bash
cd examples/metrics-demo
docker-compose up -d
```

然后访问：
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000

在 Prometheus 中查询：

```promql
llama_stack_tool_runtime_invocations_total{tool_name="get_weather"}
```

## 🔧 配置说明

### weather-stack-config.yaml

```yaml
version: 2
image_name: llamastack/distribution-together

providers:
  tool_runtime:
    - provider_id: weather-runtime
      provider_type: inline::weather  # 注册的 provider 类型
      config: {}

tool_groups:
  - toolgroup_id: weather
    provider_id: weather-runtime
```

### 关键点

1. **provider_type**: `inline::weather` 必须与 registry 中注册的一致
2. **provider_id**: 可以自定义，如 `weather-runtime`
3. **toolgroup_id**: Tool group 的标识符，client 可以用它来过滤工具

## 📊 与现有工具集成

如果你想同时使用天气工具和其他工具（如 Tavily Search），可以这样配置：

```yaml
version: 2

providers:
  tool_runtime:
    # 天气工具
    - provider_id: weather-runtime
      provider_type: inline::weather
      config: {}

    # Tavily Search
    - provider_id: tavily-search
      provider_type: remote::tavily-search
      config:
        api_key: ${env.TAVILY_SEARCH_API_KEY:}

tool_groups:
  - toolgroup_id: weather
    provider_id: weather-runtime

  - toolgroup_id: builtin::websearch
    provider_id: tavily-search
```

然后你就能同时使用两种工具：

```python
# 获取天气
weather_result = client.tool_runtime.invoke_tool(
    tool_name="get_weather",
    kwargs={"city": "Tokyo"}
)

# 搜索网页
search_result = client.tool_runtime.invoke_tool(
    tool_name="web_search",
    kwargs={"query": "latest AI news"}
)
```

## 🛠️ 自定义你的工具

### 修改工具逻辑

编辑 `src/llama_stack/providers/inline/tool_runtime/weather/weather.py`:

```python
async def invoke_tool(self, tool_name, kwargs, ...) -> ToolInvocationResult:
    city = kwargs.get("city")

    # 替换为真实 API 调用
    import httpx
    api_key = os.environ.get("OPENWEATHER_API_KEY")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": api_key, "units": "metric"}
        )
        data = response.json()

    # 格式化真实数据
    weather_report = f"""Weather in {data['name']}:
Temperature: {data['main']['temp']}°C
Condition: {data['weather'][0]['description']}
Humidity: {data['main']['humidity']}%
Wind Speed: {data['wind']['speed']} m/s"""

    return ToolInvocationResult(content=weather_report)
```

### 添加更多工具

在 `weather.py` 中添加新工具：

```python
async def list_runtime_tools(self, ...) -> ListToolDefsResponse:
    return ListToolDefsResponse(data=[
        ToolDef(
            name="get_weather",
            description="Get current weather",
            ...
        ),
        ToolDef(
            name="get_forecast",
            description="Get 5-day weather forecast",
            input_schema={
                "properties": {
                    "city": {"type": "string"},
                    "days": {"type": "integer", "default": 5}
                }
            }
        ),
    ])
```

然后在 `invoke_tool` 中处理新工具：

```python
async def invoke_tool(self, tool_name, kwargs, ...) -> ToolInvocationResult:
    if tool_name == "get_weather":
        return await self._get_current_weather(kwargs)
    elif tool_name == "get_forecast":
        return await self._get_forecast(kwargs)
    else:
        return ToolInvocationResult(error_message=f"Unknown tool: {tool_name}")
```

### 添加配置参数

在 `config.py` 中添加配置：

```python
class WeatherToolRuntimeConfig(BaseModel):
    api_key: str | None = None
    default_units: str = "celsius"
    cache_ttl_seconds: int = 300
```

然后在 `weather.py` 中使用：

```python
def __init__(self, config: WeatherToolRuntimeConfig):
    self.config = config
    self.api_key = config.api_key
    self.default_units = config.default_units
```

在配置文件中设置：

```yaml
providers:
  tool_runtime:
    - provider_id: weather-runtime
      provider_type: inline::weather
      config:
        api_key: ${env.OPENWEATHER_API_KEY:}
        default_units: "fahrenheit"
        cache_ttl_seconds: 600
```

## 🐛 故障排除

### 1. Provider 未注册

**错误**: `Unknown provider type: inline::weather`

**解决**:
- 确认 `src/llama_stack/providers/registry/tool_runtime.py` 中已添加 weather provider
- 重新安装 llama-stack: `pip install -e .`

### 2. 模块导入错误

**错误**: `ModuleNotFoundError: No module named 'llama_stack.providers.inline.tool_runtime.weather'`

**解决**:
- 确认文件已创建在正确位置
- 检查 `__init__.py` 文件存在
- 重启 server

### 3. Tool group 未显示

**错误**: `llama-stack-client toolgroups list` 不显示 weather

**解决**:
- 检查配置文件中的 `tool_groups` 部分
- 确认 server 启动时使用了正确的配置文件
- 查看 server 日志是否有错误

### 4. Invoke 失败

**错误**: 调用工具返回错误

**解决**:
- 检查 kwargs 参数是否正确
- 查看 server 日志获取详细错误信息
- 验证工具的 input_schema 定义

## 📚 相关资源

- [Llama Stack 文档](https://llama-stack.com)
- [Tool Runtime API](https://llama-stack.com/docs/tool-runtime)
- [Provider 开发指南](https://llama-stack.com/docs/providers)
- [OpenTelemetry Metrics](https://opentelemetry.io/docs/concepts/signals/metrics/)

## 🎯 总结

你已经成功：

1. ✅ 创建了自定义天气工具 provider
2. ✅ 在 llama-stack registry 中注册了 provider
3. ✅ 通过配置文件启动了包含天气工具的 server
4. ✅ 使用 llama-stack-client 查询和调用工具
5. ✅ 自动记录 tool runtime metrics

下一步你可以：

- 集成真实天气 API
- 添加更多工具（forecast, air quality, etc.）
- 部署到生产环境
- 设置监控和告警

Happy coding! 🦙🌤️
