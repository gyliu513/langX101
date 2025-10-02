# Agent Orchestrator with Task Decomposition

This project combines task decomposition capabilities with agent selection to create a powerful workflow that:

1. Decomposes complex tasks into smaller, manageable steps
2. Selects the most appropriate agent for each step based on embeddings similarity
3. Executes each step with the selected agent
4. Reflects on the results and adjusts as needed

## Features

- **Task Decomposition**: Breaks down complex queries into manageable steps
- **Dynamic Agent Selection**: Uses embeddings to select the most appropriate agent for each step
- **Reflection and Replanning**: Evaluates results and replans if necessary
- **Local Execution**: Uses Ollama models for privacy and no API costs
- **Comprehensive Summary**: Generates a detailed summary of the workflow execution

## Installation

### Prerequisites

- Python 3.9+
- [Ollama](https://ollama.com/download) installed and running

### Setup

1. Install dependencies:

```bash
# Install base dependencies
uv pip install numpy langchain langchain-core langgraph python-dotenv requests

# Install Ollama support (recommended)
uv pip install langchain-ollama

# Or if you prefer to use langchain-community instead
uv pip install langchain-community
```

2. Make sure Ollama is running:

```bash
ollama serve
```

3. Pull the required model:

```bash
ollama pull llama3.1
```

## Usage

Run the agent orchestrator:

```bash
uv run main.py
```

The script will:
1. Take a complex query
2. Break it down into steps
3. Select the most appropriate agent for each step
4. Execute the steps
5. Generate a comprehensive summary

## Available Agents

- **General Conversation Agent**: For casual conversations and general questions
- **Technical Support Agent**: For programming and technical questions
- **Creative Writing Agent**: For storytelling and creative content
- **Business Consultant Agent**: For business strategy and professional advice
- **Health & Wellness Agent**: For health, fitness, and wellness guidance

## How It Works

1. **Planning Phase**: The LLM creates a detailed plan to solve the problem
2. **Agent Selection Phase**: For each step, the most appropriate agent is selected using embedding similarity
3. **Execution Phase**: The selected agent executes the current step
4. **Reflection Phase**: Results are evaluated to determine if they meet requirements
5. **Decision Phase**: Either continue with next steps or replan if results are not satisfactory
6. **Summary Phase**: A comprehensive summary of the workflow is generated

## Example

Input:
```
I want to create a personal finance tracking app. Help me understand what features it should have, how to implement it, and what technologies to use.
```

The system will:
1. Break this down into steps (feature planning, technology selection, implementation strategy, etc.)
2. Select appropriate agents for each step (business consultant for features, technical support for technologies, etc.)
3. Execute each step with the selected agent
4. Generate a comprehensive summary of the plan