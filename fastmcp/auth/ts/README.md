# FastMCP Authentication TypeScript Implementation

This directory contains TypeScript versions of the FastMCP authentication utilities, providing type safety and better development experience.

## 📁 Files

- `token-generator.ts` - JWT token generator with RSA key pair management
- `real-client.ts` - LangChain MCP client with JWT authentication
- `package.json` - Project dependencies and scripts
- `tsconfig.json` - TypeScript configuration

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd fastmcp/auth/ts
npm install
```

### 2. Build TypeScript Files

```bash
npm run build
```

This will compile the TypeScript files to JavaScript in the `dist/` directory.

### 3. Run the Token Generator

```bash
# Generate a new token with default settings
npm run token

# Generate keys first, then token
npm run token -- --generate-keys

# Generate token with custom options
npm run token -- --subject "user@example.com" --scopes "read,write,admin" --expires "1h"

# Verify an existing token
npm run token -- --verify "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
```

### 4. Run the Real Client

```bash
# Run the example client (requires FastMCP server running)
npm run client
```

## 🔧 Available Scripts

| Script | Description |
|--------|-------------|
| `npm run build` | Compile TypeScript to JavaScript |
| `npm run dev` | Watch mode - recompile on file changes |
| `npm run start` | Run token generator |
| `npm run start:client` | Run real client |
| `npm run token` | Run token generator with CLI |
| `npm run client` | Run real client example |
| `npm run clean` | Remove compiled files |
| `npm run test` | Run tests (placeholder) |

## 📋 Token Generator Usage

### Command Line Options

```bash
node dist/token-generator.js [options]

Options:
  --generate-keys    Generate new RSA key pair (or load existing if present)
  --subject <email>  Token subject (default: dev-user)
  --issuer <url>     Token issuer (default: http://localhost:8000)
  --audience <name>  Token audience (default: my-mcp-server)
  --scopes <list>    Comma-separated scopes (default: read,write)
  --expires <time>   Expiration time (default: 30d)
  --verify <token>   Verify an existing token
  --help, -h         Show help
```

### Examples

```bash
# Generate new RSA keys
node dist/token-generator.js --generate-keys

# Generate token for specific user
node dist/token-generator.js --subject "alice@example.com" --scopes "read,write,admin"

# Generate short-lived token
node dist/token-generator.js --expires "1h" --subject "temp-user"

# Verify a token
node dist/token-generator.js --verify "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
```

## 🔌 Real Client Usage

### Prerequisites

1. **FastMCP Server Running**: Make sure your FastMCP server is running on `http://localhost:8000/mcp`
2. **RSA Keys**: The client will automatically generate or load RSA keys from `/Users/guangyaliu/langX101/fastmcp/auth/`

### Basic Usage

```typescript
import { createRealFastMCPClient } from './real-client.js';

// Create client
const client = createRealFastMCPClient({
    serverUrl: 'http://localhost:8000/mcp',
    defaultSubject: 'my-user@example.com',
    defaultScopes: ['read', 'write'],
    serverName: 'my-fastmcp-server'
});

// Initialize and use
await client.initialize();
const tools = await client.listTools();
const result = await client.callTool('greet', { name: 'Alice' });
await client.close();
```

### Advanced Usage

```typescript
import { RealFastMCPClient } from './real-client.js';

const client = new RealFastMCPClient({
    serverUrl: 'http://localhost:8000/mcp',
    defaultSubject: 'admin@example.com',
    defaultScopes: ['read', 'write', 'admin'],
    serverName: 'admin-server'
});

try {
    // Initialize
    await client.initialize();
    
    // Check status
    const status = client.getStatus();
    console.log('Client status:', status);
    
    // Verify token
    await client.verifyCurrentToken();
    
    // List available tools
    const tools = await client.listTools();
    
    // Call specific tool
    const result = await client.callTool('greet', { name: 'World' });
    console.log('Greet result:', result);
    
    // Create and run agent
    const response = await client.runAgent('Hello, how are you?');
    console.log('Agent response:', response);
    
} catch (error) {
    console.error('Error:', error);
} finally {
    await client.close();
}
```

## 🔑 RSA Key Management

The TypeScript implementation uses the same RSA key management as the JavaScript version:

- **Key Location**: `/Users/guangyaliu/langX101/fastmcp/auth/private.pem` and `public.pem`
- **Auto-generation**: Keys are automatically generated if they don't exist
- **Key Loading**: Existing keys are loaded automatically

### Manual Key Generation

```bash
# Generate new keys
node dist/token-generator.js --generate-keys
```

## 🛠️ Development

### TypeScript Features

- **Type Safety**: Full TypeScript support with strict type checking
- **Interfaces**: Well-defined interfaces for all data structures
- **Error Handling**: Proper error typing and handling
- **ES Modules**: Modern ES module imports/exports

### Key Interfaces

```typescript
// Token options
interface TokenOptions {
    subject?: string;
    issuer?: string;
    audience?: string;
    scopes?: string[];
    expiresIn?: string;
}

// Client options
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

// Client status
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
```

### Building for Production

```bash
# Clean build
npm run clean
npm run build

# The compiled JavaScript files will be in dist/
```

## 🔍 Troubleshooting

### Common Issues

1. **TypeScript Compilation Errors**
   ```bash
   # Check TypeScript configuration
   npx tsc --noEmit
   
   # Fix type issues
   npm run build
   ```

2. **Missing Dependencies**
   ```bash
   # Install missing packages
   npm install @langchain/mcp-adapters @langchain/openai @langchain/langgraph
   ```

3. **RSA Key Issues**
   ```bash
   # Regenerate keys
   npm run token -- --generate-keys
   ```

4. **Server Connection Issues**
   - Ensure FastMCP server is running on `http://localhost:8000/mcp`
   - Check server logs for authentication errors
   - Verify RSA keys are in the correct location

### Debug Mode

```bash
# Run with debug logging
DEBUG=* npm run client

# Or set environment variable
export DEBUG=*
npm run client
```

## 📚 API Reference

### FastMCPTokenGenerator

```typescript
class FastMCPTokenGenerator {
    constructor(privateKeyPath?: string, publicKeyPath?: string);
    loadKeys(): boolean;
    generateKeyPair(): boolean;
    createToken(options?: TokenOptions): string;
    verifyToken(token: string): JWTPayload;
}
```

### RealFastMCPClient

```typescript
class RealFastMCPClient {
    constructor(options?: ClientOptions);
    initialize(): Promise<boolean>;
    generateToken(customOptions?: TokenOptions): Promise<string>;
    refreshToken(): Promise<string>;
    getToken(): Promise<string>;
    createMCPClient(): Promise<any>;
    getTools(): Promise<any[]>;
    listTools(): Promise<any[]>;
    callTool(toolName: string, parameters?: Record<string, any>): Promise<any>;
    createAgent(modelName?: string, temperature?: number): Promise<any>;
    runAgent(message: string, modelName?: string, temperature?: number): Promise<any>;
    close(): Promise<void>;
    getStatus(): ClientStatus;
    verifyCurrentToken(): Promise<JWTPayload>;
}
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details. 