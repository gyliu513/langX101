# LangChainJS MCP Client

This project demonstrates how to use LangChainJS with the Model Context Protocol (MCP) to create AI agents that can interact with multiple MCP servers.

## Overview

The `langchainjs-client.js` file shows how to:
- Connect to multiple MCP servers (stdio, HTTP, SSE)
- Create a React agent with LangChainJS
- Use tools from different MCP servers
- Handle authentication and error scenarios

## Prerequisites

- Node.js (version 18 or higher)
- npm or yarn package manager
- OpenAI API key (for the ChatOpenAI model)

## Installation

1. **Create a new Node.js project** (if not already done):
   ```bash
   mkdir langchainjs-mcp-demo
   cd langchainjs-mcp-demo
   npm init -y
   ```

2. **Install required dependencies**:
   ```bash
   npm install @langchain/mcp-adapters @langchain/openai @langchain/langgraph
   ```

3. **Set up environment variables**:
   Create a `.env` file in your project root:
   ```env
   OPENAI_API_KEY=your_openai_api_key_here
   ```

## Configuration

### MCP Server Setup

The client is configured to connect to several types of MCP servers:

#### 1. Math Server (STDIO)
```javascript
math: {
  transport: "stdio",
  command: "npx",
  args: ["-y", "@modelcontextprotocol/server-math"],
  restart: {
    enabled: true,
    maxAttempts: 3,
    delayMs: 1000,
  },
}
```

#### 2. Filesystem Server (STDIO)
```javascript
filesystem: {
  transport: "stdio",
  command: "npx",
  args: ["-y", "@modelcontextprotocol/server-filesystem"],
}
```

#### 3. Weather Server (HTTP with Auth)
```javascript
weather: {
  url: "https://example.com/weather/mcp",
  headers: {
    Authorization: "Bearer token123",
  },
  automaticSSEFallback: false
}
```

#### 4. OAuth Protected Server
```javascript
"oauth-protected-server": {
  url: "https://protected.example.com/mcp",
  authProvider: new MyOAuthProvider({
    redirectUrl: "https://myapp.com/oauth/callback",
    clientMetadata: {
      redirect_uris: ["https://myapp.com/oauth/callback"],
      client_name: "My MCP Client",
      scope: "mcp:read mcp:write"
    }
  }),
  headers: {
    "User-Agent": "My-MCP-Client/1.0"
  }
}
```

#### 5. GitHub Server (SSE)
```javascript
github: {
  transport: "sse",
  url: "https://example.com/mcp",
  reconnect: {
    enabled: true,
    maxAttempts: 5,
    delayMs: 2000,
  },
}
```

## Usage

### Basic Usage

1. **Run the client**:
   ```bash
   node langchainjs-client.js
   ```

2. **The client will**:
   - Connect to all configured MCP servers
   - Load available tools from each server
   - Create a React agent with the tools
   - Execute a sample query: "what's (3 + 5) x 12?"
   - Display the result
   - Clean up connections

### Customizing the Query

To modify the query, edit the `agent.invoke()` call in the script:

```javascript
const response = await agent.invoke({
  messages: [{ role: "user", content: "Your custom query here" }],
});
```

### Adding New MCP Servers

To add a new MCP server, add it to the `mcpServers` configuration:

```javascript
mcpServers: {
  // ... existing servers ...
  
  "my-new-server": {
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-my-server"],
  },
}
```

## Configuration Options

### Global Options

- `throwOnLoadError`: Whether to throw errors if a tool fails to load (default: true)
- `prefixToolNameWithServerName`: Prefix tool names with server name (default: true)
- `additionalToolNamePrefix`: Additional prefix for tool names (default: "mcp")
- `useStandardContentBlocks`: Use standardized content block format (default: true)

### Transport Options

#### STDIO Transport
```javascript
{
  transport: "stdio",
  command: "npx",
  args: ["-y", "package-name"],
  restart: {
    enabled: true,
    maxAttempts: 3,
    delayMs: 1000,
  }
}
```

#### HTTP Transport
```javascript
{
  url: "https://example.com/mcp",
  headers: {
    Authorization: "Bearer token",
  },
  automaticSSEFallback: true
}
```

#### SSE Transport
```javascript
{
  transport: "sse",
  url: "https://example.com/mcp",
  reconnect: {
    enabled: true,
    maxAttempts: 5,
    delayMs: 2000,
  }
}
```

## Error Handling

The client includes comprehensive error handling:

```javascript
try {
  const response = await agent.invoke({
    messages: [{ role: "user", content: "Your query" }],
  });
  console.log(response);
} catch (error) {
  console.error("Error during agent execution:", error);
  if (error.name === "ToolException") {
    console.error("Tool execution failed:", error.message);
  }
}
```

## Troubleshooting

### Common Issues

1. **"Module not found" errors**:
   - Ensure all dependencies are installed: `npm install`
   - Check that you're using Node.js 18+ with ES modules support

2. **OpenAI API errors**:
   - Verify your `OPENAI_API_KEY` is set correctly
   - Check your OpenAI account has sufficient credits

3. **MCP server connection failures**:
   - Ensure the MCP server packages are available on npm
   - Check network connectivity for HTTP/SSE servers
   - Verify authentication tokens for protected servers

4. **Tool loading errors**:
   - Check server configurations
   - Verify server compatibility with MCP protocol version

### Debug Mode

Enable debug logging by setting the log level:

```javascript
// Add this before creating the client
process.env.DEBUG = "mcp:*";
```

## Examples

### Simple Math Query
```javascript
const response = await agent.invoke({
  messages: [{ role: "user", content: "Calculate 15 * 23" }],
});
```

### File Operations
```javascript
const response = await agent.invoke({
  messages: [{ role: "user", content: "List files in the current directory" }],
});
```

### Weather Information
```javascript
const response = await agent.invoke({
  messages: [{ role: "user", content: "What's the weather in New York?" }],
});
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Resources

- [LangChainJS Documentation](https://js.langchain.com/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [MCP Server Registry](https://github.com/modelcontextprotocol/server-registry)
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchainjs/tree/main/langchain-mcp-adapters) 