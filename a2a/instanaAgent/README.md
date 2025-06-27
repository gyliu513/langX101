# Instana Agent - Monitoring & Observability Operations

This agent allows you to interact with Instana monitoring platform via natural language using LangGraph and the Instana MCP server. It supports HTTP MCP transport mode for reliable communication with the mcp-instana server running in HTTP mode.

## ✨ Key Features

### 📊 Monitoring & Observability Operations
- **Event Analysis**: Retrieve and analyze application and infrastructure events
- **Alert Management**: Monitor alerts and alert configurations
- **Performance Metrics**: Access application and infrastructure performance data
- **Resource Monitoring**: Monitor Kubernetes clusters and infrastructure resources

### 🤖 Advanced AI Capabilities
- **Natural Language Interface**: Interact with Instana using plain English
- **Context-Aware Operations**: Understands complex monitoring scenarios
- **Error Handling**: Intelligent error detection and resolution suggestions
- **Streaming Updates**: Real-time progress updates during operations

### 🔗 MCP Integration
- **HTTP Transport**: Reliable HTTP-based communication with MCP server
- **Tool Discovery**: Automatically discovers available Instana tools
- **Session Management**: Proper connection lifecycle management
- **Error Recovery**: Robust error handling and recovery mechanisms

## 🎯 Supported Operations

### Application Monitoring
- **Events**: "Show me Kubernetes events for the last 24 hours"
- **Alerts**: "Get all active alerts for my applications"
- **Metrics**: "Show application performance metrics"
- **Health Status**: "Check the health of my services"

### Infrastructure Monitoring
- **Resources**: "List all infrastructure resources"
- **Topology**: "Show me the infrastructure topology"
- **Analysis**: "Analyze infrastructure performance issues"
- **Catalog**: "Get infrastructure catalog information"

### Performance Analysis
- **Event Analysis**: "Analyze recent performance events"
- **Troubleshooting**: "Help me troubleshoot application issues"
- **Trend Analysis**: "Show performance trends over time"
- **Capacity Planning**: "Analyze resource utilization patterns"

## 🚀 Quick Start

### Prerequisites

Before running the agent, you need:

1. **Instana Instance**: Access to an Instana monitoring platform
2. **API Token**: A valid Instana API token with appropriate permissions
3. **MCP Instana Server**: The mcp-instana server running in HTTP mode at `http://127.0.0.1:8000/mcp`
4. **Google API Key**: For the Gemini model used by the agent

### Setup and Run

**Step 1: Start the MCP Server**
```bash
cd ../mcp-instana
export INSTANA_BASE_URL="https://your-instana-instance.instana.io"
export INSTANA_API_TOKEN="your-instana-api-token"
python src/mcp_server.py --transport http --mcp-host localhost --mcp-port 8000 --debug

```

**Step 2: Start the Instana Agent**
```bash
cd instanaAgent
export INSTANA_BASE_URL="https://your-instana-instance.instana.io"
export INSTANA_API_TOKEN="your-instana-api-token"
export GOOGLE_API_KEY="your-google-api-key"
export MCP_SERVER_URL="http://127.0.0.1:8000/mcp"  # Optional, defaults to this
uv sync
uv run -m app
```

**Step 3: Test the Agent**
```bash
curl -X POST http://localhost:8005 \
  -H "Content-Type: application/json" \
  -d '{"method": "message/send", "params": {"message": {"parts": [{"text": "Show me recent events"}]}}}'
```

## 🧪 Testing & Validation

### Test the Setup

```bash
# Test the agent directly
curl -X POST http://localhost:8005 \
  -H "Content-Type: application/json" \
  -d '{"method": "message/send", "params": {"message": {"parts": [{"text": "Show me the latest alerts from Instana"}]}}}'

curl -X POST http://localhost:8005 \
  -H "Content-Type: application/json" \
  -d '{"method": "message/send", "params": {"message": {"parts": [{"text": "Get Kubernetes events for the last 24 hours"}]}}}'
```

### Expected Results

