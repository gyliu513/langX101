import { FastMCPTokenGenerator, generateFastMCPToken } from './token-generator.js';
import fs from 'fs';

/**
 * Real FastMCP Client using LangChain MultiServerMCPClient
 * 
 * This client uses the token generator to create JWT tokens for authentication
 * and integrates with the LangChain MultiServerMCPClient for proper MCP communication.
 */
class RealFastMCPClient {
    constructor(options = {}) {
        this.options = {
            serverUrl: 'http://localhost:8000/mcp',
            privateKeyPath: 'private.pem',
            publicKeyPath: 'public.pem',
            defaultSubject: 'real-client@example.com',
            defaultIssuer: 'http://localhost:8000',
            defaultAudience: 'my-mcp-server',
            defaultScopes: ['read', 'write'],
            defaultExpiresIn: '30d',
            serverName: 'fastmcp-server',
            ...options
        };

        this.tokenGenerator = new FastMCPTokenGenerator(
            this.options.privateKeyPath,
            this.options.publicKeyPath
        );

        this.currentToken = null;
        this.tokenExpiry = null;
        this.mcpClient = null;
    }

    /**
     * Initialize the client by loading or generating keys
     */
    async initialize() {
        try {
            console.log('🔧 Initializing Real FastMCP Client...');
            
            // Try to load existing keys, generate new ones if they don't exist
            if (!this.tokenGenerator.loadKeys()) {
                console.log('📝 No existing keys found, generating new key pair...');
                this.tokenGenerator.generateKeyPair();
            }

            // Generate initial token
            await this.refreshToken();
            
            console.log('✅ Real FastMCP Client initialized successfully');
            return true;
        } catch (error) {
            console.error('❌ Error initializing client:', error.message);
            return false;
        }
    }

    /**
     * Generate a new JWT token using generateFastMCPToken
     */
    async generateToken(customOptions = {}) {
        const tokenOptions = {
            subject: this.options.defaultSubject,
            issuer: this.options.defaultIssuer,
            audience: this.options.defaultAudience,
            scopes: this.options.defaultScopes,
            expiresIn: this.options.defaultExpiresIn,
            ...customOptions
        };

        try {
            const token = generateFastMCPToken(tokenOptions);
            const payload = this.tokenGenerator.verifyToken(token);
            
            this.currentToken = token;
            this.tokenExpiry = new Date(payload.exp * 1000);
            
            console.log('🔐 New JWT token generated using generateFastMCPToken');
            console.log(`📋 Token expires: ${this.tokenExpiry.toISOString()}`);
            
            return token;
        } catch (error) {
            console.error('❌ Error generating token:', error.message);
            throw error;
        }
    }

    /**
     * Refresh token if it's expired or about to expire
     */
    async refreshToken() {
        const now = new Date();
        const bufferTime = 5 * 60 * 1000; // 5 minutes buffer

        if (!this.currentToken || !this.tokenExpiry || 
            this.tokenExpiry.getTime() - now.getTime() < bufferTime) {
            console.log('🔄 Refreshing JWT token...');
            return await this.generateToken();
        }

        console.log('✅ Current token is still valid');
        return this.currentToken;
    }

    /**
     * Get current token (refreshes if needed)
     */
    async getToken() {
        return await this.refreshToken();
    }

    /**
     * Create LangChain MultiServerMCPClient configuration
     */
    async createMCPClientConfig() {
        const token = await this.getToken();
        
        console.log('🔐 Using JWT token for MCP client');
        console.log(`📋 Token preview: ${token.substring(0, 50)}...`);

        return {
            // Global tool configuration options
            throwOnLoadError: true,
            prefixToolNameWithServerName: true,
            additionalToolNamePrefix: "mcp",
            useStandardContentBlocks: true,

            // Server configuration
            mcpServers: {
                [this.options.serverName]: {
                    url: this.options.serverUrl,
                    headers: {
                        Authorization: `Bearer ${token}`,
                    },
                    automaticSSEFallback: false
                }
            }
        };
    }

