import crypto from 'crypto';
import fs from 'fs';
import jwt from 'jsonwebtoken';

/**
 * Token options interface
 */
interface TokenOptions {
    subject?: string;
    issuer?: string;
    audience?: string;
    scopes?: string[];
    expiresIn?: string;
}

/**
 * JWT payload interface
 */
interface JWTPayload {
    sub: string;
    iss: string;
    aud: string;
    scope: string;
    iat: number;
    exp: number;
}

/**
 * FastMCP JWT Token Generator
 * 
 * This utility generates JWT tokens for FastMCP authentication using RSA key pairs.
 * It uses the jsonwebtoken npm package for reliable JWT handling.
 */
class FastMCPTokenGenerator {
    private privateKeyPath: string;
    private publicKeyPath: string;
    private privateKey: string | null;
    private publicKey: string | null;

    constructor(privateKeyPath: string = '/Users/guangyaliu/langX101/fastmcp/auth/private.pem', 
                publicKeyPath: string = '/Users/guangyaliu/langX101/fastmcp/auth/public.pem') {
        this.privateKeyPath = privateKeyPath;
        this.publicKeyPath = publicKeyPath;
        this.privateKey = null;
        this.publicKey = null;
    }

    /**
     * Load RSA keys from PEM files
     */
    loadKeys(): boolean {
        try {
            console.log('🔍 Looking for private key at:', this.privateKeyPath);
            console.log('🔍 Looking for public key at:', this.publicKeyPath);
            
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
            console.error('❌ Error loading RSA keys:', (error as Error).message);
            return false;
        }
    }

    /**
     * Generate a new RSA key pair and save to files
     * If keys already exist, they will be loaded instead
     */
    generateKeyPair(): boolean {
        try {
            console.log('🔍 Checking for existing keys...');
            console.log('🔍 Private key path:', this.privateKeyPath);
            console.log('🔍 Public key path:', this.publicKeyPath);
            
            // Check if keys already exist
            if (fs.existsSync(this.privateKeyPath) && fs.existsSync(this.publicKeyPath)) {
                console.log('🔑 RSA key pair already exists, loading existing keys...');
                return this.loadKeys();
            }

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
            console.error('❌ Error generating RSA key pair:', (error as Error).message);
            return false;
        }
    }

    /**
     * Create JWT token with RS256 signature using jsonwebtoken package
     */
    createToken(options: TokenOptions = {}): string {
        const {
            subject = 'dev-user',
            issuer = 'http://localhost:8000',
            audience = 'google-workspace-mcp',
            scopes = ['read', 'write']
        } = options;

        if (!this.privateKey) {
            throw new Error('Private key not loaded. Call loadKeys() or generateKeyPair() first.');
        }

        try {
            // Print which PEM files are being used
            console.log('🔑 Using private key from:', this.privateKeyPath);
            console.log('🔑 Using public key from:', this.publicKeyPath);
            
            // Create JWT payload
            const payload = {
                sub: subject,
                iss: issuer,
                aud: audience,
                scope: scopes.join(' ')
            };

            // Sign the token using jsonwebtoken with explicit RS256 algorithm
            // Note: expiresIn is handled by jsonwebtoken internally
            const token = jwt.sign(payload, this.privateKey!, { 
                algorithm: 'RS256',
                expiresIn: '30d' // Default to 30 days
            });

            console.log('🔐 JWT token generated successfully');
            return token;
        } catch (error) {
            console.error('❌ Error creating JWT token:', (error as Error).message);
            throw error;
        }
    }

    /**
     * Verify JWT token using jsonwebtoken package
     */
    verifyToken(token: string): JWTPayload {
        if (!this.publicKey) {
            throw new Error('Public key not loaded. Call loadKeys() or generateKeyPair() first.');
        }

        try {
            // Verify the token using jsonwebtoken
            const decoded = jwt.verify(token, this.publicKey, {
                algorithms: ['RS256']
            }) as JWTPayload;

            console.log('✅ JWT token verified successfully');
            return decoded;
        } catch (error: unknown) {
            if (error instanceof jwt.TokenExpiredError) {
                console.error('❌ Token has expired');
                throw new Error('Token has expired');
            } else if (error instanceof jwt.JsonWebTokenError) {
                console.error('❌ Invalid token:', error.message);
                throw new Error(`Invalid token: ${error.message}`);
            } else {
                console.error('❌ Error verifying JWT token:', (error as Error).message);
                throw error;
            }
        }
    }

    /**
     * Decode JWT token without verification (for debugging)
     */
    decodeToken(token: string): any {
        try {
            const decoded = jwt.decode(token, { complete: true });
            return decoded;
        } catch (error: unknown) {
            console.error('❌ Error decoding JWT token:', (error as Error).message);
            throw error;
        }
    }
}

/**
 * Utility function to generate a token with default settings
 */
function generateFastMCPToken(options: TokenOptions = {}): string {
    const generator = new FastMCPTokenGenerator();
    
    // Try to load existing keys, generate new ones if they don't exist
    if (!generator.loadKeys()) {
        console.log('📝 No existing keys found, generating new key pair...');
        generator.generateKeyPair();
    }
    
    return generator.createToken(options);
}

// Export for use as module
export {
    FastMCPTokenGenerator,
    generateFastMCPToken,
    TokenOptions,
    JWTPayload
};
