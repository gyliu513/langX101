"""
Test script for FastMCP Authentication Module

This script tests all the authentication functionality including:
- JWT token generation with email as subject (gyliu513@gmail.com)
- Token validation using FastMCP BearerAuthProvider
- Access token claims extraction
- Google public key integration
"""

import sys
import os
import time

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastmcp_auth import (
    RSAKeyPair, 
    AccessToken, 
    TokenValidator, 
    create_test_key_pair,
    create_test_token,
    create_bearer_auth_provider,
    create_google_bearer_auth_provider,
    GOOGLE_PUBLIC_KEY_URI,
    DEFAULT_CONFIG
)


def test_key_pair_generation():
    """Test RSA key pair generation using FastMCP's RSAKeyPair."""
    print("🔑 Testing RSA Key Pair Generation...")
    
    try:
        # Generate a new key pair using FastMCP's RSAKeyPair
        key_pair = create_test_key_pair()
        
        # Test public key PEM format
        public_key_pem = key_pair.public_key
        assert public_key_pem.startswith("-----BEGIN PUBLIC KEY-----")
        assert public_key_pem.endswith("-----END PUBLIC KEY-----\n")
        
        print("✅ Key pair generation successful")
        return key_pair
        
    except Exception as e:
        print(f"❌ Key pair generation failed: {e}")
        return None


def test_token_creation_with_email(key_pair):
    """Test JWT token creation with email as subject."""
    print("\n🎫 Testing Token Creation with Email...")
    
    try:
        # Create a token with default email (test@example.com)
        token = create_test_token(key_pair, subject="test@example.com")
        
        # Verify token is not empty
        assert token and len(token) > 0
        print(f"✅ Default email token created: {token[:50]}...")
        
        # Create token with custom email
        custom_email = "test.user@example.com"
        token_with_custom_email = key_pair.create_token(
            subject=custom_email,
            issuer=DEFAULT_CONFIG["issuer"],
            audience=DEFAULT_CONFIG["audience"],
            scopes=["read", "write", "admin"],
            expires_in_seconds=7200,  # 2 hours
            additional_claims={"role": "admin", "department": "engineering"}
        )
        
        assert token_with_custom_email and len(token_with_custom_email) > 0
        print(f"✅ Custom email token created: {token_with_custom_email[:50]}...")
        
        return token, token_with_custom_email
        
    except Exception as e:
        print(f"❌ Token creation failed: {e}")
        return None, None


def test_token_validation_and_email_extraction(key_pair, token, custom_token):
    """Test token validation and email extraction."""
    print("\n🔍 Testing Token Validation and Email Extraction...")
    
    try:
        # Create validator with the public key
        validator = TokenValidator(
            public_key=key_pair.public_key,
            issuer=DEFAULT_CONFIG["issuer"],
            audience=DEFAULT_CONFIG["audience"],
            algorithm="RS256"
        )
        
        # Validate basic token and extract email
        access_token = validator.validate_token(token)
        assert access_token.client_id == "test@example.com"
        assert access_token.email == "test@example.com"
        assert "read" in access_token.scopes
        assert "write" in access_token.scopes
        print("✅ Basic token validation and email extraction successful")
        
        # Validate custom token and extract email
        custom_access_token = validator.validate_token(custom_token)
        assert custom_access_token.client_id == "test.user@example.com"
        assert custom_access_token.email == "test.user@example.com"
        assert "admin" in custom_access_token.scopes
        assert custom_access_token.additional_claims.get("role") == "admin"
        print("✅ Custom token validation and email extraction successful")
        
        # Test email extraction method
        email = validator.extract_email(token)
        assert email == "test@example.com"
        print("✅ Email extraction method successful")
        
        # Test invalid token
        invalid_token = "invalid.token.here"
        try:
            validator.validate_token(invalid_token)
            print("❌ Invalid token validation should have failed")
        except Exception:
            print("✅ Invalid token correctly rejected")
        
        # Test email extraction from invalid token
        invalid_email = validator.extract_email(invalid_token)
        assert invalid_email is None
        print("✅ Invalid token email extraction correctly returns None")
        
        return validator, access_token, custom_access_token
        
    except Exception as e:
        print(f"❌ Token validation failed: {e}")
        return None, None, None


def test_bearer_auth_provider_creation():
    """Test BearerAuthProvider creation."""
    print("\n🔧 Testing BearerAuthProvider Creation...")
    
    try:
        # Create BearerAuthProvider with public key
        key_pair = create_test_key_pair()
        auth_provider = create_bearer_auth_provider(
            public_key=key_pair.public_key,
            issuer="https://test.example.com",
            audience="test-server",
            required_scopes=["read"]
        )
        
        assert auth_provider is not None
        print("✅ BearerAuthProvider with public key created successfully")
        
        # Create BearerAuthProvider with JWKS
        google_auth_provider = create_google_bearer_auth_provider()
        assert google_auth_provider is not None
        print("✅ Google BearerAuthProvider created successfully")
        
        return auth_provider, google_auth_provider
        
    except Exception as e:
        print(f"❌ BearerAuthProvider creation failed: {e}")
        return None, None


