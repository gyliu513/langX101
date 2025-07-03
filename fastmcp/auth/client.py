from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
import asyncio
import sys

async def main():
    transport = StreamableHttpTransport(url="http://localhost:8000/mcp")
    client = Client(transport)
    
    try:
        # Connection is established here
        async with client:
            print(f"✅ Client connected: {client.is_connected()}")
            
            # List available tools
            tools = await client.list_tools()
            print(f"📋 Available tools: {[tool.name for tool in tools]}")
            
            # Test the greet tool
            if any(tool.name == "greet" for tool in tools):
                print("🎯 Testing greet tool...")
                result = await client.call_tool("greet", {"name": "FastMCP 2.0"})
                print(f"💬 Greet result: {result}")
            else:
                print("❌ Greet tool not found!")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        print("💡 Make sure the server is running with: uv run server.py")
        sys.exit(1)
    
    # Connection is closed automatically here
    print(f"🔌 Client disconnected: {client.is_connected()}")

if __name__ == "__main__":
    print("🚀 Starting FastMCP client...")
    asyncio.run(main())