    /**
     * Create and initialize the LangChain MCP client
     */
    async createMCPClient() {
        try {
            console.log('🔧 Creating LangChain MCP client...');
            
            // Dynamic import for ES modules
            const { MultiServerMCPClient } = await import('@langchain/mcp-adapters');
            
            const config = await this.createMCPClientConfig();
            this.mcpClient = new MultiServerMCPClient(config);
            
            console.log('✅ LangChain MCP client created successfully');
            return this.mcpClient;
        } catch (error) {
            console.error('❌ Error creating MCP client:', error.message);
            console.log('💡 Make sure @langchain/mcp-adapters is installed: npm install @langchain/mcp-adapters');
            throw error;
        }
    }

    /**
     * Get tools from the MCP server
     */
    async getTools() {
        try {
            if (!this.mcpClient) {
                await this.createMCPClient();
            }

            console.log('📋 Getting tools from MCP server...');
            const tools = await this.mcpClient.getTools();
            
            console.log(`✅ Retrieved ${tools.length} tools from server`);
            return tools;
        } catch (error) {
            console.error('❌ Error getting tools:', error.message);
            throw error;
        }
    }

    /**
     * List available tools with details
     */
    async listTools() {
        try {
            const tools = await this.getTools();
            
            console.log('\n🔧 Available Tools:');
            console.log('=' * 50);
            
            if (tools.length === 0) {
                console.log('❌ No tools available');
            } else {
                tools.forEach((tool, index) => {
                    console.log(`${index + 1}. 📋 ${tool.name}`);
                    if (tool.description) {
                        console.log(`   Description: ${tool.description}`);
                    }
                    if (tool.schema) {
                        console.log(`   Schema: ${JSON.stringify(tool.schema, null, 2)}`);
                    }
                    console.log('');
                });
            }
            
            console.log(`Total tools: ${tools.length}`);
            console.log('=' * 50);
            
            return tools;
        } catch (error) {
            console.error('❌ Error listing tools:', error.message);
            throw error;
        }
    }

    /**
     * Call a specific tool
     */
    async callTool(toolName, parameters = {}) {
        try {
            if (!this.mcpClient) {
                await this.createMCPClient();
            }

            console.log(`🛠️ Calling tool: ${toolName}`);
            console.log(`📋 Parameters:`, parameters);
            
            // Get the tool from the client
            const tools = await this.mcpClient.getTools();
            const tool = tools.find(t => t.name === toolName || t.name.endsWith(toolName));
            
            if (!tool) {
                throw new Error(`Tool '${toolName}' not found`);
            }

            console.log(`🔧 Found tool: ${tool.name}`);
            
            // Call the tool
            const result = await tool.invoke(parameters);
            
            console.log('✅ Tool call completed successfully');
            console.log('📋 Result:', result);
            
            return result;
        } catch (error) {
            console.error(`❌ Error calling tool ${toolName}:`, error.message);
            throw error;
        }
    }

    /**
     * Create and run a LangChain agent
     */
    async createAgent(modelName = "gpt-4o", temperature = 0) {
        try {
            console.log('🤖 Creating LangChain agent...');
            
            // Dynamic imports for ES modules
            const { ChatOpenAI } = await import('@langchain/openai');
            const { createReactAgent } = await import('@langchain/langgraph/prebuilt');
            
            const tools = await this.getTools();
            
            // Create an OpenAI model
            const model = new ChatOpenAI({
                modelName: modelName,
                temperature: temperature,
            });

            // Create the React agent
            const agent = createReactAgent({
                llm: model,
                tools,
            });

            console.log('✅ LangChain agent created successfully');
            return agent;
        } catch (error) {
            console.error('❌ Error creating agent:', error.message);
            console.log('💡 Make sure required packages are installed: npm install @langchain/openai @langchain/langgraph');
            throw error;
        }
    }

