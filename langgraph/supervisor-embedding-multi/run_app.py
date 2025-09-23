#!/usr/bin/env python3
"""
Entry point script to run the multi-agent supervisor application
"""

import os
from dotenv import load_dotenv
from langgraph_supervisor.main import app, AGENTS, agent_selector
from langchain_core.messages import HumanMessage

# Load environment variables
load_dotenv()

def main():
    """Run the multi-agent supervisor application"""
    
    # Check if API key is set
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable is not set.")
        print("Please set your OpenAI API key:")
        print("export OPENAI_API_KEY='your-api-key-here'")
        exit(1)
    
    # Example usage
    print("🤖 LangGraph Supervisor with Multi-Agent Embedding-Based Selection")
    print("Available agents:")
    for agent_id, agent_info in AGENTS.items():
        print(f"  • {agent_info['name']}")
    print("\n💡 Multi-agent capability:")
    print(f"  • Similarity threshold: {agent_selector.similarity_threshold}")
    print(f"  • Max agents per request: {agent_selector.max_agents}")
    print("  • Complex requests will automatically engage multiple agents")
    print("\n💬 Example multi-agent queries:")
    print("  • 'I want to start a tech business and need help with both business strategy and technical implementation'")
    print("  • 'I'm stressed about work and need both emotional support and career advice'")
    print("  • 'Help me write a creative story about a health-conscious entrepreneur'")
    print("\nType 'quit' to exit")
    print("-" * 50)
    
    # Initialize the conversation
    config = {"configurable": {"thread_id": "default"}}
    
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ['quit', 'exit', 'bye']:
            print("Goodbye!")
            break
        
        # Run the graph with proper state initialization
        initial_state = {
            "messages": [HumanMessage(content=user_input)],
            "selected_agents": []
        }
        result = app.invoke(initial_state, config)
        
        # Get the last response
        if result["messages"]:
            last_response = result["messages"][-1].content
            print(f"Assistant: {last_response}")
        else:
            print("Assistant: I'm sorry, I couldn't process that request.")

if __name__ == "__main__":
    main()

# Made with Bob
