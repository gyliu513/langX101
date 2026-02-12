#!/bin/bash
# Start llama-stack server with weather tool AND metrics export

set -e

echo "=============================================================="
echo "🦙 Starting Llama Stack with Weather Tool + Metrics"
echo "=============================================================="
echo ""

# Stop any existing server
if pgrep -f "llama stack run" > /dev/null; then
    echo "⚠️  Stopping existing llama-stack server..."
    pkill -f "llama stack run" || true
    sleep 2
fi

# Check if Docker monitoring stack is running
echo "🔍 Checking monitoring stack..."
cd examples/metrics-demo
if ! docker-compose ps | grep -q "llama-stack-otel-collector"; then
    echo "⚠️  Monitoring stack not running"
    echo ""
    read -p "Start monitoring stack now? (Y/n): " start_stack
    if [[ ! "$start_stack" =~ ^[Nn]$ ]]; then
        echo "📦 Starting monitoring stack..."
        docker-compose up -d
        echo "⏳ Waiting for services to start..."
        sleep 10
    fi
else
    echo "✅ Monitoring stack is running"
fi

cd ../..
echo ""

# Export OpenTelemetry environment variables
echo "🔧 Configuring OpenTelemetry..."
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="llama-stack-server"
export OTEL_METRIC_EXPORT_INTERVAL="5000"  # 5 seconds

echo "   ✓ OTEL_EXPORTER_OTLP_ENDPOINT=$OTEL_EXPORTER_OTLP_ENDPOINT"
echo "   ✓ OTEL_EXPORTER_OTLP_PROTOCOL=$OTEL_EXPORTER_OTLP_PROTOCOL"
echo "   ✓ OTEL_SERVICE_NAME=$OTEL_SERVICE_NAME"
echo "   ✓ OTEL_METRIC_EXPORT_INTERVAL=$OTEL_METRIC_EXPORT_INTERVAL"
echo ""

# Start server in background with OTEL env vars
echo "🚀 Starting server on port 8321 (with metrics export)..."
nohup llama stack run weather-stack-config.yaml --port 8321 > /tmp/llama-stack-weather-metrics.log 2>&1 &
SERVER_PID=$!

echo "   Server PID: $SERVER_PID"
echo "   Logs: /tmp/llama-stack-weather-metrics.log"
echo ""

# Wait for server to start
echo "⏳ Waiting for server to start..."
sleep 8

# Check if server is running
if ! curl -s http://localhost:8321/v1/health > /dev/null 2>&1; then
    echo "❌ Server failed to start"
    echo ""
    echo "Check logs:"
    echo "   tail -50 /tmp/llama-stack-weather-metrics.log"
    exit 1
fi

echo "✅ Server is running"
echo ""

# Check if telemetry is initialized
echo "🔍 Checking telemetry initialization..."
if grep -q "OpenTelemetry metrics exporter configured" /tmp/llama-stack-weather-metrics.log; then
    echo "✅ OpenTelemetry metrics exporter is configured!"
    grep "OpenTelemetry metrics exporter configured" /tmp/llama-stack-weather-metrics.log | tail -1
else
    echo "⚠️  Telemetry may not be initialized. Check logs:"
    echo "   grep -i 'telemetry\|otel' /tmp/llama-stack-weather-metrics.log"
fi
echo ""

# Register weather tool group
echo "📝 Registering weather tool group..."
RESPONSE=$(curl -s -X POST http://localhost:8321/v1/toolgroups \
  -H "Content-Type: application/json" \
  -d '{
    "toolgroup_id": "weather",
    "provider_id": "weather-runtime"
  }')

if [ "$RESPONSE" == "null" ] || [ -z "$RESPONSE" ]; then
    echo "✅ Weather tool group registered"
else
    echo "⚠️  Registration response: $RESPONSE"
fi

echo ""

# Verify registration
echo "🔍 Verifying tool registration..."
echo ""
llama-stack-client toolgroups list
echo ""

echo "=============================================================="
echo "✅ Setup Complete!"
echo "=============================================================="
echo ""
echo "Server is running with metrics export enabled!"
echo "Server PID: $SERVER_PID"
echo ""
echo "To test the weather tool (and generate metrics):"
echo "   python test_weather_client.py"
echo ""
echo "To view metrics:"
echo "   📊 Prometheus: http://localhost:9090"
echo "   📈 Grafana:    http://localhost:3000 (admin/admin)"
echo ""
echo "PromQL query:"
echo "   llama_stack_tool_runtime_invocations_total{tool_name=\"get_weather\"}"
echo ""
echo "To stop the server:"
echo "   kill $SERVER_PID"
echo ""
echo "To view logs:"
echo "   tail -f /tmp/llama-stack-weather-metrics.log"
echo ""
