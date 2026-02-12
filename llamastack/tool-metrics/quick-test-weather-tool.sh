#!/bin/bash
# Quick start script for testing the custom weather tool with metrics

set -e

echo "=============================================================="
echo "🦙 Llama Stack - Custom Weather Tool Metrics Test"
echo "=============================================================="
echo ""

# Check if we're in the right directory
if [ ! -f "test_weather_tool.py" ]; then
    echo "❌ Error: test_weather_tool.py not found"
    echo "   Please run this script from examples/metrics-demo directory"
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    echo "   Please start Docker and try again"
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Check if monitoring stack is running
if ! docker-compose ps | grep -q "llama-stack-otel-collector.*Up"; then
    echo "⚠️  Monitoring stack not running"
    echo ""
    read -p "Start monitoring stack now? (Y/n): " start_stack
    if [[ ! "$start_stack" =~ ^[Nn]$ ]]; then
        echo "📦 Starting monitoring stack..."
        docker-compose up -d
        echo "⏳ Waiting for services to be healthy..."
        sleep 30
    fi
fi

echo ""
echo "🔍 Checking monitoring stack..."
docker-compose ps

echo ""

# Configure environment for library mode (no server needed)
echo "🔧 Configuring test environment..."
export USE_SERVER_MODE="false"  # Use library mode
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="llama-stack-weather-tool"
export OTEL_METRIC_EXPORT_INTERVAL="5000"

echo "   ✓ USE_SERVER_MODE=false (library mode)"
echo "   ✓ OTEL_EXPORTER_OTLP_ENDPOINT=$OTEL_EXPORTER_OTLP_ENDPOINT"
echo "   ✓ OTEL_EXPORTER_OTLP_PROTOCOL=$OTEL_EXPORTER_OTLP_PROTOCOL"
echo "   ✓ OTEL_SERVICE_NAME=$OTEL_SERVICE_NAME"

echo ""

# Open UIs
echo "🌐 Opening monitoring dashboards..."
echo ""
echo "   📊 Prometheus: http://localhost:9090"
echo "   📈 Grafana:    http://localhost:3000 (admin/admin)"
echo ""

# Try to open in browser (macOS)
if command -v open &> /dev/null; then
    open http://localhost:9090 2>/dev/null || true
    sleep 1
    open http://localhost:3000 2>/dev/null || true
fi

echo ""
echo "=============================================================="
echo "🚀 Ready to test weather tool!"
echo "=============================================================="
echo ""
echo "The script will:"
echo "   - Use library mode (no server needed)"
echo "   - Create a custom weather tool provider"
echo "   - Invoke the weather tool every 1 second for 2 minutes"
echo "   - Generate metrics visible in Prometheus and Grafana"
echo ""
echo "Note: This is a MOCK weather service that returns random data."
echo "      In production, you'd integrate with a real weather API."
echo ""

read -p "Start testing now? (Y/n): " start_test

if [[ ! "$start_test" =~ ^[Nn]$ ]]; then
    echo ""
    echo "🎯 Starting weather tool tests..."
    echo ""
    python test_weather_tool.py
else
    echo ""
    echo "To run manually:"
    echo ""
    echo "   export USE_SERVER_MODE=false"
    echo "   export OTEL_EXPORTER_OTLP_ENDPOINT='http://localhost:4318'"
    echo "   export OTEL_EXPORTER_OTLP_PROTOCOL='http/protobuf'"
    echo "   python test_weather_tool.py"
    echo ""
fi
