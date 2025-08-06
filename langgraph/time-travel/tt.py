import os
import uuid
from dotenv import load_dotenv

from typing_extensions import TypedDict, NotRequired
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver

# Load environment variables
load_dotenv()

class State(TypedDict):
    topic: NotRequired[str]
    joke: NotRequired[str]


# Initialize Google Gemini model
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY"),
)


def generate_topic(state: State):
    """LLM call to generate a topic for the joke"""
    msg = llm.invoke("Give me a funny topic for a joke")
    return {"topic": msg.content}


def write_joke(state: State):
    """LLM call to write a joke based on the topic"""
    msg = llm.invoke(f"Write a short joke about {state['topic']}")
    return {"joke": msg.content}


# Build workflow
workflow = StateGraph(State)

# Add nodes
workflow.add_node("generate_topic", generate_topic)
workflow.add_node("write_joke", write_joke)

# Add edges to connect nodes
workflow.add_edge(START, "generate_topic")
workflow.add_edge("generate_topic", "write_joke")
workflow.add_edge("write_joke", END)

# Compile
checkpointer = InMemorySaver()
graph = workflow.compile(checkpointer=checkpointer)

# Draw the graph
graph.get_graph().draw_mermaid_png()

# Run the workflow
if __name__ == "__main__":
    # Check if API key is set
    if not os.getenv("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY environment variable is not set.")
        print("Please set your Google API key in a .env file or as an environment variable.")
        exit(1)
    
    # Execute the workflow with proper configuration (using thread_id)
    config = {
        "configurable": {
            "thread_id": str(uuid.uuid4()),
        }
    }
    
    print("=== Running Initial Workflow ===")
    state = graph.invoke({}, config)
    print(f"Generated topic: {state['topic']}")
    print(f"Generated joke: {state['joke']}")
    
    print("\n=== State History ===")
    # The states are returned in reverse chronological order.
    states = list(graph.get_state_history(config))
    
    for i, state_obj in enumerate(states):
        print(f"\nState {i}:")
        print(f"  Next: {state_obj.next}")
        print(f"  Checkpoint ID: {state_obj.config['configurable']['checkpoint_id']}")
        print(f"  Values: {state_obj.values}")
    
    # Demonstrate time-travel by selecting a previous state and modifying it
    if len(states) > 1:
        print("\n=== Time Travel Demo ===")
        # Select the state before the last one (which should be after generate_topic)
        selected_state = states[1]
        print(f"Selected state - Next: {selected_state.next}")
        print(f"Selected state - Values: {selected_state.values}")
        
        # Update the state with a new topic
        print("\n=== Updating State ===")
        new_config = graph.update_state(
            selected_state.config, 
            values={"topic": "programmers"}
        )
        print(f"New config: {new_config}")
        
        # Resume execution from the checkpoint
        print("\n=== Resuming from Checkpoint ===")
        new_result = graph.invoke(None, new_config)
        print(f"New topic: {new_result['topic']}")
        print(f"New joke: {new_result['joke']}")