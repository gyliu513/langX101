from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
import asyncio

transport = StreamableHttpTransport(url="http://0.0.0.0:8000/mcp")
client = Client(transport)

async def main():
    # Connection is established here
    async with client:
        print(f"Client connected: {client.is_connected()}")
        tools = await client.list_tools()
        print(f"Available tools: {tools}")
        if any(tool.name == "greet" for tool in tools):
            result = await client.call_tool("greet", {"name": "FastMCP 2.0"})
            print(f"Greet result: {result}")
            
    # Connection is closed automatically here
    print(f"Client connected: {client.is_connected()}")

if __name__ == "__main__":
    asyncio.run(main())
