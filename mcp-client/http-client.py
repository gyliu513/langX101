from dotenv import load_dotenv

load_dotenv() 

import asyncio
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession


async def main():
    # MCP server URL - make sure this matches your running server
    mcp_server_url = "http://127.0.0.1:8000/mcp"
    
    print(f"Connecting to MCP server at: {mcp_server_url}")
    
    try:
        # Connect to a streamable HTTP server with timeout
        async with asyncio.timeout(10):
            async with streamablehttp_client(mcp_server_url) as (
                read_stream,
                write_stream,
                _,  # session_id_callback (unused)
            ):
                print("HTTP connection established")
                
                # Create a session using the client streams
                async with ClientSession(read_stream, write_stream) as session:
                    print("Client session created")
                    
                    # Initialize the connection
                    await session.initialize()
                    print("Session initialized successfully")
                    
                    # List available tools
                    tool_result = await session.list_tools()
                    print(f"Available tools: {len(tool_result.tools)}")
                    
                    for tool in tool_result.tools:
                        print(f"  - {tool.name}: {tool.description}")
                    
                    # Optionally call a specific tool (example)
                    # if tool_result.tools:
                    #     first_tool = tool_result.tools[0]
                    #     result = await session.call_tool(first_tool.name, {})
                    #     print(f"Tool result: {result}")
                    
    except asyncio.TimeoutError:
        print("❌ Timeout connecting to MCP server")
        print("Make sure the MCP server is running:")
        print("  cd mcp-instana")
        print("  python src/mcp_server.py --host 127.0.0.1 --port 8000")
    except ConnectionError as e:
        print(f"❌ Connection error: {e}")
        print("Make sure the MCP server is running and accessible")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        print("Check if the MCP server is properly configured and running")


if __name__ == "__main__":
    asyncio.run(main())