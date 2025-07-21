import { FastMCPTokenGenerator, TokenOptions, JWTPayload } from './token-generator.js';
import fs from 'fs';

/**
 * Client options interface
 */
interface ClientOptions {
    serverUrl?: string;
    privateKeyPath?: string;
    publicKeyPath?: string;
    defaultSubject?: string;
    defaultIssuer?: string;
    defaultAudience?: string;
    defaultScopes?: string[];
    defaultExpiresIn?: string;
    serverName?: string;
}

/**
 * Client status interface
 */
interface ClientStatus {
    initialized: boolean;
    serverUrl: string;
    serverName: string;
    tokenExpiry: string | null;
    tokenValid: boolean;
    mcpClientCreated: boolean;
    keyFiles: {
        privateKey: boolean;
        publicKey: boolean;
    };
}

/**
 * MCP client configuration interface
 */
interface MCPClientConfig {
    throwOnLoadError: boolean;
    prefixToolNameWithServerName: boolean;
    additionalToolNamePrefix: string;
    useStandardContentBlocks: boolean;
    mcpServers: {
        [key: string]: {
            url: string;
            headers: {
                Authorization: string;
            };
            automaticSSEFallback: boolean;
        };
    };
}

/**
 * Real FastMCP Client using LangChain MultiServerMCPClient
 * 
 * This client uses the token generator to create JWT tokens for authentication
 * and integrates with the LangChain MultiServerMCPClient for proper MCP communication.
 */
class RealFastMCPClient {
    private options: Required<ClientOptions>;
    private tokenGenerator: FastMCPTokenGenerator;
    private currentToken: string | null;
    private tokenExpiry: Date | null;
    private mcpClient: any; // Using any for LangChain client type

