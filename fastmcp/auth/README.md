# FastMCP Auth Reference

A reference implementation of FastMCP with JWT authentication, based on the example from [FastMCP issue #963](https://github.com/jlowin/fastmcp/issues/963).

## Prerequisites

- Python 3.10 or higher
- `uv` package manager (install from https://docs.astral.sh/uv/getting-started/installation/)
- OpenSSL (for generating RSA keys)

## Quick Start

### 1. Navigate to the Project Directory

```bash
cd /Users/guangyaliu/go/src/github.com/gyliu513/langX101/fastmcp/auth_reference
```

### 2. Install Dependencies

```bash
uv sync --extra dev
```

This installs all required dependencies including:
- `fastmcp` - The main FastMCP library
- `PyJWT` - JWT token handling
- `pydantic` - Data validation

### 3. Generate RSA Keys for JWT Authentication

```bash
# Generate private key
openssl genpkey -algorithm RSA -out private.pem -pkeyopt rsa_keygen_bits:2048

# Generate public key
openssl rsa -in private.pem -pubout -out public.pem
```

### 4. Start the Server

In your terminal, run:

```bash
uv run server.py
```

You should see:
```
Starting FastMCP server on http://localhost:8000/mcp
Available tools: greet
```

The server is now running with JWT authentication enabled.

### 5. Test the Client

Open a **new terminal window** and navigate to the same directory:

```bash
cd /Users/guangyaliu/go/src/github.com/gyliu513/langX101/fastmcp/auth_reference
```

Then run the client:

```bash
uv run client.py
```

You should see output like:
```
🚀 Starting FastMCP client with JWT authentication...
🔐 Generated JWT token: eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
✅ Result: Hello, Shane! Your userid is test@example.com.
```

## What's Happening

1. **Server**: 
   - Uses `BearerAuthProvider` with local RSA public key
   - Validates JWT tokens automatically
   - Extracts user information from tokens
   - Includes logging and error handling middleware

2. **Client**: 
   - Generates JWT tokens using RSA private key
   - Sends tokens in Authorization header
   - Connects to server and calls authenticated tools

3. **Authentication**: 
   - JWT tokens are validated using RSA signature verification
   - User information is extracted from token claims
   - Server logs access token information

## Key Features

- **Local JWT Authentication**: Uses RSA key pairs instead of external JWKS
- **Middleware Support**: Includes logging and error handling middleware
- **Debug Logging**: Comprehensive logging for debugging authentication issues
- **Proper Error Handling**: Graceful error handling with detailed messages

## Project Structure

```
fastmcp/auth_reference/
├── server.py          # FastMCP server with JWT auth
├── client.py          # Client with JWT token generation
├── __init__.py        # Makes this a Python package
├── pyproject.toml     # Project configuration and dependencies
├── private.pem        # RSA private key (generate this)
├── public.pem         # RSA public key (generate this)
└── README.md          # This file
```

## Troubleshooting

### "private.pem and public.pem files not found" Error
Generate the RSA keys:
```bash
openssl genpkey -algorithm RSA -out private.pem -pkeyopt rsa_keygen_bits:2048
openssl rsa -in private.pem -pubout -out public.pem
```

### "No module named 'fastmcp'" Error
Install dependencies:
```bash
uv sync --extra dev
```

### Authentication Errors
Make sure the server and client are using the same:
- Issuer: `http://localhost:8000`
- Audience: `my-mcp-server`
- RSA key pair

## Differences from Original

This implementation differs from the original reference in several ways:

1. **Local Authentication**: Uses local RSA keys instead of external JWKS
2. **Token Generation**: Client generates its own JWT tokens
3. **Simplified Setup**: No external authentication service required
4. **Better Error Messages**: More descriptive error handling

## Resources

- [FastMCP Documentation](https://fastmcp.com/)
- [Original Issue #963](https://github.com/jlowin/fastmcp/issues/963)
- [JWT Authentication](https://jwt.io/)
- [uv Package Manager](https://docs.astral.sh/uv/) 