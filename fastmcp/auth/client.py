
import asyncio
import sys
import os
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth.providers.bearer import RSAKeyPair
from pydantic import SecretStr

async def main():
    """
    End-to-end example: Generate a JWT with your private key, validate it with your public key, and show a successful validation case.
    
    How to run:
    1. Generate an RSA private key (if you don't have one):
       openssl genpkey -algorithm RSA -out private.pem -pkeyopt rsa_keygen_bits:2048
    2. Generate the public key:
       openssl rsa -in private.pem -pubout -out public.pem
    3. Place 'private.pem' and 'public.pem' in the same directory as this script.
    4. Run:
       uv run client.py
    """
    
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

    # Generate a JWT with the required scope for my_mcp_tool.py
    test_email = "test@example.com"
    jwt_token = key_pair.create_token(
        subject=test_email,
        issuer="http://localhost:8000",
        audience="my-mcp-server",
        scopes=["data:read_sensitive"]
    )

    print("🔐 Generated JWT token (self-signed):")
    print(f"   {jwt_token[:50]}...")
    print()
    
    # Create FastMCP client with authentication
    transport = StreamableHttpTransport(
        url="http://localhost:8000/mcp",
        headers={"Authorization": f"Bearer {jwt_token}"}
    )
    client = Client(transport)
    
    try:
        # Connection is established here
        async with client:
            print(f"✅ Client connected: {client.is_connected()}")
            
            # List available tools
            tools = await client.list_tools()
            print(f"📋 Available tools: {[tool.name for tool in tools]}")
            
            # Test the greet tool
            if any(tool.name == "greet" for tool in tools):
                print("🎯 Testing greet tool...")
                result = await client.call_tool("greet", {"name": "FastMCP 2.0"})
                print(f"💬 Greet result: {result}")
            else:
                print("❌ Greet tool not found!")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        print("💡 Make sure the server is running with: uv run server.py")
        sys.exit(1)
    
    # Connection is closed automatically here
    print(f"🔌 Client disconnected: {client.is_connected()}")

if __name__ == "__main__":
    print("🚀 Starting FastMCP client with JWT authentication...")
    asyncio.run(main())
