# LangGraph Supervisor with Multi-Agent Embedding-Based Selection

This package demonstrates a LangGraph supervisor that uses embeddings to select the most appropriate agent(s) for a user query.

## Features

- Embedding-based agent selection
- Multi-agent coordination for complex queries
- Five specialized agents:
  - General Conversation Agent
  - Technical Support Agent
  - Creative Writing Agent
  - Business Consultant Agent
  - Health & Wellness Agent

## Installation

This package uses a src-layout structure. To install it in development mode:

```bash
# Navigate to the package directory
cd langgraph/supervisor-embedding-multi

# Install in development mode
uv pip install -e .
```

## Usage

### Running the Test Script

To run the test script that demonstrates multi-agent selection:

```bash
# Method 1: Using the run_test.py script
python run_test.py

# Method 2: Using the module directly
python -m langgraph_supervisor.test_multi_agent
```

### Using the Package in Your Code

```python
from langgraph_supervisor import app, AGENTS, agent_selector

# Initialize the conversation
config = {"configurable": {"thread_id": "default"}}

# Example user query
user_input = "I want to start a tech business and need help with both business strategy and technical implementation"

# Run the graph with proper state initialization
from langchain_core.messages import HumanMessage

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
```

## Project Structure

```
langgraph/supervisor-embedding-multi/
├── pyproject.toml
├── README.md
├── run_test.py
├── src/
│   └── langgraph_supervisor/
│       ├── __init__.py
│       ├── main.py
│       └── test_multi_agent.py
```

## Requirements

- Python 3.9+
- OpenAI API key (set as environment variable `OPENAI_API_KEY`)
- Dependencies listed in pyproject.toml