**Instana Operations**:
```
✅ Get Events: "Found 25 Kubernetes events in the last 24 hours..."
✅ Get Alerts: "Found 5 active alerts: High CPU usage, Memory threshold exceeded..."
✅ Infrastructure Status: "Infrastructure topology shows 15 services across 3 clusters..."
✅ Performance Analysis: "Application performance shows latency spike at 14:30..."
```

## 🔧 Technical Architecture

### MCP Integration

The agent uses the mcp-instana MCP server for monitoring operations via HTTP:

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from langchain_mcp_adapters.tools import load_mcp_tools

class InstanaAgent:
    async def _init_mcp_tools(self):
        # MCP server endpoint - default to localhost:8000/mcp
        mcp_server_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
        
        # Use HTTP connection to MCP server
        async with streamablehttp_client(mcp_server_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await load_mcp_tools(session)
                return tools
```

### Agent Architecture

```python
from a2a.server.agent_execution import AgentExecutor

class InstanaAgentExecutor(AgentExecutor):
    def __init__(self):
        self.agent = InstanaAgent()
    
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        # Handle agent requests and stream responses
```

## 🔍 Available Tools

The agent provides access to comprehensive Instana monitoring tools:

### Event Tools
- `get_event`: Get specific event by ID
- `get_kubernetes_info_events`: Get Kubernetes events with time filtering
- `get_agent_monitoring_events`: Get agent monitoring events

### Infrastructure Tools
- `get_infrastructure_resources`: List infrastructure resources
- `get_infrastructure_catalog`: Get infrastructure catalog
- `get_infrastructure_topology`: Get infrastructure topology
- `analyze_infrastructure`: Analyze infrastructure performance

### Application Tools
- `get_application_resources`: Get application resources
- `get_application_metrics`: Get application performance metrics
- `get_application_alerts`: Get application alert configurations

## 🚨 Troubleshooting

### Common Issues

1. **MCP Server Connection Failed**
   ```bash
   # Check if MCP server is running
   curl http://127.0.0.1:8000/health
   
   # Start the MCP server if needed
   cd ../mcp-instana
   python src/mcp_server.py --host 127.0.0.1 --port 8000
   ```

2. **Instana API Authentication**
   ```bash
   # Verify environment variables
   echo $INSTANA_BASE_URL
   echo $INSTANA_API_TOKEN
   
   # Test API connectivity
   curl -H "Authorization: apiToken $INSTANA_API_TOKEN" \
        "$INSTANA_BASE_URL/api/instana/health"
   ```

3. **Missing Dependencies**
   ```bash
   # Reinstall dependencies
   uv sync --force
   ```

4. **Port Conflicts**
   ```bash
   # Check if port 8005 is available
   lsof -i :8005
   
   # Use a different port if needed
   uv run -m app --port 8006
   ```

## 📚 Environment Variables

Required environment variables:

```bash
# Required
INSTANA_BASE_URL="https://your-instana-instance.instana.io"
INSTANA_API_TOKEN="your-instana-api-token"
GOOGLE_API_KEY="your-google-api-key"

# Optional
MCP_SERVER_URL="http://127.0.0.1:8000/mcp"  # MCP server endpoint (defaults to this)
```

## 🔗 Integration Examples

### Claude Desktop Integration

Configure Claude Desktop to use the MCP server directly:

```json
{
  "mcpServers": {
    "Instana Tools": {
      "command": "npx",
      "args": ["mcp-remote", "http://127.0.0.1:8000/mcp"],
      "env": {
        "INSTANA_BASE_URL": "<INSTANA_BASE_URL>",
        "INSTANA_API_TOKEN": "<INSTANA_API_TOKEN>"
      }
    }
  }
}
```

### Custom Client Integration

```python
import httpx

async def query_instana_agent(question: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8005",
            json={
                "method": "message/send",
                "params": {
                    "message": {
                        "parts": [{"text": question}]
                    }
                }
            }
        )
        return response.json()

# Example usage
result = await query_instana_agent("Show me recent alerts")
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with the mcp-instana server
5. Submit a pull request

## 📄 License

This project is licensed under the Apache License - see the parent repository for details.