"""
FastMCP Authentication Module

This module provides JWT token generation, validation, and access token claims
using FastMCP's BearerAuthProvider and RSAKeyPair utilities.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union
from dataclasses import dataclass
import jwt
import requests

# FastMCP imports
from fastmcp.server.auth import BearerAuthProvider
from fastmcp.server.auth.providers.bearer import RSAKeyPair
from fastmcp.server.dependencies import get_access_token


@dataclass
class AccessToken:
    """Represents an access token with claims and metadata."""
    token: str
    client_id: str
    email: Optional[str] = None
    scopes: List[str] = None
    expires_at: Optional[datetime] = None
    issuer: Optional[str] = None
    audience: Optional[str] = None
    additional_claims: Optional[Dict] = None

    def __post_init__(self):
        if self.scopes is None:
            self.scopes = []

    @classmethod
    def from_jwt(cls, token: str, verify_signature: bool = True, 
                 public_key: Optional[str] = None, jwks_uri: Optional[str] = None,
                 issuer: Optional[str] = None, audience: Optional[str] = None,
                 algorithm: str = "RS256") -> "AccessToken":
        """
        Create an AccessToken instance from a JWT token.
        
        Args:
            token: The JWT token string
            verify_signature: Whether to verify the token signature
            public_key: Public key for signature verification
            jwks_uri: JWKS URI for key lookup
            issuer: Expected issuer
            audience: Expected audience
            algorithm: JWT algorithm
            
        Returns:
            AccessToken instance
            
        Raises:
            jwt.InvalidTokenError: If token is invalid
        """
        try:
            if verify_signature:
                if jwks_uri:
                    # Fetch keys from JWKS
                    keys = cls._fetch_jwks(jwks_uri)
                    payload = None
                    for key in keys:
                        try:
                            payload = jwt.decode(
                                token, 
                                key, 
                                algorithms=[algorithm],
                                issuer=issuer,
                                audience=audience,
                                options={"verify_signature": True}
                            )
                            break
                        except jwt.InvalidTokenError:
                            continue
                    if payload is None:
                        raise jwt.InvalidTokenError("No valid key found in JWKS")
                elif public_key:
                    payload = jwt.decode(
                        token,
                        public_key,
                        algorithms=[algorithm],
                        issuer=issuer,
                        audience=audience,
                        options={"verify_signature": True}
                    )
                else:
                    raise ValueError("Either public_key or jwks_uri must be provided for signature verification")
            else:
                payload = jwt.decode(token, options={"verify_signature": False})
            
            # Extract claims
            client_id = payload.get('sub') or payload.get('client_id', 'unknown')
            email = payload.get('email') or payload.get('email_verified') or client_id
            scopes = payload.get('scope', '').split() if isinstance(payload.get('scope'), str) else payload.get('scopes', [])
            expires_at = datetime.fromtimestamp(payload['exp']) if 'exp' in payload else None
            
            return cls(
                token=token,
                client_id=client_id,
                email=email,
                scopes=scopes,
                expires_at=expires_at,
                issuer=payload.get('iss'),
                audience=payload.get('aud'),
                additional_claims={k: v for k, v in payload.items() 
                                 if k not in ['sub', 'client_id', 'email', 'scope', 'scopes', 'exp', 'iss', 'aud', 'iat']}
            )
        except jwt.InvalidTokenError as e:
            raise jwt.InvalidTokenError(f"Invalid token: {str(e)}")
    
    @staticmethod
    def _fetch_jwks(jwks_uri: str) -> List[str]:
        """Fetch public keys from JWKS endpoint."""
        try:
            response = requests.get(jwks_uri, timeout=10)
            response.raise_for_status()
            jwks = response.json()
            
            keys = []
            for key_data in jwks.get('keys', []):
                # Convert JWK to PEM format
                if key_data.get('kty') == 'RSA':
                    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
                    from cryptography.hazmat.primitives import serialization
                    from cryptography.hazmat.backends import default_backend
                    
                    # Extract RSA components
                    n = int.from_bytes(jwt.utils.base64url_decode(key_data['n']), 'big')
                    e = int.from_bytes(jwt.utils.base64url_decode(key_data['e']), 'big')
                    
                    # Create RSA public numbers
                    public_numbers = RSAPublicNumbers(e, n)
                    public_key = public_numbers.public_key(backend=default_backend())
                    
                    # Serialize to PEM
                    pem = public_key.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo
                    )
                    keys.append(pem.decode('utf-8'))
            
            return keys
        except Exception as e:
            raise ValueError(f"Failed to fetch JWKS: {str(e)}")


class TokenValidator:
    """Token validation utility class using FastMCP BearerAuthProvider."""
    
    def __init__(self, 
                 public_key: Optional[str] = None,
                 jwks_uri: Optional[str] = None,
                 issuer: Optional[str] = None,
                 audience: Optional[str] = None,
                 algorithm: str = "RS256",
                 required_scopes: Optional[List[str]] = None):
        """
        Initialize token validator.
        
        Args:
            public_key: Public key for signature verification
            jwks_uri: JWKS URI for key lookup
            issuer: Expected issuer
            audience: Expected audience
            algorithm: JWT algorithm
            required_scopes: Required scopes for all requests
        """
        if not public_key and not jwks_uri:
            raise ValueError("Either public_key or jwks_uri must be provided")
        
        self.public_key = public_key
        self.jwks_uri = jwks_uri
        self.issuer = issuer
        self.audience = audience
        self.algorithm = algorithm
        self.required_scopes = required_scopes or []
    
    def validate_token(self, token: str) -> AccessToken:
        """
        Validate a JWT token and return AccessToken.
        
        Args:
            token: JWT token string
            
        Returns:
            AccessToken instance
            
        Raises:
            jwt.InvalidTokenError: If token is invalid
            ValueError: If token doesn't meet requirements
        """
        access_token = AccessToken.from_jwt(
            token=token,
            verify_signature=True,
            public_key=self.public_key,
            jwks_uri=self.jwks_uri,
            issuer=self.issuer,
            audience=self.audience,
            algorithm=self.algorithm
        )
        
        # Check required scopes
        if self.required_scopes:
            missing_scopes = set(self.required_scopes) - set(access_token.scopes)
            if missing_scopes:
                raise ValueError(f"Missing required scopes: {missing_scopes}")
        
        return access_token
    
    def is_token_valid(self, token: str) -> bool:
        """
        Check if token is valid without raising exceptions.
        
        Args:
            token: JWT token string
            
        Returns:
            True if token is valid, False otherwise
        """
        try:
            self.validate_token(token)
            return True
        except (jwt.InvalidTokenError, ValueError):
            return False
    
    def extract_email(self, token: str) -> Optional[str]:
        """
        Extract email from JWT token.
        
        Args:
            token: JWT token string
            
        Returns:
            Email address or None if not found
        """
        try:
            access_token = self.validate_token(token)
            return access_token.email
        except (jwt.InvalidTokenError, ValueError):
            return None


def create_test_key_pair() -> RSAKeyPair:
    """Create a test RSA key pair for development using FastMCP's RSAKeyPair."""
    return RSAKeyPair.generate()


