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
        for tool in tools:
            if tool.name == "greet":
                result = await client.call_tool("greet", {"name": "FastMCP 2.0"})
                print(f"Greet result: {result}")
            elif tool.name == "add":
                result = await client.call_tool("add", {"a": 5, "b": 7})
                print(f"Add result: {result}")
    # Connection is closed automatically here
    print(f"Client connected: {client.is_connected()}")

if __name__ == "__main__":
    asyncio.run(main())
