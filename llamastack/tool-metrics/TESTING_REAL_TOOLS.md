# Testing Real Tool Runtime with Metrics

This guide shows you how to test real llama-stack tool runtime and generate actual metrics.

## 🎯 Overview

The `test_real_tools.py` script invokes real llama-stack tools (brave-search, tavily-search, etc.) and generates metrics that flow to Prometheus and Grafana.

## 📋 Prerequisites

### 1. Docker Stack Running

```bash
cd examples/metrics-demo
docker-compose up -d

# Verify all services are healthy
docker-compose ps
```

### 2. Llama Stack Server Running

You need a running llama-stack server with tool runtime configured.

**Option A: Use an existing config**

```bash
llama stack run <your-config>.yaml
```

**Option B: Create a minimal config**

Create `tool-test-config.yaml`:

```yaml
version: 2
image_name: llamastack/distribution-together
providers:
  tool_runtime:
    - provider_id: brave-search
      provider_type: remote::brave-search
      config:
        api_key: ${env.BRAVE_SEARCH_API_KEY:}
```

Then run:

```bash
llama stack run tool-test-config.yaml
```

### 3. API Keys (at least one)

Set environment variables for the tools you want to test:

```bash
# Brave Search (recommended)
export BRAVE_SEARCH_API_KEY="your-key-here"

# Tavily Search
export TAVILY_SEARCH_API_KEY="your-key-here"

# Wolfram Alpha
export WOLFRAM_ALPHA_API_KEY="your-key-here"
```

Get API keys from:
- Brave Search: https://brave.com/search/api/
- Tavily: https://tavily.com/
- Wolfram Alpha: https://products.wolframalpha.com/api/

---

## 🚀 Running the Test

### Basic Usage

```bash
cd examples/metrics-demo

# 1. Configure metrics export
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="llama-stack-tools"
export OTEL_METRIC_EXPORT_INTERVAL="5000"

# 2. Run the test script
python test_real_tools.py
```

### Configuration Options

**Connect to a specific server URL:**

```bash
export LLAMA_STACK_URL="http://localhost:5001"
python test_real_tools.py
```

**Use library mode (no server needed):**

```bash
export USE_SERVER_MODE="false"
python test_real_tools.py
```

**Customize test duration and rate:**

Edit `test_real_tools.py` line ~280:

```python
await tester.run_tool_tests(
    duration_seconds=300,  # Run for 5 minutes
    requests_per_second=2.0  # 2 requests per second
)
```

---

## 📊 Viewing Metrics

### Prometheus (http://localhost:9090)

1. Go to **Graph** tab
2. Enter query:
   ```promql
   llama_stack_tool_runtime_invocations_total
   ```
3. Click **Execute**

**Useful queries:**

```promql
# Tool invocation rate
rate(llama_stack_tool_runtime_invocations_total[1m])

# Success rate
sum(rate(llama_stack_tool_runtime_invocations_total{status="success"}[5m]))
/
sum(rate(llama_stack_tool_runtime_invocations_total[5m]))

# P95 latency by tool
histogram_quantile(0.95, rate(llama_stack_tool_runtime_duration_seconds_bucket[1m]))
```

### Grafana (http://localhost:3000)

1. Login: **admin** / **admin**
2. Navigate to: **Dashboards → Llama Stack → Tool Runtime Metrics**
3. You should see:
   - Tool Invocation Rate
   - Success vs Error Rate
   - Tool Latency (P50, P95, P99)
   - Total Invocations
   - Error Rate by Provider
   - Invocations by Tool Group
   - Tool Invocation Details

---

## 🎯 Expected Output

### Console Output

```
==============================================================
🦙 Llama Stack - Real Tool Runtime Metrics Test
==============================================================

🔧 Configuration:
   Mode: HTTP Client (Server)
   Server URL: http://localhost:5001

✅ OTLP Export: http://localhost:4318

📡 Connecting to llama-stack server at http://localhost:5001
✅ Connected to server successfully

📋 Available tools: 1
   - web_search (brave-search)

==============================================================
🚀 Starting tool invocation tests
==============================================================
Duration: 120 seconds
Rate: 1.0 requests/second
Total expected requests: ~120

✅ web_search: 0.85s
✅ web_search: 1.23s
✅ web_search: 0.92s

⏱️  10s | Requests: 10 | Success: 10 | Failed: 0 | Rate: 100.0%

...
```

