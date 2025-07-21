import { TokenOptions, JWTPayload } from './token-generator.js';
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
declare class RealFastMCPClient {
    private options;
    private tokenGenerator;
    private currentToken;
    private tokenExpiry;
    private mcpClient;
    constructor(options?: ClientOptions);
    /**
     * Initialize the client by loading or generating keys
     */
    initialize(): Promise<boolean>;
    /**
     * Generate a new JWT token
     */
    generateToken(customOptions?: TokenOptions): Promise<string>;
    /**
     * Refresh token if it's expired or about to expire
     */
    refreshToken(): Promise<string>;
    /**
     * Get current token (refreshes if needed)
     */
    getToken(): Promise<string>;
    /**
     * Create LangChain MultiServerMCPClient configuration
     */
    createMCPClientConfig(): Promise<MCPClientConfig>;
    /**
     * Create and initialize the LangChain MCP client
     */
    createMCPClient(): Promise<any>;
    /**
     * Get tools from the MCP server
     */
    getTools(): Promise<any[]>;
    /**
     * List available tools with details
     */
    listTools(): Promise<any[]>;
    /**
     * Call a specific tool
     */
    callTool(toolName: string, parameters?: Record<string, any>): Promise<any>;
    /**
     * Create and run a LangChain agent
     */
    createAgent(modelName?: string, temperature?: number): Promise<any>;
    /**
     * Run agent with a user message
     */
    runAgent(message: string, modelName?: string, temperature?: number): Promise<any>;
    /**
     * Close the MCP client
     */
    close(): Promise<void>;
    /**
     * Get client status and token information
     */
    getStatus(): ClientStatus;
    /**
     * Verify current token
     */
    verifyCurrentToken(): Promise<JWTPayload>;
}
/**
 * Utility function to create a real FastMCP client
 */
declare function createRealFastMCPClient(options?: ClientOptions): RealFastMCPClient;
/**
 * Example usage with real server connection
 */
declare function realServerExample(): Promise<void>;
export { RealFastMCPClient, createRealFastMCPClient, realServerExample, ClientOptions, ClientStatus, MCPClientConfig };
//# sourceMappingURL=real-client.d.ts.map