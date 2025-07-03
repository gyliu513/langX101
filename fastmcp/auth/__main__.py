from server import mcp

if __name__ == "__main__":
    print("Starting FastMCP server via __main__.py on http://localhost:8000/mcp")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp") 