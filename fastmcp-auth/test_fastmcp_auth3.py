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
from fastmcp.server.dependencies import AccessToken, get_access_token
import requests
from fastmcp import FastMCP, Context

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
