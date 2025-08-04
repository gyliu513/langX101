from typing_extensions import TypedDict
from typing import Annotated
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage, HumanMessage, AnyMessage
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Get configuration from environment variables with defaults
openai_model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
temperature = float(os.getenv("TEMPERATURE", "0"))

# Check if OpenAI API key is set
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set. Please set your OpenAI API key.")

# Initialize OpenAI model
llm = ChatOpenAI(
    model=openai_model,
    temperature=temperature,
    api_key=api_key
)

# Define state structure
class GraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

# Node: User input
def user_node(state: GraphState) -> dict:
    return {
        "messages": [HumanMessage(content="What is the capital of France?")]
    }

# Node: AI response
def ai_node(state: GraphState) -> dict:
    # Get the last message from the state
    last_message = state["messages"][-1]
    
    # Use OpenAI to generate a response
    response = llm.invoke([last_message])
    
    return {
        "messages": [response]
    }

# Node: User follow-up question
def user_followup_node(state: GraphState) -> dict:
    return {
        "messages": [HumanMessage(content="And what about Germany?")]
    }

# Node: AI follow-up response
def ai_followup_node(state: GraphState) -> dict:
    # Get the conversation history
    messages = state["messages"]
    
    # Use OpenAI to generate a response based on the conversation history
    response = llm.invoke(messages)
    
    return {
        "messages": [response]
    }

def main():
    # Print configuration
    print(f"Using model: {openai_model}")
    print(f"Temperature: {temperature}")
    print("-" * 40)
    
    # Build state graph
    builder = StateGraph(GraphState)
    builder.add_node("user_node", user_node)
    builder.add_node("ai_node", ai_node)
    builder.add_node("user_followup", user_followup_node)
    builder.add_node("ai_followup", ai_followup_node)
    
    builder.set_entry_point("user_node")
    builder.add_edge("user_node", "ai_node")
    builder.add_edge("ai_node", "user_followup")
    builder.add_edge("user_followup", "ai_followup")
    
    graph = builder.compile()
    
    # Visualize the graph (if in interactive environment)
    try:
        from IPython.display import Image, display
        display(Image(graph.get_graph().draw_mermaid_png()))
    except ImportError:
        print("IPython not available. Skipping graph visualization.")
    except Exception as e:
        print(f"Could not display graph: {e}")
    
    # Execute the workflow
    final_state = graph.invoke({"messages": []})
    
    # Print the final messages content
    print("\n🧾 Final chat history:")
    for m in final_state["messages"]:
        role = "🧑 User" if isinstance(m, HumanMessage) else "🤖 AI"
        print(f"{role}: {m.content}")

if __name__ == "__main__":
    main()
