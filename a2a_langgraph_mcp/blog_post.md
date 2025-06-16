# Building a Multi-Agent System with A2A, MCP, and LangGraph

*A practical guide to creating a simple yet powerful multi-agent framework*

## Introduction

In the rapidly evolving landscape of AI, multi-agent systems are becoming increasingly important. They allow for complex tasks to be broken down and distributed among specialized agents, leading to more robust and scalable solutions. In this blog post, we'll explore how to build a simple multi-agent system that combines three powerful technologies:

1. **Agent-to-Agent (A2A) Protocol**: Google's standard for agent communication
2. **Model Context Protocol (MCP)**: A protocol for agent discovery and tool registration
3. **LangGraph**: A framework for building structured agent workflows

We'll create a "Hello World" example that demonstrates the core concepts while keeping the implementation simple and understandable.

## Understanding the Components

Before diving into the code, let's understand the key components of our system:

### Agent-to-Agent (A2A) Protocol

The A2A protocol, developed by Google, standardizes how agents communicate with each other. It defines:

- **Agent Cards**: JSON schemas that describe an agent's identity, capabilities, and endpoints
- **Message Formats**: Standardized formats for agent communication
- **Interaction Flows**: Patterns for how agents should interact

In our implementation, we'll use a simplified version of A2A concepts, focusing on agent cards and basic message formats.

### Model Context Protocol (MCP)

MCP provides a standard way for applications to discover, access, and utilize contextual information and tools. In our system, MCP serves as a registry for:

- **Agent Cards**: Storing and retrieving agent descriptions
- **Tools**: Registering and discovering available tools

### LangGraph

LangGraph is a framework for building structured, stateful agent workflows. It allows us to:

- Define nodes and edges in a computational graph
- Manage state between steps
- Create complex, multi-step reasoning processes

## System Architecture

Our multi-agent system has the following architecture:

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

1. The **MCP Server** loads agent cards and makes them discoverable
2. The **Orchestrator Agent** coordinates tasks between multiple agents
3. The **Hello World Agent** performs the actual greeting task
4. The **Client** interacts with the system through REST or WebSocket APIs

## Implementation

Let's walk through the key parts of our implementation:

### 1. Base Agent Class

We start with a base class that all agents will inherit from:

```python
class BaseAgent(BaseModel, ABC):
    """Base class for agents."""

    model_config = {
        'arbitrary_types_allowed': True,
        'extra': 'allow',
    }

    agent_name: str = Field(
        description='The name of the agent.',
    )

    description: str = Field(
        description="A brief description of the agent's purpose.",
    )

    content_types: list[str] = Field(description='Supported content types.')
    
    async def stream(self, query: str, context_id: str, task_id: str) -> AsyncIterable[Dict[str, Any]]:
        """Stream the agent's response."""
        raise NotImplementedError("Subclasses must implement this method")
```

This provides a common interface for all agents in our system.

### 2. Workflow System

The workflow system is the heart of our orchestration:

```python
class WorkflowNode:
    """Represents a single node in a workflow graph."""

    def __init__(
        self,
        task: str,
        node_key: str | None = None,
        node_label: str | None = None,
    ):
        self.id = str(uuid.uuid4())
        self.node_key = node_key
        self.node_label = node_label
        self.task = task
        self.results = None
        self.state = Status.READY
        self.agent = None

    # ... methods for executing the node ...


class WorkflowGraph:
    """Represents a graph of workflow nodes."""

    def __init__(self):
        self.graph = nx.DiGraph()
        self.nodes = {}
        self.latest_node = None
        self.state = Status.INITIALIZED
        self.paused_node_id = None

    # ... methods for managing the graph and executing workflows ...
```

This allows us to create directed graphs of agent tasks and execute them in the correct order.

### 3. MCP Server

Our MCP server provides endpoints for discovering agents and tools:

```python
class MCPServer:
    """Simple MCP server implementation."""
    
    def __init__(self, host="localhost", port=10000):
        self.host = host
        self.port = port
        self.app = FastAPI(title="Simple MCP Server")
        self.tools = []
        self.agent_cards = {}
        
        # ... setup routes and methods ...
    
    def register_tool(self, tool: Tool):
        """Register a tool with the MCP server."""
        self.tools.append(tool)
        logger.info(f"Registered tool: {tool.name}")
    
    def load_agent_cards(self):
        """Load agent cards from the specified directory."""
        # ... load agent cards from JSON files ...
```

### 4. Hello World Agent

Our Hello World agent uses LangGraph to process queries:

```python
class HelloWorldAgent(BaseAgent):
    """A simple Hello World agent using LangGraph."""
    
    def __init__(self):
        super().__init__(
            agent_name="HelloWorldAgent",
            description="A simple agent that greets users",
            content_types=["text", "text/plain"],
        )
        
        # Initialize the LLM
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            temperature=0,
        )
        
        # Create a simple graph
        self.graph = self._build_graph()
        
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        
        # Define the state schema
        class State(dict):
            messages: List
        
        # Define the nodes
        def greet(state: State) -> State:
            """Generate a greeting based on the input."""
            messages = state["messages"]
            response = self.llm.invoke(messages)
            return {"messages": messages + [response]}
        
        # Create the graph
        workflow = StateGraph(State)
        workflow.add_node("greet", greet)
        workflow.set_entry_point("greet")
        workflow.add_edge("greet", END)
        
        return workflow.compile()
```

### 5. Orchestrator Agent

The orchestrator coordinates between agents:

```python
class OrchestratorAgent(BaseAgent):
    """Orchestrator Agent that coordinates between multiple agents."""
    
    def __init__(self, mcp_host="localhost", mcp_port=10000):
        super().__init__(
            agent_name="OrchestratorAgent",
            description="Coordinates tasks between multiple agents",
            content_types=["text", "text/plain"],
        )
        
        self.mcp_client = get_client(host=mcp_host, port=mcp_port)
        self.graph = None
        self.results = []
        self.context_id = None
    
    # ... methods for managing the workflow and coordinating agents ...
```

## Running the System

To run the system, we've created a simple entry point:

```python
def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(description="A2A LangGraph MCP Demo")
    parser.add_argument("--mcp-host", default="localhost", help="MCP server host")
    parser.add_argument("--mcp-port", type=int, default=10000, help="MCP server port")
    parser.add_argument("--api-host", default="0.0.0.0", help="API server host")
    parser.add_argument("--api-port", type=int, default=8000, help="API server port")
    parser.add_argument("--mcp-only", action="store_true", help="Run only the MCP server")
    parser.add_argument("--api-only", action="store_true", help="Run only the API server")
    
    args = parser.parse_args()
    
    # ... start the servers ...
```

This allows us to start both the MCP server and API server with a single command.

## Interacting with the System

Once the system is running, you can interact with it through REST API or WebSockets:

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

## Extending the System

This simple implementation can be extended in several ways:

1. **Add more agents**: Create specialized agents for different tasks
2. **Enhance the workflow**: Add branching, parallel execution, and error handling
3. **Improve agent discovery**: Use embeddings for semantic agent discovery
4. **Add authentication**: Secure the API and agent communication
5. **Implement full A2A protocol**: Support all A2A message types and interaction patterns

## Conclusion

Building a multi-agent system doesn't have to be complex. By combining A2A, MCP, and LangGraph, we've created a simple yet powerful framework that demonstrates the core concepts of multi-agent systems. This approach provides a solid foundation that can be extended and enhanced as needed.

The full code for this project is available on GitHub, and we encourage you to experiment with it, extend it, and adapt it to your own use cases.

Happy coding!

---

*Note: This implementation is a simplified version of the concepts and is intended for educational purposes. For production use, consider using more robust implementations of A2A and MCP.*