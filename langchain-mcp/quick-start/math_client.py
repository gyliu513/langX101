import asyncio
import json
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from langchain_mcp_adapters.tools import load_mcp_tools

# Load environment variables
load_dotenv()

def safe_serialize(obj):
    if isinstance(obj, list):
        return [safe_serialize(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: safe_serialize(v) for k, v in obj.items()}
    elif hasattr(obj, "dict"):
        return obj.dict()
    elif hasattr(obj, "__dict__"):
        return vars(obj)
    else:
        return str(obj)

async def main():
    model = ChatOpenAI(model="gpt-4o")

    server_params = StdioServerParameters(
        command="python",
        args=["/Users/gyliu513/github.com/gyliu513/langX101/langchain-mcp/quick-start/math_server.py"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await load_mcp_tools(session)
            print("Available Tools:")
            for tool in tools:
                print(f"- {tool.name}: {tool.description}")

            agent = create_react_agent(model, tools)
            agent_response = await agent.ainvoke({"messages": "what's (3 + 5) x 12?"})

            print("Agent Response (formatted):")
            print(json.dumps(safe_serialize(agent_response), indent=2))

if __name__ == "__main__":
    asyncio.run(main())
