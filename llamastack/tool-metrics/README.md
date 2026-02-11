# 🦙 Llama Stack - Tool Runtime Metrics Demo

Complete end-to-end demo for visualizing tool runtime metrics using OpenTelemetry, Prometheus, and Grafana.

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Step-by-Step Guide](#step-by-step-guide)
- [Viewing Metrics](#viewing-metrics)
- [Troubleshooting](#troubleshooting)
- [Cleanup](#cleanup)

---

## 🎯 Overview

This demo showcases the tool runtime metrics system by:

1. Running an OpenTelemetry Collector to receive metrics
2. Storing metrics in Prometheus
3. Visualizing metrics in pre-configured Grafana dashboards
4. Generating sample metrics through simulated tool invocations

**Metrics Tracked:**
- `llama_stack.tool_runtime.invocations_total` - Total tool invocations (by tool, provider, status)
- `llama_stack.tool_runtime.duration_seconds` - Tool execution duration (histogram)

---

## 🏗️ Architecture

```
┌─────────────────┐
│  Llama Stack    │
│  (Your App)     │
└────────┬────────┘
         │ OTLP/HTTP (port 4318)
         │ Metrics Export
         ▼
┌─────────────────┐
│ OTLP Collector  │ ◄─── Receives metrics via OTLP
└────────┬────────┘
         │ Prometheus Format (port 8889)
         │ Exposes metrics
         ▼
┌─────────────────┐
│  Prometheus     │ ◄─── Scrapes & stores metrics
└────────┬────────┘
         │ PromQL queries
         │
         ▼
┌─────────────────┐
│    Grafana      │ ◄─── Visualizes metrics
└─────────────────┘
     (port 3000)
```

---

## ✅ Prerequisites

### Required

- **Docker** & **Docker Compose** installed
  ```bash
  docker --version  # Should be 20.10+
  docker-compose --version  # Should be 1.29+
  ```

- **Python 3.10+** with llama-stack installed
  ```bash
  python --version  # Should be 3.10+
  ```

### Optional

- `jq` for pretty-printing JSON (for troubleshooting)
  ```bash
  brew install jq  # macOS
  ```

---

## 🚀 Quick Start

**5-minute setup to see metrics in Grafana:**

```bash
# 1. Navigate to the demo directory
cd examples/metrics-demo

# 2. Start the monitoring stack
docker-compose up -d

# 3. Wait for services to be healthy (30 seconds)
sleep 30

# 4. Configure environment variables
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="llama-stack-demo"
export OTEL_METRIC_EXPORT_INTERVAL="5000"  # 5 seconds

# 5. Generate sample metrics
python generate_metrics.py

# 6. Open Grafana in your browser
open http://localhost:3000
# Login: admin / admin
# Dashboard is pre-loaded: "Llama Stack - Tool Runtime Metrics"
```

**That's it!** 🎉 You should see metrics flowing into the dashboard.

---

## 📖 Step-by-Step Guide

### Step 1: Start the Monitoring Stack

```bash
# From the examples/metrics-demo directory
cd examples/metrics-demo

# Start all services (OTLP Collector, Prometheus, Grafana)
docker-compose up -d

# Verify all services are running
docker-compose ps
```

**Expected output:**
```
NAME                            STATUS              PORTS
llama-stack-grafana             Up (healthy)        0.0.0.0:3000->3000/tcp
llama-stack-otel-collector      Up (healthy)        0.0.0.0:4318->4318/tcp, 0.0.0.0:8889->8889/tcp
llama-stack-prometheus          Up (healthy)        0.0.0.0:9090->9090/tcp
```

**Wait for health checks** (about 30 seconds):
```bash
# Watch until all show "healthy"
watch -n 2 docker-compose ps
```

---

### Step 2: Verify Services

#### Check OTLP Collector

```bash
# Check collector logs
docker-compose logs otel-collector

# Should see:
# "Everything is ready. Begin running and processing data."
```

#### Check Prometheus

```bash
# Open Prometheus UI
open http://localhost:9090

# Or curl the targets endpoint
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].health'
# Should return: "up"
```

#### Check Grafana

```bash
# Open Grafana UI
open http://localhost:3000

# Login credentials:
#   Username: admin
#   Password: admin
```

**First login:**
1. You'll be prompted to change the password (you can skip this)
2. Navigate to: Dashboards → Llama Stack → Tool Runtime Metrics
3. You should see an empty dashboard (no data yet)

---

### Step 3: Configure Llama Stack

Set the required environment variables to enable metrics export:

```bash
# OTLP endpoint (where to send metrics)
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"

# Protocol (http/protobuf is recommended)
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"

# Service name (appears in metrics)
export OTEL_SERVICE_NAME="llama-stack-demo"

# Export interval (5 seconds for demo, 60s for production)
export OTEL_METRIC_EXPORT_INTERVAL="5000"
```

**Verify configuration:**
```bash
env | grep OTEL_
```

---

### Step 4: Generate Metrics

Run the sample metrics generator:

```bash
# From the repo root, or with correct PYTHONPATH
python examples/metrics-demo/generate_metrics.py
```

**What this does:**
- Simulates tool invocations (brave-search, tavily-search, rag-query)
- Generates ~600 requests over 5 minutes at 2 req/sec
- Simulates realistic success rates and latencies
- Exports metrics to the OTLP Collector

**Expected output:**
```
==============================================================
🦙 Llama Stack - Tool Runtime Metrics Generator
==============================================================

🚀 Starting metrics generation for 300 seconds
📊 Target rate: 2.0 requests/second
💡 Total expected requests: ~600

⏱️  10s | Requests: 20 | Success: 19 | Failed: 1 | Rate: 95.0%
⏱️  20s | Requests: 40 | Success: 38 | Failed: 2 | Rate: 95.0%
...
```

**Keep this running** while you view the metrics in the next step.

---

### Step 5: View Metrics in Prometheus

While metrics are being generated, open Prometheus:

1. Go to: **http://localhost:9090**

2. Click on **"Graph"** tab

3. Try these queries:

   **Total invocations:**
   ```promql
   llama_stack_tool_runtime_invocations_total
   ```

   **Invocation rate per second:**
   ```promql
   rate(llama_stack_tool_runtime_invocations_total[1m])
   ```

   **P95 latency:**
   ```promql
   histogram_quantile(0.95, rate(llama_stack_tool_runtime_duration_seconds_bucket[1m]))
   ```

4. Click **"Execute"** and switch to **"Graph"** view

You should see data points appearing!

---

### Step 6: View Metrics in Grafana

Open the pre-configured dashboard:

1. Go to: **http://localhost:3000**

2. Navigate to: **Dashboards → Llama Stack → Tool Runtime Metrics**

3. You should see **7 panels** with live data:

   - **Tool Invocation Rate (per second)** - Line graph showing request rate by tool
   - **Success vs Error Rate** - Pie chart showing success/error ratio
   - **Tool Latency (P50, P95, P99)** - Multi-line graph showing latency percentiles
   - **Total Tool Invocations** - Single stat showing total count
   - **Error Rate by Provider** - Line graph showing errors by provider
   - **Invocations by Tool Group** - Donut chart showing distribution
   - **Tool Invocation Details** - Table with detailed breakdown

4. **Adjust the time range** (top right):
   - Select "Last 5 minutes"
   - Enable auto-refresh: "5s"

5. **Explore the data**:
   - Hover over graphs to see values
   - Click legend items to toggle series
   - Zoom in by dragging on the graph

---

## 📊 Viewing Metrics

### Prometheus UI (http://localhost:9090)

**Useful queries:**

```promql
# Total requests by tool
sum by (tool_name) (llama_stack_tool_runtime_invocations_total)

# Success rate
sum(rate(llama_stack_tool_runtime_invocations_total{status="success"}[5m]))
/
sum(rate(llama_stack_tool_runtime_invocations_total[5m]))

# Average latency
avg(rate(llama_stack_tool_runtime_duration_seconds_sum[1m]))
/
avg(rate(llama_stack_tool_runtime_duration_seconds_count[1m]))

# Errors per minute
sum(increase(llama_stack_tool_runtime_invocations_total{status="error"}[1m]))
```

### Grafana Dashboard (http://localhost:3000)

**Features:**
- Auto-refreshing every 5 seconds
- Pre-configured panels for all key metrics
- Color-coded for easy visualization
- Drill-down capabilities

**Tips:**
- Click on any panel title → "Edit" to see the underlying query
- Use the time picker to view historical data
- Create alerts by clicking "Alert" on any panel

---

## 🐛 Troubleshooting

### No metrics appearing in Prometheus

**Check 1: Is the OTLP Collector receiving metrics?**
```bash
docker-compose logs otel-collector | grep -i metric

# Should see lines like:
# "Metric #0"
# "llama_stack_tool_runtime_invocations_total"
```

**Check 2: Is Prometheus scraping the collector?**
```bash
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health, lastScrape: .lastScrape}'

# Should show:
# {
#   "job": "otel-collector",
#   "health": "up",
#   "lastScrape": "2024-02-11T20:30:00Z"
# }
```

**Check 3: Are environment variables set?**
```bash
env | grep OTEL_

# Should show:
# OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
# OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
# ...
```

**Check 4: Is the metrics generator running?**
```bash
ps aux | grep generate_metrics.py
```

---

### Grafana dashboard is empty

**Check 1: Is Prometheus data source configured?**
```bash
# In Grafana UI:
# Configuration → Data Sources → Prometheus
# Should show: "Data source is working"
```

**Check 2: Is there data in Prometheus?**
```bash
# Query Prometheus directly
curl -s 'http://localhost:9090/api/v1/query?query=llama_stack_tool_runtime_invocations_total' | jq '.data.result | length'

# Should return > 0
```

**Check 3: Check time range**
- Make sure the Grafana time picker is set to "Last 15 minutes" or "Last 5 minutes"
- The data might be outside your current time window

---

### Collector not receiving metrics

**Check 1: Verify llama-stack is exporting**
```bash
# Check if telemetry module is imported
python -c "from llama_stack.telemetry import setup_telemetry; print('OK')"
```

**Check 2: Test OTLP endpoint directly**
```bash
# Send a test metric
curl -X POST http://localhost:4318/v1/metrics \
  -H "Content-Type: application/x-protobuf" \
  --data-binary @/dev/null

# Should return: 200 OK (even with empty data)
```

**Check 3: Check Docker networking**
```bash
docker network ls | grep metrics

# Should show the metrics network
docker network inspect metrics-demo_metrics
```

---

### Services failing to start

**Check 1: Ports already in use**
```bash
# Check if ports are available
lsof -i :3000  # Grafana
lsof -i :9090  # Prometheus
lsof -i :4318  # OTLP Collector

# If something is using these ports, either:
# - Stop that service
# - Or edit docker-compose.yml to use different ports
```

**Check 2: Docker resources**
```bash
docker system df

# Make sure you have enough space
# Clean up if needed:
docker system prune
```

**Check 3: View service logs**
```bash
docker-compose logs -f [service-name]

# Examples:
docker-compose logs -f otel-collector
docker-compose logs -f prometheus
docker-compose logs -f grafana
```

---

## 🧹 Cleanup

### Stop the stack (keep data)
```bash
docker-compose stop
```

### Stop and remove containers (keep data)
```bash
docker-compose down
```

### Remove everything (including data volumes)
```bash
docker-compose down -v

# This will delete:
# - All containers
# - All volumes (Prometheus data, Grafana dashboards)
# - Network
```

### Remove only volumes (keep containers)
```bash
docker volume rm metrics-demo_prometheus-data
docker volume rm metrics-demo_grafana-data
```

---

## 📚 Additional Resources

### PromQL Cheat Sheet

```promql
# Rate of requests
rate(llama_stack_tool_runtime_invocations_total[5m])

# Increase in last hour
increase(llama_stack_tool_runtime_invocations_total[1h])

# Histogram quantiles
histogram_quantile(0.95, rate(llama_stack_tool_runtime_duration_seconds_bucket[5m]))

# Aggregations
sum by (tool_name) (...)
avg by (provider) (...)
max by (tool_group) (...)

# Filtering
{tool_name="web_search"}
{status="error"}
{provider=~"brave.*"}  # Regex
```

### Grafana Dashboard Customization

To modify the dashboard:
1. Edit in Grafana UI: Dashboard → Settings → JSON Model
2. Export: Dashboard → Share → Export → Save to file
3. Replace `grafana/dashboards/tool-runtime-metrics.json`
4. Restart: `docker-compose restart grafana`

### Production Recommendations

For production use:
1. **Increase scrape intervals** (15s → 60s in prometheus.yml)
2. **Set longer retention** (add `--storage.tsdb.retention.time=30d` to Prometheus)
3. **Enable authentication** (configure `GF_SECURITY_*` vars in Grafana)
4. **Set up alerts** (use Grafana alerting or Prometheus Alertmanager)
5. **Use persistent volumes** (already configured in docker-compose.yml)
6. **Monitor the monitoring stack** (enable Prometheus self-monitoring)

---

## 🎓 Learning More

- [OpenTelemetry Metrics Spec](https://opentelemetry.io/docs/specs/otel/metrics/)
- [Prometheus Query Language](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana Documentation](https://grafana.com/docs/grafana/latest/)
- [OTLP Collector Configuration](https://opentelemetry.io/docs/collector/configuration/)

---

## 🆘 Getting Help

If you encounter issues:

1. **Check logs**: `docker-compose logs -f`
2. **Verify health**: `docker-compose ps`
3. **Test connectivity**: Use the curl commands in troubleshooting
4. **File an issue**: [llama-stack GitHub Issues](https://github.com/llamastack/llama-stack/issues)

---

**Happy monitoring! 📊🦙**