### Metrics in Grafana

You should see live graphs updating with:
- Tool invocation counts increasing
- Latency percentiles (P50, P95, P99)
- Success/error ratios
- Provider breakdown

---

## 🐛 Troubleshooting

### "Failed to connect to server"

**Problem:** Script can't connect to llama-stack server

**Solutions:**
1. Check server is running: `curl http://localhost:5001/v1/health`
2. Verify port: Default is 5001, check your config
3. Set correct URL: `export LLAMA_STACK_URL="http://localhost:YOUR_PORT"`

### "No tools available to test"

**Problem:** No tools are registered

**Solutions:**
1. Check tool groups: `curl http://localhost:5001/v1/toolgroups`
2. Verify tool runtime is configured in your llama-stack config
3. Make sure API keys are set

### "Connection refused" errors (OTLP)

**Problem:** Metrics can't be exported

**Solutions:**
1. Check Docker stack is running: `docker-compose ps`
2. Restart OTLP collector: `docker-compose restart otel-collector`
3. Verify endpoint: `curl http://localhost:4318/v1/metrics`

### Tool invocations fail with auth errors

**Problem:** API key issues

**Solutions:**
1. Verify API key is set: `echo $BRAVE_SEARCH_API_KEY`
2. Check key is valid
3. Try with a different tool that you have credentials for

---

## 📚 Advanced Usage

### Test Specific Tools Only

Edit the `test_queries` dict in `test_real_tools.py` to only include tools you want to test:

```python
test_queries = {
    "web_search": [
        "latest AI news",
        "quantum computing",
    ],
    # Remove or comment out other tools
}
```

### Concurrent Requests

Modify the script to send multiple requests in parallel:

```python
# In run_tool_tests method
tasks = []
for _ in range(requests_per_batch):
    tool = random.choice(self.available_tools)
    task = self.invoke_tool(tool.name, {"query": random.choice(queries)})
    tasks.append(task)

results = await asyncio.gather(*tasks, return_exceptions=True)
```

### Custom Metrics Labels

The metrics automatically include:
- `tool_group`: Group the tool belongs to (e.g., "websearch")
- `tool_name`: Name of the tool (e.g., "web_search")
- `provider`: Provider ID (e.g., "brave-search::impl")
- `status`: "success" or "error"

These are set automatically by the ToolRuntimeRouter instrumentation we added in Phase 1.

---

## 💡 Tips

1. **Start small**: Begin with 1 req/sec for 1-2 minutes to verify everything works
2. **Monitor resources**: Watch Docker container resource usage
3. **Check logs**: Use `docker-compose logs -f` to see what's happening
4. **Use Brave Search**: It's the easiest to set up and most reliable
5. **Real queries**: Use realistic queries to get meaningful latency metrics

---

## 🎓 What's Being Tested

When you run this script, the flow is:

```
test_real_tools.py
  ↓ HTTP POST to /v1/tool-runtime/invoke
llama-stack server
  ↓ ToolRuntimeRouter.invoke_tool (instrumented!)
  ↓ Records metrics: invocations_total, duration_seconds
Brave Search API (or other tool)
  ↓ Returns results
Metrics exported to OTLP Collector
  ↓ Every 5 seconds
Prometheus scrapes collector
  ↓ Every 15 seconds
Grafana displays in dashboard
  ↓ Auto-refresh every 5 seconds
You see beautiful metrics! 📈
```

---

## 🔗 Related Files

- `generate_metrics.py` - Simulated metrics generator (for testing without real tools)
- `test_real_tools.py` - Real tool invocation (this script)
- `docker-compose.yml` - Monitoring stack configuration
- `README.md` - Complete setup guide

---

Happy testing! 🦙📊
