# LangGraph Custom Workflow Demo

This is a simple demonstration of using LangGraph to create a custom workflow for joke generation using OpenAI.

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
cd langgraph/custom-workflow
uv pip install -e .
```

## Running the Demo

Run the script using uv:

```bash
uv run python chaining.py
```

## How it Works

This script demonstrates a simple LangGraph workflow:

1. Generate an initial joke about a user-provided topic
2. Check if the joke has a punchline (contains "?" or "!")
3. If it doesn't have a punchline, improve the joke by adding wordplay
4. Polish the joke by adding a surprising twist
5. Output the final joke

The workflow uses conditional branching to determine whether the joke needs improvement.

## Environment Variables

The following environment variables can be set in the `.env` file:

- `OPENAI_API_KEY`: Your OpenAI API key (required)
- `OPENAI_MODEL`: The OpenAI model to use (optional, defaults to "gpt-3.5-turbo")
- `TEMPERATURE`: The temperature setting for the model (optional, defaults to 0.7)

// Made with Bob
