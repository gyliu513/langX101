# server.py
from fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("My MCP Server")

@mcp.tool
def greet(name: str) -> str:
    """Returns a friendly greeting."""
    return f"Hello, {name}!"