const { FastMCPTokenGenerator, generateFastMCPToken } = require('./token-generator');

/**
 * Example: Using FastMCP Token Generator with a FastMCP Client
 * 
 * This example demonstrates how to generate JWT tokens and use them
 * with a FastMCP client for authentication.
 */

async function exampleUsage() {
    console.log('🚀 FastMCP Token Generator Example\n');

    // Example 1: Generate token with default settings
    console.log('📝 Example 1: Generate token with default settings');
    try {
        const defaultToken = generateFastMCPToken();
        console.log('✅ Default token generated:', defaultToken.substring(0, 50) + '...');
    } catch (error) {
        console.error('❌ Error generating default token:', error.message);
    }
    console.log();

    // Example 2: Generate token with custom settings
    console.log('📝 Example 2: Generate token with custom settings');
    try {
        const customToken = generateFastMCPToken({
            subject: 'alice@company.com',
            issuer: 'https://my-fastmcp-server.com',
            audience: 'production-mcp-server',
            scopes: ['read', 'write', 'admin'],
            expiresIn: '8h'
        });
        console.log('✅ Custom token generated:', customToken.substring(0, 50) + '...');
    } catch (error) {
        console.error('❌ Error generating custom token:', error.message);
    }
    console.log();

    // Example 3: Using the generator class directly
    console.log('📝 Example 3: Using generator class directly');
    try {
        const generator = new FastMCPTokenGenerator();
        
        // Load existing keys (or generate new ones if they don't exist)
        if (!generator.loadKeys()) {
            console.log('🔑 Generating new key pair...');
            generator.generateKeyPair();
        }

        // Create multiple tokens for different users
        const users = [
            { subject: 'bob@company.com', scopes: ['read'] },
            { subject: 'charlie@company.com', scopes: ['read', 'write'] },
            { subject: 'admin@company.com', scopes: ['read', 'write', 'admin'] }
        ];

        for (const user of users) {
            const token = generator.createToken({
                subject: user.subject,
                scopes: user.scopes,
                expiresIn: '4h'
            });
            console.log(`✅ Token for ${user.subject}:`, token.substring(0, 50) + '...');
        }
    } catch (error) {
        console.error('❌ Error in generator class example:', error.message);
    }
    console.log();

    // Example 4: Simulate FastMCP client usage
    console.log('📝 Example 4: Simulate FastMCP client usage');
    try {
        const token = generateFastMCPToken({
            subject: 'client@example.com',
            scopes: ['read', 'write']
        });

        // Simulate FastMCP client configuration
        const clientConfig = {
            transport: "http://localhost:8000/mcp",
            auth: {
                type: "bearer",
                token: token
            }
        };

        console.log('🔧 FastMCP Client Configuration:');
        console.log(JSON.stringify(clientConfig, null, 2));
        console.log();

        // Simulate making a request
        console.log('📡 Simulating FastMCP request...');
        console.log('Headers:');
        console.log(`  Authorization: Bearer ${token.substring(0, 50)}...`);
        console.log('  Content-Type: application/json');
        console.log();

        // Verify the token we just created
        const generator = new FastMCPTokenGenerator();
        generator.loadKeys();
        const payload = generator.verifyToken(token);
        
        console.log('✅ Token verification successful');
        console.log('📋 Token claims:');
        console.log(`  Subject: ${payload.sub}`);
        console.log(`  Issuer: ${payload.iss}`);
        console.log(`  Audience: ${payload.aud}`);
        console.log(`  Scopes: ${payload.scope}`);
        console.log(`  Expires: ${new Date(payload.exp * 1000).toISOString()}`);
    } catch (error) {
        console.error('❌ Error in client simulation:', error.message);
    }
    console.log();

    console.log('🎉 Example completed successfully!');
}

// Example: Integration with a hypothetical FastMCP client
function createFastMCPClient(token) {
    // This is a hypothetical example - replace with your actual FastMCP client
    return {
        connect: async () => {
            console.log('🔗 Connecting to FastMCP server...');
            console.log(`🔐 Using token: ${token.substring(0, 50)}...`);
            return { success: true };
        },
        
        callTool: async (toolName, params) => {
            console.log(`🛠️ Calling tool: ${toolName}`);
            console.log(`📋 Parameters:`, params);
            return { data: `Result from ${toolName}` };
        },
        
        listTools: async () => {
            console.log('📋 Listing available tools...');
            return [
                { name: 'greet', description: 'Greet a user' },
                { name: 'calculate', description: 'Perform calculations' }
            ];
        }
    };
}

// Run the example if called directly
if (require.main === module) {
    exampleUsage().catch(console.error);
}

module.exports = {
    exampleUsage,
    createFastMCPClient
}; 