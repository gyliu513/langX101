from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_google_genai import ChatGoogleGenerativeAI
import os
import json

# Create a simple weather tool using DuckDuckGo search
def get_weather(query: str) -> str:
    """Get weather information for a location"""
    search = DuckDuckGoSearchRun()
    result = search.run(f"weather in {query}")
    return result

# Initialize Google AI model
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("GOOGLE_API_KEY environment variable not set. Please set your Google API key.")

model = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=api_key,
    temperature=0
)

checkpointer = InMemorySaver()

agent = create_react_agent(
    model=model,
    tools=[get_weather],
    checkpointer=checkpointer  
)

# Run the agent
config = {"configurable": {"thread_id": "1"}}
sf_response = agent.invoke(
    {"messages": [{"role": "user", "content": "what is the weather in sf"}]},
    config  
)
ny_response = agent.invoke(
    {"messages": [{"role": "user", "content": "what about new york?"}]},
    config
)

def extract_final_response(response):
    """Extract the final AI response from the LangChain response object"""
    if hasattr(response, 'messages') and response.messages:
        # Get the last message which should be the AI response
        last_message = response.messages[-1]
        if hasattr(last_message, 'content'):
            return last_message.content
    return str(response)

def format_response_as_json(response_text):
    """Format the response text as a structured JSON object"""
    # Try to extract weather information and format it as JSON
    response_data = {
        "status": "success",
        "message": response_text,
        "timestamp": "2024-01-01T00:00:00Z"  # You could add actual timestamp
    }
    
    # If the response contains weather info, try to extract it
    if "weather" in response_text.lower():
        response_data["type"] = "weather_response"
        response_data["data"] = {
            "raw_response": response_text,
            "extracted_info": {
                "location": "unknown",
                "conditions": "unknown",
                "temperature": "unknown"
            }
        }
    else:
        response_data["type"] = "general_response"
        response_data["data"] = {
            "raw_response": response_text
        }
    
    return response_data

# Format responses as JSON
sf_response_text = extract_final_response(sf_response)
ny_response_text = extract_final_response(ny_response)

sf_json = {
    "query": "what is the weather in sf",
    "response": format_response_as_json(sf_response_text),
    "location": "San Francisco"
}

ny_json = {
    "query": "what about new york?",
    "response": format_response_as_json(ny_response_text),
    "location": "New York"
}

# Print in JSON format
print("\n" + "="*60)
print("🌤️  WEATHER RESPONSES (JSON FORMAT)")
print("="*60)
print(json.dumps(sf_json, indent=2))
print("\n" + "-"*60)
print(json.dumps(ny_json, indent=2))
print("\n" + "="*60)
