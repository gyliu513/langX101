import asyncio
import os
import sys
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.client.auth import BearerAuth
from fastmcp.server.auth.providers.bearer import RSAKeyPair
from pydantic import SecretStr
import logging

# Check if key files exist
if not os.path.exists("private.pem") or not os.path.exists("public.pem"):
    print("❌ Error: private.pem and public.pem files not found!")
    print("💡 Please generate them using:")
    print("   openssl genpkey -algorithm RSA -out private.pem -pkeyopt rsa_keygen_bits:2048")
    print("   openssl rsa -in private.pem -pubout -out public.pem")
    sys.exit(1)

# Read the private key from the file
with open("private.pem", "r") as private_key_file:
    private_key_content = private_key_file.read()

# Read the public key from the file
with open("public.pem", "r") as public_key_file:
    public_key_content = public_key_file.read()

# Use the actual public key for both signing and validation
key_pair = RSAKeyPair(
    private_key=SecretStr(private_key_content),
    public_key=public_key_content
)

# Generate a JWT token
test_email = "hello@world.com"
TOKEN = key_pair.create_token(
    subject=test_email,
    issuer="http://localhost:8000",
    audience="my-mcp-server",
    scopes=["read", "write"]
)

print(f"🔐 Generated JWT token: {TOKEN[:50]}...")

# logging.basicConfig(level=logging.DEBUG)
transport = StreamableHttpTransport(
    "http://localhost:8000/mcp",
    headers={"Authorization": "Bearer " + TOKEN},
)
from fastmcp.client.logging import LogMessage

async def log_handler(message: LogMessage):
    level = message.level.upper()
    logger = message.logger or 'server'
    data = message.data
    print(f"[{level}] {logger}: {data}")

async def list_tools():
    """List all available tools from the MCP server"""
    async with Client(transport=transport, log_handler=log_handler) as client:
        try:
            tools = await client.list_tools()
            print("🔧 Available tools:")
            if not tools:
                print("   No tools available")
            else:
                for tool in tools:
                    print(f"   📋 {tool.name}")
                    if tool.description:
                        print(f"      Description: {tool.description}")
                    if tool.inputSchema:
                        print(f"      Input Schema: {tool.inputSchema}")
                    print()
            return tools
        except Exception as e:
            print(f"❌ Error listing tools: {e}")
            return []

async def call_tool(name: str):
    """Call a specific tool with given parameters"""
    async with Client(transport=transport, log_handler=log_handler) as client:
        try:
            result = await client.call_tool("greet", {"name": name})
            print(f"✅ Result: {result.data}")
            return result
        except Exception as e:
            print(f"❌ Error calling tool: {e}")
            return None

async def main():
    """Main function to demonstrate both listing tools and calling a tool"""
    print("🚀 Starting FastMCP client with JWT authentication...")
    
    # First, list all available tools
    print("\n" + "="*50)
    print("📋 LISTING AVAILABLE TOOLS")
    print("="*50)
    tools = await list_tools()
    
    # Then call a specific tool
    print("\n" + "="*50)
    print("🎯 CALLING SPECIFIC TOOL")
    print("="*50)
    await call_tool("World")

if __name__ == "__main__":
    asyncio.run(main())
