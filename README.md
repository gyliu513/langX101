[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/gyliu513/langX101)
[![GitHub stars](https://img.shields.io/github/stars/gyliu513/langX101?style=social)](https://github.com/gyliu513/langX101)
[![License](https://img.shields.io/github/license/gyliu513/langX101)](LICENSE)

# langX101

A comprehensive repository for testing and exploring **GenAI Observability**, **AI Agent Frameworks**, **Model Context Protocol (MCP)**, and **Agent-to-Agent (A2A) Protocol** implementations.

## 🎯 Overview

This repository serves as a hands-on laboratory for experimenting with various generative AI tools, observability platforms, and integration patterns. It contains practical examples, tutorials, and implementations across multiple AI frameworks and monitoring solutions.

## 📁 Repository Structure

### 🤖 AI Agents & Multi-Agent Systems
| Directory | Description |
|-----------|-------------|
| `a2a/` | Agent-to-Agent (A2A) protocol implementations |
| `a2a_langgraph_mcp/` | LangGraph with MCP integration for multi-agent systems |
| `adk/` | Agent Development Kit with MCP server implementations |
| `swarm/` | OpenAI Swarm agent implementations |
| `oai-agent/` | OpenAI agent examples with function calling |
| `crew/` | CrewAI multi-agent orchestration examples |
| `langgraph/` | LangGraph stateful agent workflows |
| `agent-semantic-convention/` | OpenTelemetry semantic conventions for AI agents |

### 🔧 Model Context Protocol (MCP)
| Directory | Description |
|-----------|-------------|
| `mcp/` | Core MCP implementations (weather, email, tutorial servers) |
| `mcp-client/` | MCP client implementations |
| `mcp-go/` | Go-based MCP server and client examples |
| `oai-mcp/` | OpenAI integration with MCP (filesystem, SSE) |
| `langchain-mcp/` | LangChain integration with MCP servers |
| `fastmcp/` | FastMCP server implementations |

### 🦜 LangChain Ecosystem
| Directory | Description |
|-----------|-------------|
| `langchain/` | Comprehensive LangChain examples (callbacks, RAG, AutoGPT) |
| `langchainjs/` | LangChain JavaScript/TypeScript examples |
| `langgraph/` | LangGraph stateful workflows and agents |
| `langserve/` | LangServe server implementations |
| `langflow/` | LangFlow visual workflows and custom components |
| `langsmith/` | LangSmith evaluation and monitoring |
| `langfuse/` | LangFuse observability integration |

### 📊 Observability & Monitoring
| Directory | Description |
|-----------|-------------|
| `otel/` | **OpenTelemetry instrumentation** for AI frameworks |
| `traceloop/` | Traceloop SDK integration examples |
| `arize/` | Arize AI monitoring integration |
| `helicone/` | Helicone observability examples |
| `langtrace/` | LangTrace monitoring implementation |
| `llmonitor/` | LLM monitoring examples |
| `newrelic/` | New Relic AI monitoring |
| `promptlayer/` | PromptLayer integration |

#### OpenTelemetry (`otel/`) Includes:
- OpenAI auto-instrumentation
- LangChain instrumentation
- ChromaDB instrumentation
- WatsonX instrumentation
- Custom span and trace examples

### ☁️ Cloud Providers & Models
| Directory | Description |
|-----------|-------------|
| `aws/` | AWS Bedrock examples and model implementations |
| `watsonx/` | IBM WatsonX examples with RAG |
| `openai/` | OpenAI API examples and assistants |
| `deepseek/` | DeepSeek model implementations |
| `litellm/` | LiteLLM proxy examples |
| `llamastack/` | Meta Llama Stack implementations |

### 🗄️ Vector Databases & Memory
| Directory | Description |
|-----------|-------------|
| `milvus/` | Milvus vector database examples |
| `embedchain/` | Embedchain implementations |
| `mem0/` | Mem0 memory layer for AI agents |
| `postgres/` | PostgreSQL with pgvector examples |

### 🛡️ Security & Evaluation
| Directory | Description |
|-----------|-------------|
| `llmguard/` | LLM security and guardrails |
| `eval/` | Model evaluation frameworks |

### 🌐 Web & API Development
| Directory | Description |
|-----------|-------------|
| `graphql_instana/` | GraphQL with Instana monitoring |
| `graphql-example/` | GraphQL examples |
| `my_flask_graphql_app/` | Flask GraphQL application |
| `streamlit-test/` | Streamlit application examples |
| `drizzle-demo/` | Drizzle ORM demo |

### 🔧 Utilities & Tools
| Directory | Description |
|-----------|-------------|
| `python/` | Python utilities and decorators |
| `mylib/` | Custom library implementations |
| `autowrapt/` | Auto-wrapping utilities |
| `oauth/` | OAuth authentication examples |
| `cline/` | Cline AI coding assistant examples |
| `scira/` | Scira search integration |

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- Node.js (for TypeScript/JavaScript examples)
- Go (for Go examples)
- Docker (for some services)
- [uv](https://github.com/astral-sh/uv) (recommended for Python dependency management)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/gyliu513/langX101.git
cd langX101
```

2. Set up Python environment (using uv):
```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync
```

Or using pip:
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt  # if available in specific directory
```

3. Configure environment variables:
```bash
cp dot-env.txt .env
# Edit .env with your API keys
```

## 📚 Key Examples

### MCP Server Setup
Check out the MCP examples in `/mcp/` for setting up Model Context Protocol servers:
- Weather server implementation
- Email sending capabilities
- Multi-tool scenarios

### Agent-to-Agent (A2A) Communication
Explore the `/a2a/` and `/a2a_langgraph_mcp/` directories for:
- Agent orchestration patterns
- Multi-agent coordination
- MCP + A2A integration

### OpenTelemetry GenAI Observability
The `/otel/` directory contains comprehensive examples for:
- Auto-instrumentation of LLM calls
- Custom span attributes for AI operations
- Integration with various observability backends

### RAG Implementations
Find various RAG patterns:
- WatsonX RAG in `/watsonx/`
- LangChain RAG examples in `/langchain/`
- Llama Stack RAG in `/llamastack/`
- Vector database integrations

## 🔗 Related Resources

- [Model Context Protocol (MCP) Documentation](https://modelcontextprotocol.io/)
- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Traceloop OpenLLMetry](https://github.com/traceloop/openllmetry)

## 👤 Author

**Guangya Liu** - Senior Technical Staff Member at IBM

- OpenTelemetry GenAI Semantic Convention Maintainer
- Apache Mesos PMC Member & Committer
- IBM Master Inventor with 30+ patents
- [LinkedIn](https://www.linkedin.com/in/guangya-liu-ibm) | [GitHub](https://github.com/gyliu513) | [Medium](https://gyliu513.medium.com/)

## 🤝 Contributing

Contributions are welcome! Feel free to:
- Add new tool integrations
- Improve existing examples
- Share interesting use cases
- Report issues or suggestions

## 📄 License

This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.

## 🏷️ Tags

`genai` `observability` `mcp` `a2a` `langchain` `langgraph` `openai` `agents` `rag` `monitoring` `opentelemetry` `ai-agents` `multi-agent` `traceloop`
