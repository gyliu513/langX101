from fastmcp import FastMCP
mcp = FastMCP(name="My MCP Server")

@mcp.tool
def add(a: int, b: int) -> int:
    """Returns the sum of two integers."""
    return a + b

@mcp.tool
def greet(name: str) -> str:
    """Returns a friendly greeting."""
    return f"Hello, {name}!"

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp")
