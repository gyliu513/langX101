from dotenv import load_dotenv
load_dotenv()

import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.chat_models import init_chat_model

async def main():
    model = init_chat_model("openai:gpt-4.1")

    client = MultiServerMCPClient(
        {
            "math": {
                "command": "python",
                "args": ["./examples/math_server.py"],
                "transport": "stdio",
            },
            "weather": {
                "url": "http://localhost:8000/mcp",
                "transport": "streamable_http",
            }
        }
    )

    tools = client.get_tools()

    def call_model(state: MessagesState):
        response = model.bind_tools(tools).invoke(state["messages"])
        return {"messages": response}

    builder = StateGraph(MessagesState)
    builder.add_node(call_model)
    builder.add_node(ToolNode(tools))
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", tools_condition)
    builder.add_edge("tools", "call_model")
    graph = builder.compile()


    math_response = await graph.ainvoke({"messages": "what's (3 + 5) x 12?"})
    print("Math response:", math_response)

    weather_response = await graph.ainvoke({"messages": "what is the weather in nyc?"})
    print("Weather response:", weather_response)

    # Save the graph structure as an image
    png_bytes = graph.get_graph().draw_mermaid_png()
    with open("/Users/gyliu513/gyliu513/langX101/langchain-mcp/multi-mcp/langgraph_structure.png", "wb") as f:
        f.write(png_bytes)
    print("Graph image saved to langgraph_structure.png")

asyncio.run(main())
