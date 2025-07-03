# From https://github.com/jlowin/fastmcp/issues/963
# Updated to work with local JWT authentication

from fastmcp import FastMCP, Context
from fastmcp.server.auth import BearerAuthProvider
from fastmcp.server.dependencies import get_access_token, AccessToken
from fastmcp.server.middleware.logging import (
    LoggingMiddleware,
)
from fastmcp.server.middleware.error_handling import (
    ErrorHandlingMiddleware,
)
from fastmcp.server.auth.providers.bearer import RSAKeyPair
import logging
import asyncio
import os
import sys
from pydantic import SecretStr

# Check if key files exist
if not os.path.exists("private.pem") or not os.path.exists("public.pem"):
    print("❌ Error: private.pem and public.pem files not found!")
    print("💡 Please generate them using:")
    print("   openssl genpkey -algorithm RSA -out private.pem -pkeyopt rsa_keygen_bits:2048")
    print("   openssl rsa -in private.pem -pubout -out public.pem")
    sys.exit(1)

# Read the public key from the file
with open("public.pem", "r") as public_key_file:
    public_key_content = public_key_file.read()

# Configure the auth provider with the public key
auth = BearerAuthProvider(
    public_key=public_key_content,
    issuer="http://localhost:8000",
    audience="my-mcp-server"
)

logging.basicConfig(level=logging.DEBUG)
mcp = FastMCP(name="My MCP Server", auth=auth)
mcp.add_middleware(LoggingMiddleware())
mcp.add_middleware(ErrorHandlingMiddleware(
    include_traceback=True,
    transform_errors=True,
))

@mcp.tool()
def greet(name: str, ctx: Context) -> str:
    access_token: AccessToken = get_access_token()
    print(f"Access Token: {access_token.json}")
    user_id = access_token.client_id

    return f"Hello, {name}! Your userid is {user_id}."

async def main():
    print("Starting FastMCP server on http://localhost:8000/mcp")
    print("Available tools: greet")
    await mcp.run_http_async(transport="streamable-http", log_level="debug")

if __name__ == "__main__":
    asyncio.run(main())