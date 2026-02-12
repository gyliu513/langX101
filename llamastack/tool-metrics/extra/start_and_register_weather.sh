#!/bin/bash
# Start llama-stack server with weather tool and register it

set -e

echo "=============================================================="
echo "🦙 Starting Llama Stack with Weather Tool"
echo "=============================================================="
echo ""

# Stop any existing server
if pgrep -f "llama stack run" > /dev/null; then
    echo "⚠️  Stopping existing llama-stack server..."
    pkill -f "llama stack run" || true
    sleep 2
fi

# Start server in background
echo "🚀 Starting server on port 8321..."
nohup llama stack run weather-stack-config.yaml --port 8321 > /tmp/llama-stack-weather.log 2>&1 &
SERVER_PID=$!

echo "   Server PID: $SERVER_PID"
echo "   Logs: /tmp/llama-stack-weather.log"
echo ""

# Wait for server to start
echo "⏳ Waiting for server to start..."
sleep 8

# Check if server is running
if ! curl -s http://localhost:8321/v1/health > /dev/null 2>&1; then
    echo "❌ Server failed to start"
    echo ""
    echo "Check logs:"
    echo "   tail -50 /tmp/llama-stack-weather.log"
    exit 1
fi

echo "✅ Server is running"
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
echo "🔍 Verifying registration..."
echo ""
llama-stack-client toolgroups list
echo ""

echo "=============================================================="
echo "✅ Setup Complete!"
echo "=============================================================="
echo ""
echo "Server is running in the background (PID: $SERVER_PID)"
echo ""
echo "To test the weather tool:"
echo "   python test_weather_client.py"
echo ""
echo "To stop the server:"
echo "   kill $SERVER_PID"
echo ""
echo "To view logs:"
echo "   tail -f /tmp/llama-stack-weather.log"
echo ""
