#!/bin/bash
# Start llama-stack server with weather tool

set -e

echo "=============================================================="
echo "🦙 Starting Llama Stack Server with Weather Tool"
echo "=============================================================="
echo ""

# Stop any existing server
if pgrep -f "llama stack run" > /dev/null; then
    echo "⚠️  Stopping existing llama-stack server..."
    pkill -f "llama stack run" || true
    sleep 2
fi

# Check if weather provider files exist
if [ ! -f "src/llama_stack/providers/inline/tool_runtime/weather/weather.py" ]; then
    echo "❌ Error: Weather provider files not found"
    echo "   Please ensure provider files are created"
    exit 1
fi

# Check if config file exists
if [ ! -f "weather-stack-config.yaml" ]; then
    echo "❌ Error: weather-stack-config.yaml not found"
    exit 1
fi

echo "✅ Configuration files found"
echo ""

# Reinstall to pick up changes
echo "📦 Reinstalling llama-stack..."
pip install -e . > /dev/null 2>&1
echo "✅ Installation complete"
echo ""

# Start server
echo "🚀 Starting server on port 8321..."
echo ""
echo "   Server logs will appear below."
echo "   Press Ctrl+C to stop the server."
echo ""
echo "=============================================================="
echo ""

llama stack run weather-stack-config.yaml --port 8321