    constructor(options: ClientOptions = {}) {
        this.options = {
            serverUrl: 'http://localhost:8000/mcp',
            privateKeyPath: '/Users/guangyaliu/langX101/fastmcp/auth/private.pem',
            publicKeyPath: '/Users/guangyaliu/langX101/fastmcp/auth/public.pem',
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
    async initialize(): Promise<boolean> {
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
            console.error('❌ Error initializing client:', (error as Error).message);
            return false;
        }
    }

    /**
     * Generate a new JWT token
     */
    async generateToken(customOptions: TokenOptions = {}): Promise<string> {
        const tokenOptions: TokenOptions = {
            subject: this.options.defaultSubject,
            issuer: this.options.defaultIssuer,
            audience: this.options.defaultAudience,
            scopes: this.options.defaultScopes,
            expiresIn: this.options.defaultExpiresIn,
            ...customOptions
        };

        try {
            const token = this.tokenGenerator.createToken(tokenOptions);
            const payload = this.tokenGenerator.verifyToken(token);
            
            this.currentToken = token;
            this.tokenExpiry = new Date(payload.exp * 1000);
            
            console.log('🔐 New JWT token generated');
            console.log(`📋 Token expires: ${this.tokenExpiry.toISOString()}`);
            
            return token;
        } catch (error) {
            console.error('❌ Error generating token:', (error as Error).message);
            throw error;
        }
    }

    /**
     * Refresh token if it's expired or about to expire
     */
    async refreshToken(): Promise<string> {
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
    async getToken(): Promise<string> {
        return await this.refreshToken();
    }

    /**
     * Create LangChain MultiServerMCPClient configuration
     */
    async createMCPClientConfig(): Promise<MCPClientConfig> {
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
    async createMCPClient(): Promise<any> {
        try {
            console.log('🔧 Creating LangChain MCP client...');
            
            // Dynamic import for ES modules
            const { MultiServerMCPClient } = await import('@langchain/mcp-adapters');
            
            const config = await this.createMCPClientConfig();
            this.mcpClient = new MultiServerMCPClient(config);
            
            console.log('✅ LangChain MCP client created successfully');
            return this.mcpClient;
        } catch (error) {
            console.error('❌ Error creating MCP client:', (error as Error).message);
            console.log('💡 Make sure @langchain/mcp-adapters is installed: npm install @langchain/mcp-adapters');
            throw error;
        }
    }

    /**
     * Get tools from the MCP server
     */
    async getTools(): Promise<any[]> {
        try {
            if (!this.mcpClient) {
                await this.createMCPClient();
            }

            console.log('📋 Getting tools from MCP server...');
            const tools = await this.mcpClient.getTools();
            
            console.log(`✅ Retrieved ${tools.length} tools from server`);
            return tools;
        } catch (error) {
            console.error('❌ Error getting tools:', (error as Error).message);
            throw error;
        }
    }

    /**
     * List available tools with details
     */
    async listTools(): Promise<any[]> {
        try {
            const tools = await this.getTools();
            
            console.log('\n🔧 Available Tools:');
            console.log('='.repeat(50));
            
            if (tools.length === 0) {
                console.log('❌ No tools available');
            } else {
                tools.forEach((tool: any, index: number) => {
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
            console.log('='.repeat(50));
            
            return tools;
        } catch (error) {
            console.error('❌ Error listing tools:', (error as Error).message);
            throw error;
        }
    }

    /**
     * Call a specific tool
     */
    async callTool(toolName: string, parameters: Record<string, any> = {}): Promise<any> {
        try {
            if (!this.mcpClient) {
                await this.createMCPClient();
            }

            console.log(`🛠️ Calling tool: ${toolName}`);
            console.log(`📋 Parameters:`, parameters);
            
            // Get the tool from the client
            const tools = await this.mcpClient.getTools();
            const tool = tools.find((t: any) => t.name === toolName || t.name.endsWith(toolName));
            
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
            console.error(`❌ Error calling tool ${toolName}:`, (error as Error).message);
            throw error;
        }
    }

    /**
     * Create and run a LangChain agent
     */
    // eslint-disable-next-line @typescript-eslint/no-unused-vars, no-unused-vars
    async createAgent(modelName: string = "gpt-4o", temperature: number = 0): Promise<any> {
        try {
            console.log('🤖 Creating LangChain agent...');
            
            // Note: This requires @langchain/openai and @langchain/langgraph packages
            // For now, we'll throw an error if the packages aren't available
            throw new Error('LangChain agent creation requires additional packages. Install with: npm install @langchain/openai @langchain/langgraph');
        } catch (error) {
            console.error('❌ Error creating agent:', (error as Error).message);
            console.log('💡 Make sure required packages are installed: npm install @langchain/openai @langchain/langgraph');
            throw error;
        }
    }

    /**
     * Run agent with a user message
     */
    // eslint-disable-next-line @typescript-eslint/no-unused-vars, no-unused-vars
    async runAgent(message: string, modelName: string = "gpt-4o", temperature: number = 0): Promise<any> {
        try {
            console.log('🤖 Running LangChain agent...');
            console.log(`📝 User message: ${message}`);
            
            // Note: This requires @langchain/openai and @langchain/langgraph packages
            throw new Error('LangChain agent execution requires additional packages. Install with: npm install @langchain/openai @langchain/langgraph');
        } catch (error) {
            console.error('❌ Error running agent:', (error as Error).message);
            if ((error as any).name === "ToolException") {
                console.error("Tool execution failed:", (error as Error).message);
            }
            throw error;
        }
    }

    /**
     * Close the MCP client
     */
    async close(): Promise<void> {
        if (this.mcpClient) {
            console.log('🔒 Closing MCP client...');
            await this.mcpClient.close();
            console.log('✅ MCP client closed');
        }
    }

    /**
     * Get client status and token information
     */
    getStatus(): ClientStatus {
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
    async verifyCurrentToken(): Promise<JWTPayload> {
        if (!this.currentToken) {
            throw new Error('No current token to verify');
        }

        try {
            const payload = this.tokenGenerator.verifyToken(this.currentToken);
            console.log('✅ Current token is valid');
            console.log('📋 Token payload:', JSON.stringify(payload, null, 2));
            return payload;
        } catch (error) {
            console.error('❌ Current token verification failed:', (error as Error).message);
            throw error;
        }
    }
}

/**
 * Utility function to create a real FastMCP client
 */
function createRealFastMCPClient(options: ClientOptions = {}): RealFastMCPClient {
    return new RealFastMCPClient(options);
}

/**
 * Example usage with real server connection
 */
async function realServerExample(): Promise<void> {
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
        await client.listTools();

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
        console.error('❌ Real server example failed:', (error as Error).message);
        console.log('\n💡 Make sure the FastMCP server is running on http://localhost:8000/mcp');
        console.log('💡 Install required packages: npm install @langchain/mcp-adapters @langchain/openai @langchain/langgraph');
    }
}

// Export for use as module
export {
    RealFastMCPClient,
    createRealFastMCPClient,
    realServerExample,
    ClientOptions,
    ClientStatus,
    MCPClientConfig
};

// Run example if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
    realServerExample().catch(console.error);
} 