# FastMCP Auth Example

A simple FastMCP (Model Context Protocol) server and client example that demonstrates basic MCP functionality with a greeting tool.

## Prerequisites

- Python 3.10 or higher
- `uv` package manager (install from https://docs.astral.sh/uv/getting-started/installation/)

## Quick Start

### 1. Navigate to the Project Directory

```bash
cd /Users/guangyaliu/go/src/github.com/gyliu513/langX101/fastmcp/auth
```

### 2. Install Dependencies

```bash
uv sync --extra dev
```

This installs all required dependencies including:
- `fastmcp` - The main FastMCP library
- `httpx` - HTTP client library
- `requests` - HTTP requests library
- `asyncio` - Async I/O support

### 3. Start the Server

In your terminal, run:

```bash
uv run server.py
```

You should see:
```
Starting FastMCP server on http://localhost:8000/mcp
```

The server is now running and listening for connections on port 8000.

### 4. Test the Client

Open a **new terminal window** and navigate to the same directory:

```bash
cd /Users/guangyaliu/go/src/github.com/gyliu513/langX101/fastmcp/auth
```

Then run the client:

```bash
uv run client.py
```

You should see output like:
```
🚀 Starting FastMCP client...
✅ Client connected: True
📋 Available tools: ['greet']
🎯 Testing greet tool...
💬 Greet result: Hello, FastMCP 2.0!
🔌 Client disconnected: False
```

## What's Happening

1. **Server (`server.py`)**: Creates a FastMCP server with a `greet` tool that returns a friendly greeting
2. **Client (`client.py`)**: Connects to the server, lists available tools, and tests the `greet` tool
3. **Communication**: The client and server communicate using the Model Context Protocol (MCP) over HTTP

## Project Structure

```
fastmcp/auth/
├── server.py          # FastMCP server with greet tool
├── client.py          # Client that tests the server
├── __main__.py        # Alternative server entry point
├── __init__.py        # Makes this a Python package
├── pyproject.toml     # Project configuration and dependencies
└── README.md          # This file
```

## Troubleshooting

### "No module named 'fastmcp'" Error
Make sure you've installed dependencies:
```bash
uv sync --extra dev
```

### "Failed to connect" Error
Make sure the server is running first:
```bash
uv run server.py
```

### Port Already in Use
If port 8000 is busy, you can modify the port in `server.py`:
```python
mcp.run(transport="streamable-http", host="0.0.0.0", port=8001, path="/mcp")
```

## Alternative Ways to Run

### Run Server via Module
```bash
uv run -m fastmcp_auth
```

### Run Server via __main__.py
```bash
uv run __main__.py
```

## Understanding the Code

### Server (server.py)
```python
from fastmcp import FastMCP

mcp = FastMCP(name="My MCP Server")

@mcp.tool
def greet(name: str) -> str:
    """Returns a friendly greeting."""
    return f"Hello, {name}!"

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp")
```

### Client (client.py)
```python
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

# Connects to server, lists tools, and tests the greet function
```

## Next Steps

- Add more tools to the server
- Implement authentication
- Add error handling
- Create a more complex MCP server

## Resources

- [FastMCP Documentation](https://fastmcp.com/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [uv Package Manager](https://docs.astral.sh/uv/) 