    /**
     * Run agent with a user message
     */
    async runAgent(message, modelName = "gpt-4o", temperature = 0) {
        try {
            console.log('🤖 Running LangChain agent...');
            console.log(`📝 User message: ${message}`);
            
            const agent = await this.createAgent(modelName, temperature);
            
            const response = await agent.invoke({
                messages: [{ role: "user", content: message }],
            });
            
            console.log('✅ Agent execution completed');
            console.log('📋 Response:', response);
            
            return response;
        } catch (error) {
            console.error('❌ Error running agent:', error.message);
            if (error.name === "ToolException") {
                console.error("Tool execution failed:", error.message);
            }
            throw error;
        }
    }

    /**
     * Close the MCP client
     */
    async close() {
        if (this.mcpClient) {
            console.log('🔒 Closing MCP client...');
            await this.mcpClient.close();
            console.log('✅ MCP client closed');
        }
    }

    /**
     * Get client status and token information
     */
    getStatus() {
        return {
            initialized: !!this.currentToken,
            serverUrl: this.options.serverUrl,
            serverName: this.options.serverName,
            tokenExpiry: this.tokenExpiry ? this.tokenExpiry.toISOString() : null,
            tokenValid: this.tokenExpiry ? this.tokenExpiry > new Date() : false,
            mcpClientCreated: !!this.mcpClient,
            keyFiles: {
                privateKey: fs.existsSync(this.options.privateKeyPath),
                publicKey: fs.existsSync(this.options.publicKeyPath)
            }
        };
    }

    /**
     * Verify current token
     */
    async verifyCurrentToken() {
        if (!this.currentToken) {
            throw new Error('No current token to verify');
        }

        try {
            const payload = this.tokenGenerator.verifyToken(this.currentToken);
            console.log('✅ Current token is valid');
            console.log('📋 Token payload:', JSON.stringify(payload, null, 2));
            return payload;
        } catch (error) {
            console.error('❌ Current token verification failed:', error.message);
            throw error;
        }
    }
}

/**
 * Utility function to create a real FastMCP client
 */
function createRealFastMCPClient(options = {}) {
    return new RealFastMCPClient(options);
}

/**
 * Example usage with real server connection
 */
async function realServerExample() {
    console.log('🚀 Real FastMCP Server Connection Example\n');

    // Create real client
    const client = createRealFastMCPClient({
        serverUrl: 'http://localhost:8000/mcp',
        defaultSubject: 'real-user@example.com',
        defaultScopes: ['read', 'write'],
        serverName: 'fastmcp-auth-server'
    });

    try {
        // Initialize the client
        console.log('📝 Step 1: Initializing real client...');
        const initialized = await client.initialize();
        if (!initialized) {
            throw new Error('Failed to initialize client');
        }

        // Get client status
        console.log('\n📝 Step 2: Client status...');
        const status = client.getStatus();
        console.log('📋 Status:', JSON.stringify(status, null, 2));

        // Verify current token
        console.log('\n📝 Step 3: Verifying current token...');
        await client.verifyCurrentToken();

        // List available tools from real server
        console.log('\n📝 Step 4: Listing tools from real server...');
        const tools = await client.listTools();

        // Call the greet tool on the real server
        console.log('\n📝 Step 5: Calling greet tool on real server...');
        const result = await client.callTool('greet', { name: 'Alice' });
        console.log('📋 Greet result:', result);

        // Close the client
        console.log('\n📝 Step 6: Closing client...');
        await client.close();

        console.log('\n🎉 Real server example completed successfully!');
        console.log('\n💡 Check the server console to see the access token print statement!');
    } catch (error) {
        console.error('❌ Real server example failed:', error.message);
        console.log('\n💡 Make sure the FastMCP server is running on http://localhost:8000/mcp');
        console.log('💡 Install required packages: npm install @langchain/mcp-adapters @langchain/openai @langchain/langgraph');
    }
}

// Export for use as module
export {
    RealFastMCPClient,
    createRealFastMCPClient,
    realServerExample
};

// Run example if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
    realServerExample().catch(console.error);
} 