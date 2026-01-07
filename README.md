[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/gyliu513/langX101)

# langX101

A comprehensive repository for testing and exploring GenAI Observability Tools, AI Frameworks, and Model Context Protocol (MCP) implementations.

## 🎯 Overview

This repository serves as a hands-on laboratory for experimenting with various generative AI tools, observability platforms, and integration patterns. It contains practical examples, tutorials, and implementations across multiple AI frameworks and monitoring solutions.

## 📁 Repository Structure

### 🤖 AI Agents & Workflows
- **`a2a/`** - Agent-to-agent communication examples
- **`a2a_langgraph_mcp/`** - LangGraph with MCP integration for multi-agent systems
- **`adk/`** - Agent Development Kit with MCP server implementations
- **`swarm/`** - AI agent swarm implementations
- **`oai-agent/`** - OpenAI agent examples with function calling

### 🔧 Model Context Protocol (MCP)
- **`mcp/`** - Core MCP implementations including weather, email, and tutorial servers
- **`mcp-client/`** - MCP client implementations
- **`mcp-go/`** - Go-based MCP server and client examples
- **`oai-mcp/`** - OpenAI integration with MCP (filesystem and SSE examples)
- **`langchain-mcp/`** - LangChain integration with MCP servers
- **`fastmcp/`** - Fast MCP server implementations

### 🦜 LangChain Ecosystem
- **`langchain/`** - Comprehensive LangChain examples including callbacks, RAG, and AutoGPT
- **`langserve/`** - LangServe server implementations
- **`langflow/`** - LangFlow workflows and custom components
- **`langsmith/`** - LangSmith evaluation and monitoring examples
- **`langfuse/`** - LangFuse observability integration

### 📊 Observability & Monitoring
- **`otel/`** - OpenTelemetry instrumentation for various AI frameworks
  - OpenAI instrumentation
  - LangChain instrumentation  
  - ChromaDB instrumentation
  - WatsonX instrumentation
- **`arize/`** - Arize AI monitoring integration
- **`helicone/`** - Helicone observability examples
- **`langtrace/`** - LangTrace monitoring implementation
- **`llmonitor/`** - LLM monitoring examples
- **`newrelic/`** - New Relic AI monitoring
- **`promptlayer/`** - PromptLayer integration

### ☁️ Cloud Providers & Models
- **`aws/`** - AWS Bedrock examples and model implementations
- **`watsonx/`** - IBM WatsonX examples with RAG implementations
- **`openai/`** - OpenAI API examples and assistants
- **`deepseek/`** - DeepSeek model implementations
- **`litellm/`** - LiteLLM proxy examples

### 🛡️ Security & Evaluation
- **`llmguard/`** - LLM security and guardrails
- **`eval/`** - Model evaluation frameworks and examples

### 🗄️ Vector Databases & Storage
- **`milvus/`** - Milvus vector database examples
- **`embedchain/`** - Embedchain implementations

### 🌐 Web & API Development
- **`graphql_instana/`** - GraphQL with Instana monitoring
- **`my_flask_graphql_app/`** - Flask GraphQL application
- **`streamlit-test/`** - Streamlit application examples

### 🔄 AI Frameworks & Tools
- **`crew/`** - CrewAI multi-agent examples
- **`haystack/`** - Haystack RAG implementations
- **`react/`** - ReAct pattern implementations
- **`python/`** - Python utilities and decorators

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- Node.js (for TypeScript/JavaScript examples)
- Go (for Go examples)
- Docker (for some services)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/gyliu513/langX101.git
cd langX101
```

2. Set up Python environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies for specific examples as needed (each directory may have its own requirements).

## 📚 Key Examples

### MCP Server Setup
Check out the MCP examples in `/mcp/` for setting up Model Context Protocol servers:
- Weather server implementation
- Email sending capabilities
- Tutorial and learning examples

### Observability Integration
Explore comprehensive observability setups:
- OpenTelemetry auto-instrumentation in `/otel/openai-auto/`
- LangFuse integration in `/langfuse/`
- Multi-tool monitoring comparisons

### Agent Workflows
See advanced agent implementations:
- Multi-agent systems in `/a2a_langgraph_mcp/`
- Agent orchestration patterns
- Function calling and tool usage

### RAG Implementations
Find various RAG patterns:
- WatsonX RAG in `/watsonx/`
- LangChain RAG examples
- Vector database integrations

## 🔗 Related Resources

- [Model Context Protocol Documentation](https://modelcontextprotocol.io/)
- [LangChain Documentation](https://python.langchain.com/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)

## 🤝 Contributing

This repository is primarily for testing and experimentation. Feel free to:
- Add new tool integrations
- Improve existing examples
- Share interesting use cases
- Report issues or suggestions

## 📄 License

See [LICENSE](LICENSE) file for details.

## 🏷️ Tags

`genai` `observability` `mcp` `langchain` `openai` `agents` `rag` `monitoring` `opentelemetry` `ai-tools`
