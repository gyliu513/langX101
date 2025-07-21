# FastMCP JWT Token Generator (JavaScript)

A JavaScript utility to generate JWT tokens for FastMCP authentication using RSA key pairs. This is equivalent to the Python `RSAKeyPair` functionality from the FastMCP Python SDK.

## Features

- 🔑 Generate RSA key pairs (2048-bit)
- 🔐 Create JWT tokens with RS256 signature
- ✅ Verify JWT tokens
- 🛠️ Command-line interface
- 📦 Module import support
- ⏰ Configurable expiration times
- 🎯 Customizable claims (subject, issuer, audience, scopes)

## Installation

No external dependencies required! This utility uses Node.js built-in modules (`crypto`, `fs`, `path`).

```bash
# Clone or download the files
cd fastmcp/auth

# Make sure you have Node.js 14+ installed
node --version
```

## Quick Start

### 1. Generate RSA Key Pair

```bash
# Generate new RSA key pair (creates private.pem and public.pem)
node token-generator.js --generate-keys
```

### 2. Generate JWT Token

```bash
# Generate token with default settings
node token-generator.js

# Generate token with custom settings
node token-generator.js \
  --subject "user@example.com" \
  --issuer "https://my-server.com" \
  --audience "my-mcp-server" \
  --scopes "read,write,admin" \
  --expires "2h"
```

### 3. Verify Token

```bash
# Verify an existing token
node token-generator.js --verify "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
```

## Programmatic Usage

### Basic Usage

```javascript
const { FastMCPTokenGenerator, generateFastMCPToken } = require('./token-generator');

// Method 1: Using the utility function (auto-generates keys if needed)
const token = generateFastMCPToken({
    subject: 'user@example.com',
    issuer: 'https://my-server.com',
    audience: 'my-mcp-server',
    scopes: ['read', 'write'],
    expiresIn: '1h'
});

console.log('Generated token:', token);
```

### Advanced Usage

```javascript
const { FastMCPTokenGenerator } = require('./token-generator');

// Create generator instance
const generator = new FastMCPTokenGenerator('my-private.pem', 'my-public.pem');

// Generate new key pair
generator.generateKeyPair();

// Or load existing keys
generator.loadKeys();

// Create token
const token = generator.createToken({
    subject: 'user@example.com',
    issuer: 'https://my-server.com',
    audience: 'my-mcp-server',
    scopes: ['read', 'write', 'admin'],
    expiresIn: '2h'
});

// Verify token
try {
    const payload = generator.verifyToken(token);
    console.log('Token is valid:', payload);
} catch (error) {
    console.error('Token verification failed:', error.message);
}
```

## API Reference

### FastMCPTokenGenerator Class

#### Constructor
```javascript
new FastMCPTokenGenerator(privateKeyPath = 'private.pem', publicKeyPath = 'public.pem')
```

#### Methods

##### `generateKeyPair()`
Generates a new RSA key pair and saves to files.

##### `loadKeys()`
Loads existing RSA keys from files. Returns `true` if successful.

##### `createToken(options)`
Creates a JWT token with the specified options.

**Options:**
- `subject` (string): Token subject (default: 'dev-user')
- `issuer` (string): Token issuer (default: 'http://localhost:8000')
- `audience` (string): Token audience (default: 'my-mcp-server')
- `scopes` (array): Array of scopes (default: ['read', 'write'])
- `expiresIn` (string): Expiration time (default: '1h')

**Supported time units:** `s` (seconds), `m` (minutes), `h` (hours), `d` (days)

##### `verifyToken(token)`
Verifies a JWT token and returns the payload if valid.

### Utility Functions

#### `generateFastMCPToken(options)`
Convenience function that automatically handles key generation/loading and token creation.

## Command Line Options

```bash
node token-generator.js [options]

Options:
  --help, -h           Show help
  --generate-keys      Generate new RSA key pair
  --subject <email>    Token subject
  --issuer <url>       Token issuer
  --audience <name>    Token audience
  --scopes <list>      Comma-separated scopes
  --expires <time>     Expiration time
  --verify <token>     Verify an existing token
```

## Examples

### Generate Keys and Token
```bash
# Generate new keys
node token-generator.js --generate-keys

# Generate token with custom settings
node token-generator.js \
  --subject "alice@company.com" \
  --scopes "read,write,admin" \
  --expires "8h"
```

### Using with FastMCP Server

1. **Generate keys and token:**
```bash
cd fastmcp/auth
node token-generator.js --generate-keys
node token-generator.js --subject "dev-user" --scopes "read,write"
```

2. **Use the generated token with your FastMCP client:**
```javascript
const token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."; // Generated token

// Use in your FastMCP client
const client = new FastMCPClient({
    transport: "http://localhost:8000/mcp",
    auth: {
        type: "bearer",
        token: token
    }
});
```

## Testing

Run the test suite to verify everything works:

```bash
node test.js
```

## File Structure

```
fastmcp/auth/
├── token-generator.js    # Main utility
├── test.js              # Test suite
├── package.json         # Package configuration
├── README.md           # This file
├── private.pem         # Generated private key
└── public.pem          # Generated public key
```

## Security Notes

- Keep your `private.pem` file secure and never share it
- The `public.pem` file can be shared with your FastMCP server
- Tokens are signed with RS256 (RSA-SHA256) for security
- Default expiration is 1 hour - adjust based on your security requirements

## Compatibility

- **Node.js**: 14.0.0 or higher
- **FastMCP**: Compatible with FastMCP servers using BearerAuthProvider
- **JWT**: RFC 7519 compliant
- **RSA**: 2048-bit key pairs

## Troubleshooting

### Common Issues

1. **"Private key file not found"**
   - Run `node token-generator.js --generate-keys` first

2. **"Token verification failed"**
   - Ensure you're using the correct public key for verification
   - Check if the token has expired

3. **"Invalid JWT format"**
   - Ensure the token is a valid JWT string
   - Check for any modifications to the token

### Getting Help

- Check the test file (`test.js`) for usage examples
- Verify your Node.js version is 14+ with `node --version`
- Ensure you have read/write permissions in the directory

## License

MIT License - see the main FastMCP repository for details. 