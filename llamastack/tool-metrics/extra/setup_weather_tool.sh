#!/bin/bash
# Quick setup script for weather tool registration

set -e

echo "=============================================================="
echo "🦙 Setting up Weather Tool for Llama Stack"
echo "=============================================================="
echo ""

# Check if we're in the right directory
if [ ! -f "weather-stack-config.yaml" ]; then
    echo "❌ Error: weather-stack-config.yaml not found"
    echo "   Please run this script from the llama-stack project root"
    exit 1
fi

# Verify provider files exist
echo "🔍 Verifying provider files..."

if [ ! -f "src/llama_stack/providers/inline/tool_runtime/weather/__init__.py" ]; then
    echo "❌ Error: Weather provider files not found"
    echo "   Please ensure provider files are created in:"
    echo "   src/llama_stack/providers/inline/tool_runtime/weather/"
    exit 1
fi

echo "✅ Provider files found"
echo ""

# Check if registry is updated
if ! grep -q "inline::weather" src/llama_stack/providers/registry/tool_runtime.py; then
    echo "❌ Error: Weather provider not registered in tool_runtime.py"
    echo "   Please ensure src/llama_stack/providers/registry/tool_runtime.py"
    echo "   contains the InlineProviderSpec for inline::weather"
    exit 1
fi

echo "✅ Provider registered in registry"
echo ""

# Reinstall llama-stack to pick up changes
echo "📦 Reinstalling llama-stack (this may take a moment)..."
pip install -e . > /dev/null 2>&1 || {
    echo "⚠️  Warning: Failed to reinstall llama-stack"
    echo "   You may need to manually run: pip install -e ."
}

echo "✅ Installation complete"
echo ""

# Check if there's a running llama-stack server
if pgrep -f "llama stack run" > /dev/null; then
    echo "⚠️  Warning: A llama-stack server is already running"
    echo ""
    echo "You need to stop it first:"
    echo "   ps aux | grep 'llama stack'"
    echo "   kill <PID>"
    echo ""
    read -p "Would you like me to show the running processes? (y/N): " show_ps
    if [[ "$show_ps" =~ ^[Yy]$ ]]; then
        ps aux | grep "llama stack" | grep -v grep
    fi
    echo ""
fi

echo "=============================================================="
echo "✅ Setup Complete!"
echo "=============================================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Stop any running llama-stack server:"
echo "   ps aux | grep 'llama stack'"
echo "   kill <PID>"
echo ""
echo "2. Start the server with weather tool:"
echo "   llama stack run weather-stack-config.yaml --port 8321"
echo ""
echo "3. In another terminal, verify the tool is registered:"
echo "   llama-stack-client toolgroups list"
echo "   llama-stack-client tools list"
echo ""
echo "4. Test the weather tool:"
echo "   python test_weather_client.py"
echo ""
echo "5. (Optional) Enable metrics monitoring:"
echo "   cd examples/metrics-demo"
echo "   docker-compose up -d"
echo ""
echo "For detailed instructions, see: WEATHER_TOOL_GUIDE.md"
echo ""
