"""
End-to-end example: Generate a JWT with your private key, validate it with your public key, and show a successful validation case.

How to run:
1. Generate an RSA private key (if you don't have one):
   openssl genpkey -algorithm RSA -out private.pem -pkeyopt rsa_keygen_bits:2048
2. Generate the public key:
   openssl rsa -in private.pem -pubout -out public.pem
3. Place 'private.pem' and 'public.pem' in the same directory as this script.
4. Run:
   uv run python test_fastmcp_auth2.py
"""

import jwt
from fastmcp_auth import RSAKeyPair
from pydantic import SecretStr
from fastmcp.server.dependencies import AccessToken
import requests

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

print("Generated JWT token (self-signed):\n", jwt_token)

# Manual validation (for reference)
try:
    payload = jwt.decode(
        jwt_token,
        public_key_content,
        algorithms=["RS256"],
        issuer="http://localhost:8000",
        audience="my-mcp-server"
    )
    access_token_data = {
        "token": jwt_token,
        "client_id": payload.get("sub"),
        "scopes": payload.get("scope", "").split(),
        "expires_at": payload.get("exp"),
        "issuer": payload.get("iss"),
        "audience": payload.get("aud"),
    }
    access_token = AccessToken(**access_token_data)
    print("\n✅ Manual validation succeeded!")
    print("Extracted email from self-signed token:", access_token.client_id)
except Exception as e:
    print("\n❌ Manual validation failed:", e)

# Test the running FastMCP tool endpoint
url = "http://localhost:8000/mcp/tools/get_my_data"
headers = {
    "Authorization": f"Bearer {jwt_token}",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "X-Session-ID": "test-session"
}
jsonrpc_body = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "get_my_data",
    "params": {
        "session_id": "test-session"
    },
    "session_id": "test-session"
}
try:
    response = requests.post(url, headers=headers, json=jsonrpc_body)
    print("\nResponse from FastMCP tool:")
    print(response.status_code, response.text)
except Exception as e:
    print("\n❌ HTTP request to FastMCP tool failed:", e) 