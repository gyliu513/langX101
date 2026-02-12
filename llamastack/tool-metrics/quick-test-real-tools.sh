#!/bin/bash
# Quick start script for testing real tool runtime with metrics

set -e

echo "=============================================================="
echo "🦙 Llama Stack - Real Tool Runtime Metrics Test"
echo "=============================================================="
echo ""

# Check if we're in the right directory
if [ ! -f "test_real_tools.py" ]; then
    echo "❌ Error: test_real_tools.py not found"
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

# Check for API keys
echo "🔑 Checking for API keys..."
has_keys=false

if [ -n "$BRAVE_SEARCH_API_KEY" ]; then
    echo "   ✅ BRAVE_SEARCH_API_KEY is set"
    has_keys=true
fi

if [ -n "$TAVILY_SEARCH_API_KEY" ]; then
    echo "   ✅ TAVILY_SEARCH_API_KEY is set"
    has_keys=true
fi

if [ -n "$WOLFRAM_ALPHA_API_KEY" ]; then
    echo "   ✅ WOLFRAM_ALPHA_API_KEY is set"
    has_keys=true
fi

if [ "$has_keys" = false ]; then
    echo ""
    echo "⚠️  No API keys found!"
    echo ""
    echo "You need at least one of these:"
    echo "   export BRAVE_SEARCH_API_KEY='your-key'"
    echo "   export TAVILY_SEARCH_API_KEY='your-key'"
    echo "   export WOLFRAM_ALPHA_API_KEY='your-key'"
    echo ""
    echo "Get free API keys from:"
    echo "   - Brave Search: https://brave.com/search/api/"
    echo "   - Tavily: https://tavily.com/"
    echo "   - Wolfram Alpha: https://products.wolframalpha.com/api/"
    echo ""
    read -p "Continue anyway? (y/N): " continue_choice
    if [[ ! "$continue_choice" =~ ^[Yy]$ ]]; then
        echo "Exiting..."
        exit 1
    fi
fi

echo ""

# Check if llama-stack server is running
echo "🔍 Checking for llama-stack server..."

LLAMA_STACK_URL="${LLAMA_STACK_URL:-http://localhost:5001}"

if curl -s "${LLAMA_STACK_URL}/v1/health" > /dev/null 2>&1; then
    echo "   ✅ Server is running at $LLAMA_STACK_URL"
else
    echo "   ⚠️  Server not detected at $LLAMA_STACK_URL"
    echo ""
    echo "You need to start llama-stack server first:"
    echo "   llama stack run <your-config>.yaml"
    echo ""
    echo "Or create a minimal config:"
    cat << 'EOF'

   # tool-test-config.yaml
   version: 2
   image_name: llamastack/distribution-together
   providers:
     tool_runtime:
       - provider_id: brave-search
         provider_type: remote::brave-search
         config:
           api_key: ${env.BRAVE_SEARCH_API_KEY:}

   Then run: llama stack run tool-test-config.yaml
EOF
    echo ""
    read -p "Continue anyway (use library mode)? (y/N): " lib_mode
    if [[ "$lib_mode" =~ ^[Yy]$ ]]; then
        export USE_SERVER_MODE="false"
        echo "   📚 Will use library mode (no server needed)"
    else
        echo "Exiting..."
        exit 1
    fi
fi

echo ""

# Configure environment
echo "🔧 Configuring metrics export..."
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="llama-stack-tools-test"
export OTEL_METRIC_EXPORT_INTERVAL="5000"

echo "   ✓ OTEL_EXPORTER_OTLP_ENDPOINT=$OTEL_EXPORTER_OTLP_ENDPOINT"
echo "   ✓ OTEL_EXPORTER_OTLP_PROTOCOL=$OTEL_EXPORTER_OTLP_PROTOCOL"
echo "   ✓ OTEL_SERVICE_NAME=$OTEL_SERVICE_NAME"
echo "   ✓ OTEL_METRIC_EXPORT_INTERVAL=$OTEL_METRIC_EXPORT_INTERVAL"

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
echo "🚀 Ready to test real tools!"
echo "=============================================================="
echo ""
echo "The script will:"
echo "   - Connect to llama-stack server (or use library mode)"
echo "   - List available tools"
echo "   - Invoke tools every 1 second for 2 minutes"
echo "   - Generate metrics visible in Prometheus and Grafana"
echo ""

read -p "Start testing now? (Y/n): " start_test

if [[ ! "$start_test" =~ ^[Nn]$ ]]; then
    echo ""
    echo "🎯 Starting real tool tests..."
    echo ""
    python test_real_tools.py
else
    echo ""
    echo "To run manually:"
    echo ""
    echo "   export OTEL_EXPORTER_OTLP_ENDPOINT='http://localhost:4318'"
    echo "   export OTEL_EXPORTER_OTLP_PROTOCOL='http/protobuf'"
    echo "   export LLAMA_STACK_URL='http://localhost:5001'"
    echo "   python test_real_tools.py"
    echo ""
fi
