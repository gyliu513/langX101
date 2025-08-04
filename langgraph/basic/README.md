# LangGraph Basic Agent Demo

This is a simple demonstration of using LangGraph to create a basic ReAct agent with OpenAI.

## Setup

1. Make sure you have Python 3.9+ installed
2. Install uv if you don't have it already:
   ```
   pip install uv
   ```
3. Set up your OpenAI API key in the `.env` file:
   ```
   # Edit the .env file
   OPENAI_API_KEY=your_api_key_here
   ```
   Alternatively, you can set it as an environment variable:
   ```
   export OPENAI_API_KEY=your_api_key_here
   ```

## Installation

Install the dependencies using uv:

```bash
cd langgraph/basic
uv pip install -e .
```

## Running the Demo

Run the script using uv:

```bash
uv run basic-agent.py
```

## How it Works

This script demonstrates a simple LangGraph ReAct agent:

1. It creates a ReAct agent using the OpenAI model
2. The agent has access to a mock weather tool
3. It maintains conversation history using an InMemorySaver
4. It can answer follow-up questions using the conversation context

The script will:
1. Ask about the weather in New York
2. Ask a follow-up question about San Francisco
3. Display the responses in a formatted JSON output

## Environment Variables

The following environment variables can be set in the `.env` file:

- `OPENAI_API_KEY`: Your OpenAI API key (required)
- `OPENAI_MODEL`: The OpenAI model to use (optional, defaults to "gpt-3.5-turbo")
- `TEMPERATURE`: The temperature setting for the model (optional, defaults to 0)
