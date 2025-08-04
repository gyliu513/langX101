from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os
import json

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
model = ChatOpenAI(
    model=openai_model,
    temperature=temperature,
    api_key=api_key
)

# Define a simple tool
def get_current_weather(location: str) -> str:
    """Get the current weather in a given location"""
    # This is a mock function - in a real app, you would call a weather API
    weather_data = {
        "New York": {"temperature": "72°F", "conditions": "Sunny"},
        "San Francisco": {"temperature": "65°F", "conditions": "Foggy"},
        "London": {"temperature": "60°F", "conditions": "Rainy"},
        "Tokyo": {"temperature": "80°F", "conditions": "Clear"},
    }
    
    # Default response for unknown locations
    default_weather = {"temperature": "70°F", "conditions": "Partly cloudy"}
    
    # Get weather for the location (case insensitive)
    for city, data in weather_data.items():
        if city.lower() in location.lower():
            return f"Weather in {city}: {data['temperature']}, {data['conditions']}"
    
    return f"Weather in {location}: {default_weather['temperature']}, {default_weather['conditions']}"

# Create an in-memory saver for conversation history
from langgraph.checkpoint.memory import InMemorySaver
checkpointer = InMemorySaver()

# Create the agent
agent = create_react_agent(
    model=model,
    tools=[get_current_weather],
    checkpointer=checkpointer
)

# Visualize the graph
print("Generating graph visualizations...")

# For Jupyter or GUI environments:
try:
    from IPython.display import Image, display
    display(Image(agent.get_graph().draw_mermaid_png()))
    print("Graph displayed in Jupyter/IPython environment.")
except ImportError:
    print("IPython not available. Skipping interactive display.")
except Exception as e:
    print(f"Error displaying graph: {e}")

# To save PNG to file:
try:
    png_data = agent.get_graph().draw_mermaid_png()
    with open("graph.png", "wb") as f:
        f.write(png_data)
    print("Graph saved to graph.png")
except Exception as e:
    print(f"Error saving graph to file: {e}")

# For terminal/ASCII output:
try:
    print("\nASCII Graph Representation:")
    print(agent.get_graph().draw_ascii())
except ImportError:
    print("\nCould not draw ASCII graph. Make sure 'grandalf' is installed.")
    print("Try: pip install grandalf")
except Exception as e:
    print(f"\nError drawing ASCII graph: {e}")

def extract_final_response(response):
    """Extract the final AI response from the LangChain response object"""
    if hasattr(response, 'messages') and response.messages:
        # Get the last message which should be the AI response
        last_message = response.messages[-1]
        if hasattr(last_message, 'content'):
            return last_message.content
    return str(response)

def main():
    # Print configuration
    print(f"\nUsing model: {openai_model}")
    print(f"Temperature: {temperature}")
    print("-" * 40)
    
    # Run the agent with a thread ID for conversation history
    config = {"configurable": {"thread_id": "weather_thread"}}
    
    # First query
    print("\nAsking about weather in New York...")
    ny_response = agent.invoke(
        {"messages": [{"role": "user", "content": "What's the weather like in New York?"}]},
        config
    )
    ny_text = extract_final_response(ny_response)
    print(f"Response: {ny_text}")
    
    # Follow-up query (using the same thread_id to maintain conversation history)
    print("\nAsking about weather in San Francisco...")
    sf_response = agent.invoke(
        {"messages": [{"role": "user", "content": "How about in San Francisco?"}]},
        config
    )
    sf_text = extract_final_response(sf_response)
    print(f"Response: {sf_text}")
    
    # Format responses as JSON
    responses = {
        "new_york": {
            "query": "What's the weather like in New York?",
            "response": ny_text
        },
        "san_francisco": {
            "query": "How about in San Francisco?",
            "response": sf_text
        }
    }
    
    # Print JSON output
    print("\n" + "="*60)
    print("🌤️  WEATHER RESPONSES (JSON FORMAT)")
    print("="*60)
    print(json.dumps(responses, indent=2))
    print("="*60)

if __name__ == "__main__":
    main()
