const { FastMCPTokenGenerator, generateFastMCPToken } = require('./token-generator');

/**
 * Test script to demonstrate FastMCP JWT token generation
 */
async function runTests() {
    console.log('🧪 Testing FastMCP JWT Token Generator\n');

    // Test 1: Generate new key pair
    console.log('📝 Test 1: Generating new RSA key pair');
    const generator = new FastMCPTokenGenerator();
    generator.generateKeyPair();
    console.log('✅ Key pair generated successfully\n');

    // Test 2: Load keys and generate token
    console.log('🔐 Test 2: Loading keys and generating token');
    generator.loadKeys();
    const token = generator.createToken({
        subject: 'test-user@example.com',
        issuer: 'http://localhost:8000',
        audience: 'my-mcp-server',
        scopes: ['read', 'write', 'admin'],
        expiresIn: '2h'
    });
    console.log('✅ Token generated:', token.substring(0, 50) + '...\n');

    // Test 3: Verify token
    console.log('🔍 Test 3: Verifying generated token');
    try {
        const payload = generator.verifyToken(token);
        console.log('✅ Token verified successfully');
        console.log('📋 Token payload:', JSON.stringify(payload, null, 2));
    } catch (error) {
        console.error('❌ Token verification failed:', error.message);
    }
    console.log();

    // Test 4: Generate token with utility function
    console.log('🛠️ Test 4: Using utility function');
    try {
        const utilityToken = generateFastMCPToken({
            subject: 'utility-user@example.com',
            scopes: ['read']
        });
        console.log('✅ Utility token generated:', utilityToken.substring(0, 50) + '...');
    } catch (error) {
        console.error('❌ Utility function failed:', error.message);
    }
    console.log();

    // Test 5: Test with different expiration times
    console.log('⏰ Test 5: Testing different expiration times');
    const expirationTests = ['30s', '5m', '1h', '1d'];
    
    for (const expiresIn of expirationTests) {
        try {
            const testToken = generator.createToken({ expiresIn });
            const payload = generator.verifyToken(testToken);
            console.log(`✅ ${expiresIn} expiration works - expires at: ${new Date(payload.exp * 1000).toISOString()}`);
        } catch (error) {
            console.error(`❌ ${expiresIn} expiration failed:`, error.message);
        }
    }
    console.log();

    console.log('🎉 All tests completed!');
}

// Run tests if called directly
if (require.main === module) {
    runTests().catch(console.error);
}

module.exports = { runTests }; 