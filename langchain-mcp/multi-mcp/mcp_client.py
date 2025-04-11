
import asyncio
import json
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from mcp import ClientSession, StdioServerParameters
from langchain_mcp_adapters.client import MultiServerMCPClient
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

    async with MultiServerMCPClient(
        {
            "math": {
                "command": "python",
                # Make sure to update to the full absolute path to your math_server.py file
                "args": ["/Users/gyliu513/github.com/gyliu513/langX101/langchain-mcp/quick-start/math_server.py"],
                "transport": "stdio",
            },
            "weather": {
                # make sure you start your weather server on port 8000
                "url": "http://localhost:8000/sse",
                "transport": "sse",
            }
        }
    ) as client:
        agent = create_react_agent(model, client.get_tools())
        math_response = await agent.ainvoke({"messages": "what's (3 + 5) x 12?"})
        weather_response = await agent.ainvoke({"messages": "what is the weather in nyc?"})

        print("Math Agent Response (formatted):")
        print(json.dumps(safe_serialize(math_response), indent=2))
        
        print("Weather Agent Response (formatted):")
        print(json.dumps(safe_serialize(weather_response), indent=2))

if __name__ == "__main__":
    asyncio.run(main())
