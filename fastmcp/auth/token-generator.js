const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

/**
 * FastMCP JWT Token Generator
 * 
 * This utility generates JWT tokens for FastMCP authentication using RSA key pairs.
 * It's equivalent to the Python RSAKeyPair functionality.
 */
class FastMCPTokenGenerator {
    constructor(privateKeyPath = 'private.pem', publicKeyPath = 'public.pem') {
        this.privateKeyPath = privateKeyPath;
        this.publicKeyPath = publicKeyPath;
        this.privateKey = null;
        this.publicKey = null;
    }

    /**
     * Load RSA keys from PEM files
     */
    loadKeys() {
        try {
            if (!fs.existsSync(this.privateKeyPath)) {
                throw new Error(`Private key file not found: ${this.privateKeyPath}`);
            }
            if (!fs.existsSync(this.publicKeyPath)) {
                throw new Error(`Public key file not found: ${this.publicKeyPath}`);
            }

            this.privateKey = fs.readFileSync(this.privateKeyPath, 'utf8');
            this.publicKey = fs.readFileSync(this.publicKeyPath, 'utf8');

            console.log('✅ RSA keys loaded successfully');
            return true;
        } catch (error) {
            console.error('❌ Error loading RSA keys:', error.message);
            return false;
        }
    }

    /**
     * Generate a new RSA key pair and save to files
     */
    generateKeyPair() {
        try {
            console.log('🔑 Generating new RSA key pair...');
            
            // Generate private key
            const privateKey = crypto.generateKeyPairSync('rsa', {
                modulusLength: 2048,
                publicKeyEncoding: {
                    type: 'spki',
                    format: 'pem'
                },
                privateKeyEncoding: {
                    type: 'pkcs8',
                    format: 'pem'
                }
            });

            // Save keys to files
            fs.writeFileSync(this.privateKeyPath, privateKey.privateKey);
            fs.writeFileSync(this.publicKeyPath, privateKey.publicKey);

            this.privateKey = privateKey.privateKey;
            this.publicKey = privateKey.publicKey;

            console.log('✅ RSA key pair generated and saved');
            return true;
        } catch (error) {
            console.error('❌ Error generating RSA key pair:', error.message);
            return false;
        }
    }

    /**
     * Create JWT token with RSA256 signature
     */
    createToken(options = {}) {
        const {
            subject = 'dev-user',
            issuer = 'http://localhost:8000',
            audience = 'my-mcp-server',
            scopes = ['read', 'write'],
            expiresIn = '1h'
        } = options;

        if (!this.privateKey) {
            throw new Error('Private key not loaded. Call loadKeys() or generateKeyPair() first.');
        }

        try {
            // Create JWT header
            const header = {
                alg: 'RS256',
                typ: 'JWT'
            };

            // Create JWT payload
            const now = Math.floor(Date.now() / 1000);
            const payload = {
                sub: subject,
                iss: issuer,
                aud: audience,
                scope: scopes.join(' '),
                iat: now,
                exp: now + this.parseExpiresIn(expiresIn)
            };

            // Encode header and payload
            const encodedHeader = this.base64UrlEncode(JSON.stringify(header));
            const encodedPayload = this.base64UrlEncode(JSON.stringify(payload));

            // Create signature
            const data = `${encodedHeader}.${encodedPayload}`;
            const signature = crypto.sign('RSA-SHA256', Buffer.from(data), {
                key: this.privateKey,
                padding: crypto.constants.RSA_PKCS1_PADDING
            });

            const encodedSignature = this.base64UrlEncode(signature);

            // Combine to create JWT
            const token = `${encodedHeader}.${encodedPayload}.${encodedSignature}`;

            console.log('🔐 JWT token generated successfully');
            return token;
        } catch (error) {
            console.error('❌ Error creating JWT token:', error.message);
            throw error;
        }
    }

    /**
     * Parse expiresIn string to seconds
     */
    parseExpiresIn(expiresIn) {
        const unit = expiresIn.slice(-1);
        const value = parseInt(expiresIn.slice(0, -1));

        switch (unit) {
            case 's': return value;
            case 'm': return value * 60;
            case 'h': return value * 60 * 60;
            case 'd': return value * 60 * 60 * 24;
            default: return 3600; // Default to 1 hour
        }
    }

