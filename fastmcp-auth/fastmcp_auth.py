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
from fastmcp.server.dependencies import get_access_token, AccessToken


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
        except Exception:
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
            return getattr(access_token, 'email', None) or getattr(access_token, 'client_id', None)
        except Exception:
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