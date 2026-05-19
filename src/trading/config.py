"""Trading module configuration via Pydantic BaseSettings.

Reads configuration from environment variables with TRADING_ prefix,
falling back to .env file and default values.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingSettings(BaseSettings):
    """Trading module settings loaded from environment variables or .env file.

    All environment variables use the TRADING_ prefix.
    Example: TRADING_SUPABASE_URL=https://your-project.supabase.co
    """

    model_config = SettingsConfigDict(
        env_prefix="TRADING_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Supabase connection
    supabase_url: str = ""
    supabase_key: str = ""

    # Encryption key for storing exchange credentials (Fernet key)
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = ""

    # Telegram bot token for trade notifications (optional)
    telegram_bot_token: str = ""

    # Use testnet/sandbox mode for all exchange connections
    testnet_enabled: bool = True

    # Maximum webhook payload size in bytes (default: 1 MB)
    max_payload_size: int = 1_048_576

    # Timeout in seconds for acquiring database advisory lock
    lock_timeout_seconds: int = 5

    # Timeout in seconds for exchange order submission
    order_timeout_seconds: int = 5


def get_trading_settings() -> TradingSettings:
    """Create and return a TradingSettings instance."""
    return TradingSettings()