def create_test_token(key_pair: RSAKeyPair, 
                     subject: str = "gyliu513@gmail.com",
                     scopes: Optional[List[str]] = None) -> str:
    """Create a test token for development using FastMCP's RSAKeyPair."""
    return key_pair.create_token(
        subject=subject,
        issuer=DEFAULT_CONFIG["issuer"],
        audience=DEFAULT_CONFIG["audience"],
        scopes=scopes or DEFAULT_CONFIG["default_scopes"],
        expires_in_seconds=DEFAULT_CONFIG["token_expiry"]
    )


def create_bearer_auth_provider(public_key: Optional[str] = None,
                               jwks_uri: Optional[str] = None,
                               issuer: Optional[str] = None,
                               audience: Optional[str] = None,
                               algorithm: str = "RS256",
                               required_scopes: Optional[List[str]] = None) -> BearerAuthProvider:
    """
    Create a BearerAuthProvider for FastMCP server.
    
    Args:
        public_key: Public key for signature verification
        jwks_uri: JWKS URI for key lookup
        issuer: Expected issuer
        audience: Expected audience
        algorithm: JWT algorithm
        required_scopes: Required scopes for all requests
        
    Returns:
        BearerAuthProvider instance
    """
    return BearerAuthProvider(
        public_key=public_key,
        jwks_uri=jwks_uri,
        issuer=issuer,
        audience=audience,
        algorithm=algorithm,
        required_scopes=required_scopes
    )


def create_google_bearer_auth_provider() -> BearerAuthProvider:
    """Create a BearerAuthProvider using Google's public key."""
    return BearerAuthProvider(
        jwks_uri=GOOGLE_PUBLIC_KEY_URI,
        issuer="https://accounts.google.com",
        algorithm="RS256"
    )


def get_current_access_token() -> Optional[AccessToken]:
    """
    Get the current access token from FastMCP context.
    This function uses FastMCP's get_access_token dependency.
    """
    try:
        # This would be used within a FastMCP tool context
        access_token = get_access_token()
        return access_token
    except Exception:
        # Return None if not in FastMCP context
        return None


# Google's public key for testing
GOOGLE_PUBLIC_KEY_URI = "https://www.googleapis.com/service_accounts/v1/jwk/gsuitecse-tokenissuer-drive@system.gserviceaccount.com"

# Default configuration
DEFAULT_CONFIG = {
    "issuer": "https://fastmcp.example.com",
    "audience": "fastmcp-server",
    "algorithm": "RS256",
    "default_scopes": ["read", "write"],
    "token_expiry": 3600,  # 1 hour
    "default_email": "gyliu513@gmail.com"
} 