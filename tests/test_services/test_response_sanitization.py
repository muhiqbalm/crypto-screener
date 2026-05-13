"""
Unit tests for response sanitization in DebugExchangeService.

Tests that sensitive fields (API keys, secrets, tokens) are properly
filtered from all debug API responses.
"""

import pytest
from src.services.debug_exchange_service import sanitize_response_data, SENSITIVE_FIELDS


class TestSanitizeResponseData:
    """Tests for the sanitize_response_data function."""
    
    def test_sanitize_none(self):
        """Test that None is returned as-is."""
        result = sanitize_response_data(None)
        assert result is None
    
    def test_sanitize_primitive_types(self):
        """Test that primitive types are returned as-is."""
        assert sanitize_response_data("test") == "test"
        assert sanitize_response_data(123) == 123
        assert sanitize_response_data(45.67) == 45.67
        assert sanitize_response_data(True) is True
        assert sanitize_response_data(False) is False
    
    def test_sanitize_dict_with_no_sensitive_fields(self):
        """Test that dict without sensitive fields is returned unchanged."""
        data = {
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "volume": 1000000.0
        }
        result = sanitize_response_data(data)
        assert result == data
    
    def test_sanitize_dict_with_api_key(self):
        """Test that apiKey field is redacted."""
        data = {
            "symbol": "BTCUSDT",
            "apiKey": "my-secret-key-12345",
            "price": 50000.0
        }
        result = sanitize_response_data(data)
        assert result["symbol"] == "BTCUSDT"
        assert result["price"] == 50000.0
        assert result["apiKey"] == "[REDACTED]"
    
    def test_sanitize_dict_with_api_key_variations(self):
        """Test that various API key field name variations are redacted."""
        test_cases = [
            "apiKey",
            "api_key",
            "API_KEY",
            "ApiKey"
        ]
        
        for field_name in test_cases:
            data = {
                "symbol": "BTCUSDT",
                field_name: "secret-value",
                "price": 50000.0
            }
            result = sanitize_response_data(data)
            assert result[field_name] == "[REDACTED]", f"Field {field_name} should be redacted"
    
    def test_sanitize_dict_with_secret(self):
        """Test that secret field is redacted."""
        data = {
            "symbol": "BTCUSDT",
            "secret": "my-secret-value",
            "apiSecret": "another-secret",
            "price": 50000.0
        }
        result = sanitize_response_data(data)
        assert result["symbol"] == "BTCUSDT"
        assert result["price"] == 50000.0
        assert result["secret"] == "[REDACTED]"
        assert result["apiSecret"] == "[REDACTED]"
    
    def test_sanitize_dict_with_password(self):
        """Test that password field is redacted."""
        data = {
            "username": "trader123",
            "password": "my-password",
            "pass": "another-password"
        }
        result = sanitize_response_data(data)
        assert result["username"] == "trader123"
        assert result["password"] == "[REDACTED]"
        assert result["pass"] == "[REDACTED]"
    
    def test_sanitize_dict_with_token(self):
        """Test that token fields are redacted."""
        data = {
            "symbol": "BTCUSDT",
            "token": "bearer-token-12345",
            "accessToken": "access-token-67890",
            "refreshToken": "refresh-token-abcde"
        }
        result = sanitize_response_data(data)
        assert result["symbol"] == "BTCUSDT"
        assert result["token"] == "[REDACTED]"
        assert result["accessToken"] == "[REDACTED]"
        assert result["refreshToken"] == "[REDACTED]"
    
    def test_sanitize_dict_with_private_key(self):
        """Test that private key fields are redacted."""
        data = {
            "publicKey": "public-key-value",  # Should NOT be redacted
            "privateKey": "private-key-value",
            "private_key": "another-private-key"
        }
        result = sanitize_response_data(data)
        assert result["publicKey"] == "public-key-value"  # Not sensitive
        assert result["privateKey"] == "[REDACTED]"
        assert result["private_key"] == "[REDACTED]"
    
    def test_sanitize_nested_dict(self):
        """Test that nested dicts are recursively sanitized."""
        data = {
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "auth": {
                "apiKey": "secret-key",
                "secret": "secret-value",
                "username": "trader123"
            },
            "metadata": {
                "timestamp": 1234567890,
                "credentials": {
                    "token": "bearer-token"
                }
            }
        }
        result = sanitize_response_data(data)
        assert result["symbol"] == "BTCUSDT"
        assert result["price"] == 50000.0
        assert result["auth"]["apiKey"] == "[REDACTED]"
        assert result["auth"]["secret"] == "[REDACTED]"
        assert result["auth"]["username"] == "trader123"
        assert result["metadata"]["timestamp"] == 1234567890
        assert result["metadata"]["credentials"]["token"] == "[REDACTED]"
    
    def test_sanitize_list(self):
        """Test that lists are recursively sanitized."""
        data = [
            {"symbol": "BTCUSDT", "price": 50000.0},
            {"symbol": "ETHUSDT", "price": 3000.0, "apiKey": "secret-key"},
            {"symbol": "BNBUSDT", "price": 400.0}
        ]
        result = sanitize_response_data(data)
        assert len(result) == 3
        assert result[0] == {"symbol": "BTCUSDT", "price": 50000.0}
        assert result[1]["symbol"] == "ETHUSDT"
        assert result[1]["price"] == 3000.0
        assert result[1]["apiKey"] == "[REDACTED]"
        assert result[2] == {"symbol": "BNBUSDT", "price": 400.0}
    
    def test_sanitize_list_of_primitives(self):
        """Test that list of primitives is returned unchanged."""
        data = [1, 2, 3, "test", 4.5, True]
        result = sanitize_response_data(data)
        assert result == data
    
    def test_sanitize_complex_nested_structure(self):
        """Test sanitization of complex nested structure with lists and dicts."""
        data = {
            "results": [
                {
                    "symbol": "BTCUSDT",
                    "data": {
                        "price": 50000.0,
                        "auth": {
                            "apiKey": "secret-1",
                            "secret": "secret-2"
                        }
                    }
                },
                {
                    "symbol": "ETHUSDT",
                    "data": {
                        "price": 3000.0,
                        "credentials": [
                            {"token": "token-1", "type": "bearer"},
                            {"password": "pass-1", "username": "user1"}
                        ]
                    }
                }
            ],
            "metadata": {
                "apiKey": "master-key",
                "timestamp": 1234567890
            }
        }
        result = sanitize_response_data(data)
        
        # Check first result
        assert result["results"][0]["symbol"] == "BTCUSDT"
        assert result["results"][0]["data"]["price"] == 50000.0
        assert result["results"][0]["data"]["auth"]["apiKey"] == "[REDACTED]"
        assert result["results"][0]["data"]["auth"]["secret"] == "[REDACTED]"
        
        # Check second result
        assert result["results"][1]["symbol"] == "ETHUSDT"
        assert result["results"][1]["data"]["price"] == 3000.0
        assert result["results"][1]["data"]["credentials"][0]["token"] == "[REDACTED]"
        assert result["results"][1]["data"]["credentials"][0]["type"] == "bearer"
        assert result["results"][1]["data"]["credentials"][1]["password"] == "[REDACTED]"
        assert result["results"][1]["data"]["credentials"][1]["username"] == "user1"
        
        # Check metadata
        assert result["metadata"]["apiKey"] == "[REDACTED]"
        assert result["metadata"]["timestamp"] == 1234567890
    
    def test_sanitize_case_insensitive(self):
        """Test that field name matching is case-insensitive."""
        data = {
            "APIKEY": "secret-1",
            "ApiKey": "secret-2",
            "apikey": "secret-3",
            "API_KEY": "secret-4",
            "Api_Key": "secret-5"
        }
        result = sanitize_response_data(data)
        for key in data.keys():
            assert result[key] == "[REDACTED]", f"Field {key} should be redacted"
    
    def test_sanitize_with_hyphens_and_underscores(self):
        """Test that field names with hyphens and underscores are normalized."""
        data = {
            "api-key": "secret-1",
            "api_key": "secret-2",
            "api-secret": "secret-3",
            "api_secret": "secret-4",
            "access-token": "secret-5",
            "access_token": "secret-6"
        }
        result = sanitize_response_data(data)
        for key in data.keys():
            assert result[key] == "[REDACTED]", f"Field {key} should be redacted"
    
    def test_all_sensitive_fields_are_redacted(self):
        """Test that all fields in SENSITIVE_FIELDS set are properly redacted."""
        # Create a dict with all sensitive field names
        data = {field: f"secret-value-{field}" for field in SENSITIVE_FIELDS}
        data["safe_field"] = "safe-value"
        
        result = sanitize_response_data(data)
        
        # All sensitive fields should be redacted
        for field in SENSITIVE_FIELDS:
            assert result[field] == "[REDACTED]", f"Field {field} should be redacted"
        
        # Safe field should not be redacted
        assert result["safe_field"] == "safe-value"
    
    def test_sanitize_preserves_structure(self):
        """Test that sanitization preserves the original data structure."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "apiKey": "secret",
                        "data": [1, 2, 3]
                    }
                }
            }
        }
        result = sanitize_response_data(data)
        
        # Structure should be preserved
        assert "level1" in result
        assert "level2" in result["level1"]
        assert "level3" in result["level1"]["level2"]
        assert "apiKey" in result["level1"]["level2"]["level3"]
        assert "data" in result["level1"]["level2"]["level3"]
        
        # Sensitive field should be redacted
        assert result["level1"]["level2"]["level3"]["apiKey"] == "[REDACTED]"
        
        # Non-sensitive data should be preserved
        assert result["level1"]["level2"]["level3"]["data"] == [1, 2, 3]
