import 'dotenv/config';
import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import { ChatOpenAI } from "@langchain/openai";
import { createReactAgent } from "@langchain/langgraph/prebuilt";

// Print JWT token for debugging
console.log("🔐 JWT Token:", process.env.JWT_TOKEN);
console.log("🔐 Token length:", process.env.JWT_TOKEN?.length || 0);

// Create client and connect to server
const client = new MultiServerMCPClient({
  // Global tool configuration options
  // Whether to throw on errors if a tool fails to load (optional, default: true)
  throwOnLoadError: true,
  // Whether to prefix tool names with the server name (optional, default: true)
  prefixToolNameWithServerName: true,
  // Optional additional prefix for tool names (optional, default: "mcp")
  additionalToolNamePrefix: "mcp",
  
  // Use standardized content block format in tool outputs
  useStandardContentBlocks: true,

  // Server configuration
  mcpServers: {


    // Streamable HTTP transport example, with auth headers and automatic SSE fallback disabled (defaults to enabled)
    googleworkspace: {
      url: "http://127.0.0.1:6006/mcp",
      headers: {
        Authorization: `Bearer ${process.env.JWT_TOKEN}`,
      },
      automaticSSEFallback: false
    },

    // OAuth 2.0 authentication (recommended for secure servers)
    // Uncomment and implement your OAuth provider when ready
    /*
    "oauth-protected-server": {
      url: "https://protected.example.com/mcp",
      authProvider: new MyOAuthProvider({
        // Your OAuth provider implementation
        redirectUrl: "https://myapp.com/oauth/callback",
        clientMetadata: {
          redirect_uris: ["https://myapp.com/oauth/callback"],
          client_name: "My MCP Client",
          scope: "mcp:read mcp:write"
        }
      }),
      // Can still include custom headers for non-auth purposes
      headers: {
        "User-Agent": "My-MCP-Client/1.0"
      }
    },
    */
    
  },
});

const tools = await client.getTools();

// Create an OpenAI model
const model = new ChatOpenAI({
  modelName: "gpt-4o",
  temperature: 0,
});

// Create the React agent
const agent = createReactAgent({
  llm: model,
  tools,
});

// Run the agent
try {
  const mathResponse = await agent.invoke({
    messages: [{ role: "user", content: "show me latest two emails" }],
  });
  console.log(mathResponse);
} catch (error) {
  console.error("Error during agent execution:", error);
  // Tools throw ToolException for tool-specific errors
  if (error.name === "ToolException") {
    console.error("Tool execution failed:", error.message);
  }
}

await client.close();