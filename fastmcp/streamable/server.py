from fastmcp import FastMCP

mcp = FastMCP(name="My MCP Server")

@mcp.tool
def greet(name: str) -> str:
    """Returns a friendly greeting."""
    return f"Hello, {name}!"
