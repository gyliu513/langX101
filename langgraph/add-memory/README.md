# LangGraph In-Memory Saver Demo

This demo shows how to use LangGraph with in-memory checkpointing to maintain conversation state across multiple interactions using Google AI (Gemini).

## Setup

Make sure you have `uv` installed and a Google API key set in your environment:

```bash
export GOOGLE_API_KEY="your-google-api-key-here"
```

You can get your Google API key from: https://makersuite.google.com/app/apikey

## Running the Program

Use `uv run` to execute the program:

```bash
uv run in-memory-saver.py
```

## What it does

The program demonstrates:
1. Creating a LangGraph agent with in-memory checkpointing
2. Running multiple interactions with the same thread ID
3. Maintaining conversation context across calls

The agent will ask about weather in San Francisco and then New York, showing how the conversation state is preserved. 