from fastmcp import FastMCP

mcp = FastMCP(name="My MCP Server")

@mcp.tool
def greet(name: str) -> str:
    """Returns a friendly greeting."""
    return f"Hello, {name}!"

if __name__ == "__main__":
    print("Starting FastMCP server on http://localhost:8000/mcp")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp")
