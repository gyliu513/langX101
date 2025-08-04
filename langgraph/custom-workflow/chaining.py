from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from IPython.display import Image, display
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get configuration from environment variables with defaults
openai_model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
temperature = float(os.getenv("TEMPERATURE", "0.7"))

# Initialize OpenAI model
llm = ChatOpenAI(
    model=openai_model,
    temperature=temperature,
    api_key=os.getenv("OPENAI_API_KEY")
)

# Graph state
class State(TypedDict):
    topic: str
    joke: str
    improved_joke: str
    final_joke: str


# Nodes
def generate_joke(state: State):
    """First LLM call to generate initial joke"""
    msg = llm.invoke([HumanMessage(content=f"Write a short joke about {state['topic']}")])
    return {"joke": msg.content}


def check_punchline(state: State):
    """Gate function to check if the joke has a punchline"""
    # Debug print to see what's in the joke
    print(f"Checking joke: '{state['joke']}'")
    
    # Check if the joke contains a question mark or exclamation mark
    has_punchline = "?" in state["joke"] or "!" in state["joke"]
    
    print(f"Has punchline: {has_punchline}")
    
    if has_punchline:
        return "Pass"
    return "Fail"


def improve_joke(state: State):
    """Second LLM call to improve the joke"""
    msg = llm.invoke([HumanMessage(content=f"Make this joke funnier by adding wordplay: {state['joke']}")])
    return {"improved_joke": msg.content}


def polish_joke(state: State):
    """Third LLM call for final polish"""
    msg = llm.invoke([HumanMessage(content=f"Add a surprising twist to this joke: {state['improved_joke']}")])
    return {"final_joke": msg.content}


def main():
    # Print configuration
    print(f"Using model: {openai_model}")
    print(f"Temperature: {temperature}")
    print("-" * 40)
    
    # Build workflow
    workflow = StateGraph(State)

    # Add nodes
    workflow.add_node("generate_joke", generate_joke)
    workflow.add_node("improve_joke", improve_joke)
    workflow.add_node("polish_joke", polish_joke)

    # Add edges to connect nodes
    workflow.add_edge(START, "generate_joke")
    workflow.add_conditional_edges(
        "generate_joke", check_punchline, {"Fail": "improve_joke", "Pass": END}
    )
    workflow.add_edge("improve_joke", "polish_joke")
    workflow.add_edge("polish_joke", END)

    # Compile
    chain = workflow.compile()

    # Show workflow (only if in interactive environment)
    try:
        display(Image(chain.get_graph().draw_mermaid_png()))
    except:
        print("Running in non-interactive environment. Skipping graph visualization.")

    # Invoke
    topic = input("Enter a topic for a joke: ")
    state = chain.invoke({"topic": topic})
    
    print("\nInitial joke:")
    print(state["joke"])
    print("\n--- --- ---\n")
    
    if "improved_joke" in state:
        print("Improved joke:")
        print(state["improved_joke"])
        print("\n--- --- ---\n")

        print("Final joke:")
        print(state["final_joke"])
    else:
        print("Joke passed quality gate - no improvement needed!")


if __name__ == "__main__":
    # Check if OpenAI API key is set
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Please set your OpenAI API key in a .env file or as an environment variable.")
        print("Example .env file content: OPENAI_API_KEY=your_api_key_here")
        exit(1)
    
    main()

# Made with Bob
