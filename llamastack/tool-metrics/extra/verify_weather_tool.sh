#!/bin/bash
# Verify weather tool is registered and working

echo "=============================================================="
echo "🔍 Verifying Weather Tool Registration"
echo "=============================================================="
echo ""

# Check if server is running
echo "1. Checking if server is running..."
if ! curl -s http://localhost:8321/v1/health > /dev/null 2>&1; then
    echo "❌ Server is not running on port 8321"
    echo ""
    echo "Please start the server first:"
    echo "   ./start_weather_server.sh"
    exit 1
fi
echo "✅ Server is running"
echo ""

# List tool groups
echo "2. Listing tool groups..."
echo ""
llama-stack-client toolgroups list
echo ""

# List tools
echo "3. Listing tools..."
echo ""
llama-stack-client tools list
echo ""

# Run Python test
echo "4. Running Python client test..."
echo ""
python test_weather_client.py
