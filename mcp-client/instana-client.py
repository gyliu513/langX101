
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import asyncio
import os

load_dotenv()

model = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    max_tokens=10000,
    openai_api_key=os.getenv("OPENAI_API_KEY")
)

server_params = StdioServerParameters(
    command="/Users/gyliu513/bedrock/bin/uv",
    env={
        "INSTANA_BASE_URL": os.getenv("INSTANA_BASE_URL"),
        "INSTANA_API_TOKEN": os.getenv("INSTANA_API_TOKEN"),
    },
    args=["--directory", "/Users/gyliu513/github.com/instana/mcp-instana", "run", "src/mcp_server.py"]
)


def manage_message_history(messages, max_messages=6):
    """Keep only the most recent messages to prevent context length issues"""
    if len(messages) > max_messages:
        # Keep system message and the most recent messages
        system_message = messages[0]
        recent_messages = messages[-max_messages+1:]
        return [system_message] + recent_messages
    return messages


async def main():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            agent = create_react_agent(model, tools)

            messages = [
                {
                    "role": "system",
                    "content": "You are an IBM Instana expert. You are given a question about IBM Instana. You will use the tools provided to answer the question. You will think step by step and use the appropriate tools to help the user. Use emojis frequently to make your responses more engaging and friendly! 🚀✨. Keep responses concise."
                }
            ]

            print("🛠️ Available Tools -", *[tool.name for tool in tools])
            print("-" * 60)

            while True:
                user_input = input("\n👤 You: ")
                if user_input.lower() in ["quit", "exit", "bye"]:
                    print("👋 Goodbye! Have a great day! ✨")
                    break

                # Limit user input to prevent context issues
                user_input = user_input[:2000]  # Much smaller limit
                messages.append({"role": "user", "content": user_input})
                
                try:
                    print("🔄 Processing query...")
                    agent_response = await agent.ainvoke({"messages": messages})

                    # Check if any tools were used
                    tool_used = False
                    for msg in agent_response.get("messages", []):
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            for tool_call in msg.tool_calls:
                                tool_name = tool_call.get('name', 'Unknown')
                                print(f"🔧 Using Firecrawl tool: {tool_name}")
                                tool_used = True
                    
                    if not tool_used:
                        print("📝 No Instana tools used in this response")

                    ai_message = agent_response["messages"][-1].content
                    print("\n🤖 Agent:", ai_message)    
                    
                except Exception as e:
                    print("❌ Error:", e)
                    # Remove the last user message if it caused an error
                    if messages and messages[-1]["role"] == "user":
                        messages.pop()


if __name__ == "__main__":
    asyncio.run(main())
