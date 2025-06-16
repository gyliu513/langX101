# Multi-Agent Framework with A2A, MCP, and LangGraph

## Description

This pull request adds a simplified multi-agent framework that combines three powerful technologies:

1. **Agent-to-Agent (A2A) Protocol**: For standardized agent communication
2. **Model Context Protocol (MCP)**: For agent discovery and tool registration
3. **LangGraph**: For creating structured agent workflows

## Features

- Simple MCP server implementation for agent and tool discovery
- Hello World agent built with LangGraph
- Orchestrator agent for coordinating between multiple agents
- Workflow graph system for managing agent execution
- REST and WebSocket APIs for interacting with agents
- Comprehensive documentation and blog post

## Implementation Details

The implementation includes:

- Base agent class that defines the common interface for all agents
- Workflow system for orchestrating agent tasks
- MCP server for agent discovery and tool registration
- Hello World agent using LangGraph for simple greeting functionality
- Orchestrator agent for coordinating between multiple agents
- API server for exposing agents via REST and WebSockets

## How to Use

1. Set your Google API Key:
   ```bash
   export GOOGLE_API_KEY="your_api_key_here"
   ```

2. Run the application:
   ```bash
   python -m hello_agents
   ```

3. Interact with the agents:
   ```python
   import requests
   
   # Hello World Agent
   response = requests.post(
       "http://localhost:8000/api/hello",
       json={"query": "Alice"}
   )
   print(response.json())
   
   # Orchestrator Agent
   response = requests.post(
       "http://localhost:8000/api/orchestrator",
       json={"query": "Say hello to Bob"}
   )
   print(response.json())
   ```

## Testing

The code has been manually tested to ensure:
- MCP server correctly loads and serves agent cards
- Hello World agent properly processes queries
- Orchestrator agent correctly coordinates between agents
- API endpoints work as expected

## Future Improvements

- Add more specialized agents
- Enhance the workflow with branching and parallel execution
- Improve agent discovery with embeddings
- Add authentication and security
- Implement full A2A protocol support

## References

- [Google A2A Protocol](https://github.com/google-a2a/a2a-samples)
- [Model Context Protocol](https://github.com/google/model-context-protocol)
- [LangGraph](https://github.com/langchain-ai/langgraph)