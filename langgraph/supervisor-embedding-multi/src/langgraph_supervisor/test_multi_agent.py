#!/usr/bin/env python3
"""
Test script for multi-agent functionality
"""

import os
from dotenv import load_dotenv
from langgraph_supervisor.main import agent_selector, AGENTS

# Load environment variables
load_dotenv()

def test_multi_agent_selection():
    """Test the multi-agent selection functionality"""
    
    print("🧪 Testing Multi-Agent Selection")
    print("=" * 50)
    
    # Test queries that should trigger multiple agents
    test_queries = [
        "I'm stressed about work and need both emotional support and career advice",
        "I want to start a tech business and need help with both business strategy and technical implementation",
        "Help me write a creative story about a health-conscious entrepreneur",
        "I need help with my Python code and also want to improve my business skills",
        "I'm feeling down and want to write a poem about it"
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n📝 Test {i}: '{query}'")
        print("-" * 40)
        
        # Test single agent selection (original method)
        single_agent = agent_selector.select_agent(query)
        print(f"Single agent selected: {AGENTS[single_agent]['name']}")
        
        # Test multi-agent selection (new method)
        multiple_agents = agent_selector.select_multiple_agents(query)
        print(f"Multi-agents selected ({len(multiple_agents)}):")
        for agent_id in multiple_agents:
            print(f"  • {AGENTS[agent_id]['name']}")
        
        print()

if __name__ == "__main__":
    # Check if API key is set
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable is not set.")
        print("Please set your OpenAI API key:")
        print("export OPENAI_API_KEY='your-api-key-here'")
        exit(1)
    
    test_multi_agent_selection()

# Made with Bob
