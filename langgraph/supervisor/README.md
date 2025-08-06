# LangGraph Supervisor with OpenAI API

This is a LangGraph example that demonstrates a supervisor pattern with OpenAI's GPT API. The supervisor routes user messages to different specialized agents based on the content.

## Features

- **Supervisor Pattern**: A central supervisor that decides which agent should handle each user message
- **Specialized Agents**: 
  - `agent_1`: Handles general conversations and casual questions
  - `agent_2`: Handles technical and programming questions
- **OpenAI Integration**: Uses OpenAI's GPT-3.5 Turbo model
- **Interactive CLI**: Simple command-line interface for testing

## Setup

### 1. Install Dependencies

```bash
cd langgraph/supervisor
uv sync
```

### 2. Set up OpenAI API Key

You need an OpenAI API key to use the GPT API. Get one from [OpenAI Platform](https://platform.openai.com/api-keys).

Set the environment variable:

```bash
export OPENAI_API_KEY="your-api-key-here"
```

Or create a `.env` file in the supervisor directory:

```
OPENAI_API_KEY=your-api-key-here
```

### 3. Run the Application

```bash
uv run main.py
```

## Usage

Once running, you can interact with the system:

- Ask general questions (handled by agent_1)
- Ask technical/programming questions (handled by agent_2)
- Type 'quit', 'exit', or 'bye' to end the conversation

### Example Interactions

```
You: Hello, how are you?
Assistant: Hello! I'm doing well, thank you for asking. How can I help you today?

You: How do I write a Python function?
Assistant: To write a Python function, you use the `def` keyword followed by the function name and parameters in parentheses. Here's a basic example:

def greet(name):
    return f"Hello, {name}!"

You can call it with: greet("Alice")
```

## Architecture

The application uses a LangGraph with three nodes:

1. **Supervisor**: Analyzes user messages and routes to appropriate agents
2. **Agent 1**: Handles general conversations
3. **Agent 2**: Handles technical/programming questions

The supervisor makes routing decisions based on the content of user messages, ensuring each query is handled by the most appropriate specialized agent.

## Dependencies

- `langgraph`: For building the agent workflow
- `langchain`: Core LangChain functionality
- `langchain-openai`: OpenAI integration
- `python-dotenv`: Environment variable management 