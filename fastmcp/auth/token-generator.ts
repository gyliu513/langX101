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
 * FastMCP JWT Token Generator
 *
 * This utility generates JWT tokens for FastMCP authentication using private key.
 * It uses the jsonwebtoken npm package for reliable JWT handling.
 */
class JWTTokenGenerator {
  private privateKeyPath: string;
  private privateKey: string | null;

  constructor(privateKeyPath: string = '/etc/keys/private.pem') {
    this.privateKeyPath = privateKeyPath;
    this.privateKey = null;
  }

  /**
   * Load private key from PEM files
   */
  loadPrivateKey(): boolean {
    try {
      if (!fs.existsSync(this.privateKeyPath)) {
        throw new Error(`Private key file not found: ${this.privateKeyPath}`);
      }

      this.privateKey = fs.readFileSync(this.privateKeyPath, 'utf8');

      console.log(
        `✅ Private key loaded successfully from: ${this.privateKeyPath}`
      );
      return true;
    } catch (error) {
      console.error('❌ Error loading private key:', (error as Error).message);
      return false;
    }
  }

  /**
   * Create JWT token with RS256 signature using jsonwebtoken package
   */
  createToken(options: TokenOptions = {}): string {
    const { subject = 'dev-user' } = options;

    if (!this.privateKey) {
      throw new Error('Private key not loaded. Call loadPrivateKey() first.');
    }

    try {
      // Print which PEM files are being used
      console.log('🔑 Using private key from:', this.privateKeyPath);

      // Create JWT payload
      const payload = {
        sub: subject,
      };

      // Sign the token using jsonwebtoken with explicit RS256 algorithm
      // Note: expiresIn is handled by jsonwebtoken internally
      const token = jwt.sign(payload, this.privateKey!, {
        algorithm: 'RS256',
        expiresIn: '30d', // Default to 30 days
      });

      console.log('🔐 JWT token generated successfully');
      return token;
    } catch (error) {
      console.error('❌ Error creating JWT token:', (error as Error).message);
      throw error;
    }
  }
}

/**
 * Utility function to generate a token with default settings
 */
function generateFastMCPToken(
  options: TokenOptions = {},
  privateKeyPath: string = '/etc/keys/private.pem'
): string {
  const generator = new JWTTokenGenerator(privateKeyPath);

  // Try to load existing keys, throw exception if they don't exist
  if (!generator.loadPrivateKey()) {
    throw new Error(
      `No private key found at path: ${privateKeyPath}. Please ensure the private key file exists at the specified path.`
    );
  }

  return generator.createToken(options);
}

// Export for use as module
export { JWTTokenGenerator, generateFastMCPToken, TokenOptions };
