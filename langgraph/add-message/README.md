# LangGraph Add Message Demo

This is a demonstration of using LangGraph's message handling capabilities with OpenAI.

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
cd langgraph/add-message
uv pip install -e .
```

## Running the Demo

Run the script using uv:

```bash
uv run add-message.py
```

## How it Works

This script demonstrates a simple LangGraph workflow with message handling:

1. A user asks about the capital of France
2. The AI responds using OpenAI
3. The user asks a follow-up question about Germany
4. The AI responds again, with access to the full conversation history

The workflow uses LangGraph's `add_messages` annotation to properly accumulate messages in the state.

## Environment Variables

The following environment variables can be set in the `.env` file:

- `OPENAI_API_KEY`: Your OpenAI API key (required)
- `OPENAI_MODEL`: The OpenAI model to use (optional, defaults to "gpt-3.5-turbo")
- `TEMPERATURE`: The temperature setting for the model (optional, defaults to 0)