def test_access_token_claims(access_token, custom_access_token):
    """Test access token claims extraction."""
    print("\n📋 Testing Access Token Claims...")
    
    try:
        # Test basic token claims
        print(f"Client ID: {access_token.client_id}")
        print(f"Email: {access_token.email}")
        print(f"Scopes: {access_token.scopes}")
        print(f"Expires at: {access_token.expires_at}")
        print(f"Issuer: {access_token.issuer}")
        print(f"Audience: {access_token.audience}")
        
        # Test custom token claims
        print(f"\nCustom Token Claims:")
        print(f"Client ID: {custom_access_token.client_id}")
        print(f"Email: {custom_access_token.email}")
        print(f"Scopes: {custom_access_token.scopes}")
        print(f"Additional claims: {custom_access_token.additional_claims}")
        
        # Test email validation
        assert access_token.email == "test@example.com"
        assert custom_access_token.email == "test.user@example.com"
        assert "read" in access_token.scopes
        assert "write" in access_token.scopes
        assert "admin" in custom_access_token.scopes
        
        print("✅ Access token claims extraction successful")
        
    except Exception as e:
        print(f"❌ Access token claims test failed: {e}")


def test_google_public_key():
    """Test Google public key integration."""
    print("\n🌐 Testing Google Public Key Integration...")
    
    try:
        # Create Google validator
        google_validator = TokenValidator(
            jwks_uri=GOOGLE_PUBLIC_KEY_URI,
            issuer="https://accounts.google.com",
            algorithm="RS256"
        )
        
        # Test JWKS fetching (this will fail with invalid tokens, but should not crash)
        print(f"✅ Google validator created with JWKS URI: {GOOGLE_PUBLIC_KEY_URI}")
        
        # Test with a dummy token (should fail gracefully)
        dummy_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0In0.invalid"
        is_valid = google_validator.is_token_valid(dummy_token)
        assert not is_valid
        print("✅ Google validator correctly rejects invalid tokens")
        
        # Test email extraction from invalid token
        email = google_validator.extract_email(dummy_token)
        assert email is None
        print("✅ Google validator email extraction correctly returns None for invalid tokens")
        
    except Exception as e:
        print(f"❌ Google public key test failed: {e}")


def test_token_expiration():
    """Test token expiration functionality."""
    print("\n⏰ Testing Token Expiration...")
    
    try:
        key_pair = create_test_key_pair()
        
        # Create a token that expires in 1 second
        short_lived_token = key_pair.create_token(
            subject="test@example.com",
            expires_in_seconds=1
        )
        
        validator = TokenValidator(public_key=key_pair.public_key)
        
        # Token should be valid immediately
        access_token = validator.validate_token(short_lived_token)
        assert access_token.expires_at is not None
        assert access_token.email == "test@example.com"
        print(f"✅ Token created with expiration: {access_token.expires_at}")
        
        # Wait for token to expire
        print("⏳ Waiting for token to expire...")
        time.sleep(2)
        
        # Token should now be invalid
        try:
            validator.validate_token(short_lived_token)
            print("❌ Expired token should have been rejected")
        except Exception as e:
            if "expired" in str(e).lower() or "exp" in str(e).lower():
                print("✅ Expired token correctly rejected")
            else:
                print(f"❌ Unexpected error for expired token: {e}")
        
        # Email extraction should also fail for expired token
        email = validator.extract_email(short_lived_token)
        assert email is None
        print("✅ Expired token email extraction correctly returns None")
        
    except Exception as e:
        print(f"❌ Token expiration test failed: {e}")


def test_scope_validation():
    """Test scope-based access control."""
    print("\n🔐 Testing Scope Validation...")
    
    try:
        key_pair = create_test_key_pair()
        
        # Create validator with required scopes
        validator = TokenValidator(
            public_key=key_pair.public_key,
            required_scopes=["admin", "write"]
        )
        
        # Create token with insufficient scopes
        insufficient_token = key_pair.create_token(
            subject="test@example.com",
            scopes=["read"]
        )
        
        # Token should be rejected due to missing scopes
        try:
            validator.validate_token(insufficient_token)
            print("❌ Token with insufficient scopes should have been rejected")
        except ValueError as e:
            if "Missing required scopes" in str(e):
                print("✅ Token with insufficient scopes correctly rejected")
            else:
                print(f"❌ Unexpected error: {e}")
        
        # Email extraction should return None with insufficient scopes
        email = validator.extract_email(insufficient_token)
        assert email is None
        print("✅ Email extraction correctly returns None for insufficient scopes")
        
        # Create token with sufficient scopes
        sufficient_token = key_pair.create_token(
            subject="test@example.com",
            scopes=["read", "write", "admin"]
        )
        
        # Token should be accepted
        access_token = validator.validate_token(sufficient_token)
        assert "admin" in access_token.scopes
        assert "write" in access_token.scopes
        assert access_token.email == "test@example.com"
        print("✅ Token with sufficient scopes correctly accepted")
        
    except Exception as e:
        import traceback
        print(f"❌ Scope validation test failed: {e}")
        print(f"Full traceback: {traceback.format_exc()}")


def run_all_tests():
    """Run all authentication tests."""
    print("🚀 Starting FastMCP Authentication Tests\n")
    print("=" * 50)
    
    # Test key pair generation
    key_pair = test_key_pair_generation()
    if not key_pair:
        print("❌ Cannot continue without key pair")
        return
    
    # Test token creation with email
    token, custom_token = test_token_creation_with_email(key_pair)
    if not token or not custom_token:
        print("❌ Cannot continue without tokens")
        return
    
    # Test token validation and email extraction
    validator, access_token, custom_access_token = test_token_validation_and_email_extraction(key_pair, token, custom_token)
    if not validator:
        print("❌ Cannot continue without validator")
        return
    
    # Test BearerAuthProvider creation
    test_bearer_auth_provider_creation()
    
    # Test access token claims
    test_access_token_claims(access_token, custom_access_token)
    
    # Test Google public key integration
    test_google_public_key()
    
    # Test token expiration
    test_token_expiration()
    
    # Test scope validation
    test_scope_validation()
    
    print("\n" + "=" * 50)
    print("🎉 All tests completed!")


if __name__ == "__main__":
    run_all_tests() 