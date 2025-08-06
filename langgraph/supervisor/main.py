import os
from typing import Literal
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.types import Command

# Load environment variables
load_dotenv()

# Initialize OpenAI model
model = ChatOpenAI(
    model="gpt-3.5-turbo",
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0.1
)

def supervisor(state: MessagesState) -> Command[Literal["agent_1", "agent_2", END]]:
    """Supervisor that decides which agent to call next or to end the conversation."""
    
    print("\n🔍 SUPERVISOR: Analyzing user message...")
    
    # Get the last message from the conversation
    messages = state["messages"]
    last_message = messages[-1].content if messages else "Hello, how can I help you?"
    
    print(f"📝 SUPERVISOR: User message: '{last_message}'")
    
    # Create a system prompt for the supervisor
    system_prompt = """You are a supervisor that decides which agent to call next.
    
    Available agents:
    - agent_1: Handles general questions and conversations
    - agent_2: Handles technical and programming questions
    
    Based on the user's message, decide which agent should handle it:
    - If it's a general question or casual conversation, return "agent_1"
    - If it's a technical question, programming, or code-related, return "agent_2"
    - If the user wants to end the conversation, return "__end__"
    
    Respond with only the agent name or "__end__"."""
    
    # Create messages for the model
    model_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"User message: {last_message}\n\nWhich agent should handle this?")
    ]
    
    # Get the supervisor's decision
    try:
        response = model.invoke(model_messages)
        decision = response.content.strip().lower()
        print(f"🤖 SUPERVISOR: AI decision: '{decision}'")
    except Exception as e:
        print(f"❌ SUPERVISOR: Error calling OpenAI API: {e}")
        print("Please check your API key and billing status.")
        return Command(goto=END)
    
    # Map the decision to the appropriate agent or end
    if decision == "agent_1":
        print("✅ SUPERVISOR: Routing to Agent 1 (General Conversation)")
        return Command(goto="agent_1")
    elif decision == "agent_2":
        print("✅ SUPERVISOR: Routing to Agent 2 (Technical/Programming)")
        return Command(goto="agent_2")
    else:
        print("🛑 SUPERVISOR: Ending conversation")
        return Command(goto=END)

def agent_1(state: MessagesState) -> Command[Literal[END]]:
    """General conversation agent."""
    
    print("👤 AGENT 1: Starting general conversation processing...")
    
    messages = state["messages"]
    last_message = messages[-1].content if messages else "Hello!"
    
    print(f"📝 AGENT 1: Processing message: '{last_message}'")
    
    system_prompt = """You are a friendly general conversation agent. 
    Respond to the user in a helpful and engaging way. Keep responses concise and friendly."""
    
    model_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=last_message)
    ]
    
    try:
        print("🤖 AGENT 1: Calling OpenAI API...")
        response = model.invoke(model_messages)
        print("✅ AGENT 1: Response generated successfully")
        
        return Command(
            goto=END,
            update={"messages": [response]},
        )
    except Exception as e:
        print(f"❌ AGENT 1: Error calling OpenAI API: {e}")
        print("Please check your API key and billing status.")
        return Command(goto=END)

def agent_2(state: MessagesState) -> Command[Literal[END]]:
    """Technical and programming agent."""
    
    print("💻 AGENT 2: Starting technical/programming processing...")
    
    messages = state["messages"]
    last_message = messages[-1].content if messages else "Hello!"
    
    print(f"📝 AGENT 2: Processing message: '{last_message}'")
    
    system_prompt = """You are a technical and programming expert agent. 
    Help users with technical questions, programming problems, and code-related issues. 
    Provide clear, practical solutions and explanations."""
    
    model_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=last_message)
    ]
    
    try:
        print("🤖 AGENT 2: Calling OpenAI API...")
        response = model.invoke(model_messages)
        print("✅ AGENT 2: Response generated successfully")
        
        return Command(
            goto=END,
            update={"messages": [response]},
        )
    except Exception as e:
        print(f"❌ AGENT 2: Error calling OpenAI API: {e}")
        print("Please check your API key and billing status.")
        return Command(goto=END)

# Build the graph
builder = StateGraph(MessagesState)
builder.add_node("supervisor", supervisor)
builder.add_node("agent_1", agent_1)
builder.add_node("agent_2", agent_2)

# Add edges
builder.add_edge(START, "supervisor")
builder.add_edge("supervisor", "agent_1")
builder.add_edge("supervisor", "agent_2")
builder.add_edge("supervisor", END)
builder.add_edge("agent_1", END)
builder.add_edge("agent_2", END)

# Compile the graph
app = builder.compile()

if __name__ == "__main__":
    # Check if API key is set
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable is not set.")
        print("Please set your OpenAI API key:")
        print("export OPENAI_API_KEY='your-api-key-here'")
        exit(1)
    
    # Example usage
    print("LangGraph Supervisor with OpenAI API")
    print("Type 'quit' to exit")
    print("-" * 50)
    
    # Initialize the conversation
    config = {"configurable": {"thread_id": "default"}}
    
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ['quit', 'exit', 'bye']:
            print("Goodbye!")
            break
        
        # Run the graph
        result = app.invoke({"messages": [HumanMessage(content=user_input)]}, config)
        
        # Get the last response
        if result["messages"]:
            last_response = result["messages"][-1].content
            print(f"Assistant: {last_response}")
        else:
            print("Assistant: I'm sorry, I couldn't process that request.")