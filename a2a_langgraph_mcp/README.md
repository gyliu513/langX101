# Hello Agents: A2A + LangGraph + MCP

A simplified multi-agent framework based on Google's Agent-to-Agent (A2A) protocol, LangGraph, and Model Context Protocol (MCP).

## Overview

This project demonstrates a simplified implementation of a multi-agent system where:

1. **MCP Server** acts as a registry for agent cards and tools
2. **Hello World Agent** provides simple greeting functionality using LangGraph
3. **Orchestrator Agent** coordinates between multiple agents using a workflow graph

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│                 │     │                 │
│   MCP Server    │◄────┤  Agent Cards    │
│                 │     │                 │
└────────┬────────┘     └─────────────────┘
         │
         │ Discovers
         ▼
┌─────────────────┐     ┌─────────────────┐
│                 │     │                 │
│  Orchestrator   │────►│  Hello World    │
│     Agent       │     │     Agent       │
│                 │     │                 │
└────────┬────────┘     └─────────────────┘
         │
         │ Responds
         ▼
┌─────────────────┐
│                 │
│     Client      │
│                 │
└─────────────────┘
```

## Prerequisites

- Python 3.9+
- Google API Key for Gemini models

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/hello_agents.git
   cd hello_agents
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install the package:
   ```bash
   pip install -e .
   ```

4. Set your Google API Key:
   ```bash
   export GOOGLE_API_KEY="your_api_key_here"
   ```

## Running the Application

You can run both the MCP server and API server with a single command:

```bash
python -m hello_agents
```

This will start:
- MCP Server on http://localhost:10000
- API Server on http://localhost:8000

### Running Components Separately

To run only the MCP server:

```bash
python -m hello_agents --mcp-only
```

To run only the API server:

```bash
python -m hello_agents --api-only
```

## API Endpoints

### REST API

- `GET /`: Root endpoint
- `POST /api/hello`: Hello World Agent endpoint
- `POST /api/orchestrator`: Orchestrator Agent endpoint

### WebSocket API

- `WS /ws/hello`: WebSocket endpoint for Hello World Agent
- `WS /ws/orchestrator`: WebSocket endpoint for Orchestrator Agent

## Example Usage

### Using the REST API

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

### Using the WebSocket API

```python
import asyncio
import websockets
import json

async def hello_agent():
    uri = "ws://localhost:8000/ws/hello"
    async with websockets.connect(uri) as websocket:
        await websocket.send(json.dumps({"query": "Charlie"}))
        response = await websocket.recv()
        print(json.loads(response))

asyncio.run(hello_agent())
```

## Project Structure

```
a2a_langgraph_mcp/
├── agent_cards/                # Agent card JSON files
│   ├── hello_agent.json
│   └── orchestrator_agent.json
├── src/
│   └── hello_agents/
│       ├── agents/             # Agent implementations
│       │   ├── hello_agent.py
│       │   └── orchestrator_agent.py
│       ├── common/             # Shared utilities
│       │   ├── base_agent.py
│       │   └── workflow.py
│       ├── mcp/                # MCP implementation
│       │   ├── client.py
│       │   └── server.py
│       ├── __init__.py
│       ├── __main__.py         # Entry point
│       └── api.py              # API server
├── pyproject.toml              # Project metadata
└── README.md                   # This file
```

## License

MIT