    /**
     * Base64 URL encoding (RFC 4648)
     */
    base64UrlEncode(buffer) {
        if (typeof buffer === 'string') {
            buffer = Buffer.from(buffer);
        }
        return buffer.toString('base64')
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=/g, '');
    }

    /**
     * Verify JWT token
     */
    verifyToken(token) {
        if (!this.publicKey) {
            throw new Error('Public key not loaded. Call loadKeys() or generateKeyPair() first.');
        }

        try {
            const parts = token.split('.');
            if (parts.length !== 3) {
                throw new Error('Invalid JWT format');
            }

            const [encodedHeader, encodedPayload, encodedSignature] = parts;
            const data = `${encodedHeader}.${encodedPayload}`;
            const signature = this.base64UrlDecode(encodedSignature);

            // Verify signature
            const isValid = crypto.verify('RSA-SHA256', Buffer.from(data), {
                key: this.publicKey,
                padding: crypto.constants.RSA_PKCS1_PADDING
            }, signature);

            if (!isValid) {
                throw new Error('Invalid signature');
            }

            // Decode payload
            const payload = JSON.parse(this.base64UrlDecode(encodedPayload));
            
            // Check expiration
            const now = Math.floor(Date.now() / 1000);
            if (payload.exp && payload.exp < now) {
                throw new Error('Token has expired');
            }

            console.log('✅ JWT token verified successfully');
            return payload;
        } catch (error) {
            console.error('❌ Error verifying JWT token:', error.message);
            throw error;
        }
    }

    /**
     * Base64 URL decoding
     */
    base64UrlDecode(str) {
        str = str.replace(/-/g, '+').replace(/_/g, '/');
        while (str.length % 4) {
            str += '=';
        }
        return Buffer.from(str, 'base64');
    }
}

/**
 * Utility function to generate a token with default settings
 */
function generateFastMCPToken(options = {}) {
    const generator = new FastMCPTokenGenerator();
    
    // Try to load existing keys, generate new ones if they don't exist
    if (!generator.loadKeys()) {
        console.log('📝 Generating new key pair...');
        generator.generateKeyPair();
    }
    
    return generator.createToken(options);
}

/**
 * CLI usage example
 */
function main() {
    const args = process.argv.slice(2);
    
    if (args.includes('--help') || args.includes('-h')) {
        console.log(`
FastMCP JWT Token Generator

Usage:
  node token-generator.js [options]

Options:
  --generate-keys    Generate new RSA key pair
  --subject <email>  Token subject (default: dev-user)
  --issuer <url>     Token issuer (default: http://localhost:8000)
  --audience <name>  Token audience (default: my-mcp-server)
  --scopes <list>    Comma-separated scopes (default: read,write)
  --expires <time>   Expiration time (default: 1h)
  --verify <token>   Verify an existing token

Examples:
  node token-generator.js --generate-keys
  node token-generator.js --subject "user@example.com" --scopes "read,write,admin"
  node token-generator.js --verify "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
        `);
        return;
    }

    const generator = new FastMCPTokenGenerator();

    if (args.includes('--generate-keys')) {
        generator.generateKeyPair();
        return;
    }

    if (args.includes('--verify')) {
        const tokenIndex = args.indexOf('--verify') + 1;
        const token = args[tokenIndex];
        if (!token) {
            console.error('❌ Token required for verification');
            return;
        }
        
        if (generator.loadKeys()) {
            try {
                const payload = generator.verifyToken(token);
                console.log('📋 Token payload:', JSON.stringify(payload, null, 2));
            } catch (error) {
                console.error('❌ Token verification failed:', error.message);
            }
        }
        return;
    }

    // Parse options
    const options = {};
    const subjectIndex = args.indexOf('--subject');
    if (subjectIndex !== -1 && args[subjectIndex + 1]) {
        options.subject = args[subjectIndex + 1];
    }

    const issuerIndex = args.indexOf('--issuer');
    if (issuerIndex !== -1 && args[issuerIndex + 1]) {
        options.issuer = args[issuerIndex + 1];
    }

    const audienceIndex = args.indexOf('--audience');
    if (audienceIndex !== -1 && args[audienceIndex + 1]) {
        options.audience = args[audienceIndex + 1];
    }

    const scopesIndex = args.indexOf('--scopes');
    if (scopesIndex !== -1 && args[scopesIndex + 1]) {
        options.scopes = args[scopesIndex + 1].split(',');
    }

    const expiresIndex = args.indexOf('--expires');
    if (expiresIndex !== -1 && args[expiresIndex + 1]) {
        options.expiresIn = args[expiresIndex + 1];
    }

    // Generate token
    try {
        const token = generateFastMCPToken(options);
        console.log('\n🔐 Generated JWT Token:');
        console.log(token);
        console.log('\n📋 Token preview (first 50 chars):', token.substring(0, 50) + '...');
    } catch (error) {
        console.error('❌ Error generating token:', error.message);
    }
}

// Export for use as module
module.exports = {
    FastMCPTokenGenerator,
    generateFastMCPToken
};

// Run CLI if called directly
if (require.main === module) {
    main();
} 