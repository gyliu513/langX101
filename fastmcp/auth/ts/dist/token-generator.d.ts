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
 * JWT header interface
 */
interface JWTHeader {
    alg: string;
    typ: string;
}
/**
 * FastMCP JWT Token Generator
 *
 * This utility generates JWT tokens for FastMCP authentication using RSA key pairs.
 * It's equivalent to the Python RSAKeyPair functionality.
 */
declare class FastMCPTokenGenerator {
    private privateKeyPath;
    private publicKeyPath;
    private privateKey;
    private publicKey;
    constructor(privateKeyPath?: string, publicKeyPath?: string);
    /**
     * Load RSA keys from PEM files
     */
    loadKeys(): boolean;
    /**
     * Generate a new RSA key pair and save to files
     * If keys already exist, they will be loaded instead
     */
    generateKeyPair(): boolean;
    /**
     * Create JWT token with RSA256 signature
     */
    createToken(options?: TokenOptions): string;
    /**
     * Parse expiresIn string to seconds
     */
    parseExpiresIn(expiresIn: string): number;
    /**
     * Base64 URL encoding (RFC 4648)
     */
    base64UrlEncode(buffer: string | Buffer): string;
    /**
     * Verify JWT token
     */
    verifyToken(token: string): JWTPayload;
    /**
     * Base64 URL decoding
     */
    base64UrlDecode(str: string): Buffer;
}
/**
 * Utility function to generate a token with default settings
 */
declare function generateFastMCPToken(options?: TokenOptions): string;
export { FastMCPTokenGenerator, generateFastMCPToken, TokenOptions, JWTPayload, JWTHeader };
//# sourceMappingURL=token-generator.d.ts.map