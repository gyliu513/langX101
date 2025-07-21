import fs from 'fs';
import path from 'path';
import jwt from 'jsonwebtoken';
import { FastMCPTokenGenerator, TokenOptions } from './token-generator';

// Test configuration
const TEST_PRIVATE_KEY_PATH = path.join(__dirname, 'test-private.pem');
const TEST_PUBLIC_KEY_PATH = path.join(__dirname, 'test-public.pem');

describe('FastMCPTokenGenerator', () => {
  let generator: FastMCPTokenGenerator;
  let originalConsoleLog: any;
  let originalConsoleError: any;

  beforeEach(() => {
    // Store original console methods
    originalConsoleLog = console.log;
    originalConsoleError = console.error;
    
    // Create a new generator instance for each test
    generator = new FastMCPTokenGenerator(TEST_PRIVATE_KEY_PATH, TEST_PUBLIC_KEY_PATH);
  });

  afterEach(() => {
    // Restore original console methods
    console.log = originalConsoleLog;
    console.error = originalConsoleError;
    
    // Clean up test files
    if (fs.existsSync(TEST_PRIVATE_KEY_PATH)) {
      fs.unlinkSync(TEST_PRIVATE_KEY_PATH);
    }
    if (fs.existsSync(TEST_PUBLIC_KEY_PATH)) {
      fs.unlinkSync(TEST_PUBLIC_KEY_PATH);
    }
  });

  describe('Constructor', () => {
    test('should initialize with default paths', () => {
      const defaultGenerator = new FastMCPTokenGenerator();
      expect(defaultGenerator).toBeInstanceOf(FastMCPTokenGenerator);
    });

    test('should initialize with custom paths', () => {
      const customGenerator = new FastMCPTokenGenerator('/custom/private.pem', '/custom/public.pem');
      expect(customGenerator).toBeInstanceOf(FastMCPTokenGenerator);
    });
  });

  describe('generateKeyPair', () => {
    test('should generate new RSA key pair when files do not exist', () => {
      const result = generator.generateKeyPair();
      expect(result).toBe(true);
      expect(fs.existsSync(TEST_PRIVATE_KEY_PATH)).toBe(true);
      expect(fs.existsSync(TEST_PUBLIC_KEY_PATH)).toBe(true);
    });

    test('should load existing keys when files already exist', () => {
      // First, generate keys
      generator.generateKeyPair();
      
      // Create a new generator instance
      const newGenerator = new FastMCPTokenGenerator(TEST_PRIVATE_KEY_PATH, TEST_PUBLIC_KEY_PATH);
      
      // Should load existing keys instead of generating new ones
      const result = newGenerator.generateKeyPair();
      expect(result).toBe(true);
    });

    test('should handle errors gracefully', () => {
      // Mock fs.writeFileSync to throw an error
      const originalWriteFileSync = fs.writeFileSync;
      fs.writeFileSync = jest.fn().mockImplementation(() => {
        throw new Error('Write error');
      });

      const result = generator.generateKeyPair();
      expect(result).toBe(false);

      // Restore original method
      fs.writeFileSync = originalWriteFileSync;
    });
  });

  describe('loadKeys', () => {
    test('should load existing keys successfully', () => {
      // First generate keys
      generator.generateKeyPair();
      
      // Then test loading
      const result = generator.loadKeys();
      expect(result).toBe(true);
    });

    test('should return false when private key file does not exist', () => {
      const result = generator.loadKeys();
      expect(result).toBe(false);
    });

    test('should return false when public key file does not exist', () => {
      // Create only private key file
      generator.generateKeyPair();
      fs.unlinkSync(TEST_PUBLIC_KEY_PATH);
      
      const result = generator.loadKeys();
      expect(result).toBe(false);
    });
  });

  describe('createToken', () => {
    beforeEach(() => {
      // Generate keys before testing token creation
      generator.generateKeyPair();
    });

    test('should create a valid JWT token with default options', () => {
      const token = generator.createToken();
      
      expect(token).toBeDefined();
      expect(typeof token).toBe('string');
      expect(token.split('.').length).toBe(3); // JWT has 3 parts
    });

    test('should create a valid JWT token with custom options', () => {
      const options: TokenOptions = {
        subject: 'test-user@example.com',
        issuer: 'https://test.example.com',
        audience: 'test-audience',
        scopes: ['read', 'write', 'admin']
      };

      const token = generator.createToken(options);
      
      expect(token).toBeDefined();
      expect(typeof token).toBe('string');
      
      // Decode token to verify payload
      const decoded = jwt.decode(token) as any;
      expect(decoded.sub).toBe('test-user@example.com');
      expect(decoded.iss).toBe('https://test.example.com');
      expect(decoded.aud).toBe('test-audience');
      expect(decoded.scope).toBe('read write admin');
    });

    test('should throw error when private key is not loaded', () => {
      const emptyGenerator = new FastMCPTokenGenerator(TEST_PRIVATE_KEY_PATH, TEST_PUBLIC_KEY_PATH);
      
      expect(() => {
        emptyGenerator.createToken();
      }).toThrow('Private key not loaded. Call loadKeys() or generateKeyPair() first.');
    });

    test('should create token with RS256 algorithm', () => {
      const token = generator.createToken();
      
      // Decode header to verify algorithm
      const header = jwt.decode(token, { complete: true }) as any;
      expect(header.header.alg).toBe('RS256');
      expect(header.header.typ).toBe('JWT');
    });
  });

  describe('verifyToken', () => {
    let validToken: string;

    beforeEach(() => {
      generator.generateKeyPair();
      validToken = generator.createToken();
    });

    test('should verify a valid token successfully', () => {
      const payload = generator.verifyToken(validToken);
      
      expect(payload).toBeDefined();
      expect(payload.sub).toBe('dev-user');
      expect(payload.iss).toBe('http://localhost:8000');
      expect(payload.aud).toBe('google-workspace-mcp');
      expect(payload.scope).toBe('read write');
      expect(payload.iat).toBeDefined();
      expect(payload.exp).toBeDefined();
    });

    test('should throw error when public key is not loaded', () => {
      const emptyGenerator = new FastMCPTokenGenerator(TEST_PRIVATE_KEY_PATH, TEST_PUBLIC_KEY_PATH);
      
      expect(() => {
        emptyGenerator.verifyToken(validToken);
      }).toThrow('Public key not loaded. Call loadKeys() or generateKeyPair() first.');
    });

    test('should throw error for invalid token format', () => {
      expect(() => {
        generator.verifyToken('invalid.token.format');
      }).toThrow();
    });

    test('should throw error for tampered token', () => {
      const tamperedToken = validToken.substring(0, validToken.length - 10) + 'tampered';
      
      expect(() => {
        generator.verifyToken(tamperedToken);
      }).toThrow();
    });

    test('should throw error for token signed with different key', () => {
      // Create a different generator with different keys
      const otherGenerator = new FastMCPTokenGenerator(
        path.join(__dirname, 'other-private.pem'),
        path.join(__dirname, 'other-public.pem')
      );
      otherGenerator.generateKeyPair();
      
      const otherToken = otherGenerator.createToken();
      
      expect(() => {
        generator.verifyToken(otherToken);
      }).toThrow();
      
      // Clean up
      if (fs.existsSync(path.join(__dirname, 'other-private.pem'))) {
        fs.unlinkSync(path.join(__dirname, 'other-private.pem'));
      }
      if (fs.existsSync(path.join(__dirname, 'other-public.pem'))) {
        fs.unlinkSync(path.join(__dirname, 'other-public.pem'));
      }
    });
  });

  describe('decodeToken', () => {
    let validToken: string;

    beforeEach(() => {
      generator.generateKeyPair();
      validToken = generator.createToken();
    });

    test('should decode token without verification', () => {
      const decoded = generator.decodeToken(validToken);
      
      expect(decoded).toBeDefined();
      expect(decoded.header).toBeDefined();
      expect(decoded.payload).toBeDefined();
      expect(decoded.header.alg).toBe('RS256');
      expect(decoded.header.typ).toBe('JWT');
    });

    test('should handle invalid token format', () => {
      const result = generator.decodeToken('invalid.token');
      expect(result).toBeNull();
    });
  });

  describe('Integration Tests', () => {
    test('should create and verify token end-to-end', () => {
      // Generate keys
      generator.generateKeyPair();
      
      // Create token
      const token = generator.createToken({
        subject: 'integration-test@example.com',
        scopes: ['read', 'write']
      });
      
      // Verify token
      const payload = generator.verifyToken(token);
      
      expect(payload.sub).toBe('integration-test@example.com');
      expect(payload.scope).toBe('read write');
    });

    test('should handle token with custom audience and issuer', () => {
      generator.generateKeyPair();
      
      const token = generator.createToken({
        subject: 'custom-user',
        issuer: 'https://custom-issuer.com',
        audience: 'custom-audience'
      });
      
      const payload = generator.verifyToken(token);
      
      expect(payload.iss).toBe('https://custom-issuer.com');
      expect(payload.aud).toBe('custom-audience');
    });
  });
});

describe('generateFastMCPToken', () => {
  test('should generate token with default settings', () => {
    const { generateFastMCPToken } = require('./token-generator');
    const token = generateFastMCPToken();
    
    expect(token).toBeDefined();
    expect(typeof token).toBe('string');
    expect(token.split('.').length).toBe(3);
  });

  test('should generate token with custom options', () => {
    const { generateFastMCPToken } = require('./token-generator');
    const token = generateFastMCPToken({
      subject: 'custom-subject',
      scopes: ['admin']
    });
    
    expect(token).toBeDefined();
    
    // Decode to verify custom options
    const decoded = jwt.decode(token) as any;
    expect(decoded.sub).toBe('custom-subject');
    expect(decoded.scope).toBe('admin');
  });
}); 