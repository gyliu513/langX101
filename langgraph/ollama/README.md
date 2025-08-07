# LangGraph Multi-Agent System with Ollama

This is a multi-agent system built with LangGraph that uses local Ollama for language model inference and embeddings.

## Features

- **Multi-Agent Coordination**: Automatically selects the most appropriate agent(s) for user queries using embedding-based similarity
- **Local Inference**: Uses Ollama for both language model inference and embeddings
- **Specialized Agents**: 
  - General Conversation Agent
  - Technical Support Agent
  - Creative Writing Agent
  - Business Consultant Agent
  - Health & Wellness Agent

## Prerequisites

1. **Install Ollama**: Follow the instructions at [ollama.ai](https://ollama.ai)
2. **Install uv**: Follow the instructions at [astral.sh/uv](https://astral.sh/uv)

## Setup

1. **Start Ollama**:
   ```bash
   ollama serve
   ```

2. **Pull a model** (if you haven't already):
   ```bash
   ollama pull llama2
   ```

3. **Run the application**:
   ```bash
   uv run main.py
   ```

## Configuration

You can modify the model used by changing the `model` parameter in the code:

```python
model = Ollama(
    model="llama2",  # Change this to any model you have in Ollama
    base_url="http://localhost:11434",
    temperature=0.1
)
```

Available models include:
- `llama2` (currently configured)
- `llama2:13b`
- `llama2:70b`
- `codellama`
- `mistral`
- `neural-chat`
- `gpt-oss:20b`
- And many more available at [ollama.ai/library](https://ollama.ai/library)

## Usage

The system will automatically:
1. Analyze your query using embeddings
2. Select the most appropriate agent(s) based on similarity
3. Generate responses using your local Ollama instance
4. For complex queries, coordinate multiple agents for comprehensive responses

## Example Queries

- **Single Agent**: "Tell me a joke" (General Conversation)
- **Multi-Agent**: "I want to start a tech business and need help with both business strategy and technical implementation"

## Troubleshooting

- **Connection Error**: Make sure Ollama is running with `ollama serve`
- **Model Not Found**: Pull the model with `ollama pull <model-name>`
- **Slow Responses**: Consider using a smaller model or adjusting the temperature parameter 