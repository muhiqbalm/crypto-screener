"""
Crypto Screener API Entry Point

Starts the FastAPI server using uvicorn with configuration from environment
variables or .env file. All settings use the SCREENER_ prefix.

Usage:
    python main_api.py
    python main_api.py --reload  (development mode)
"""

import sys
import uvicorn

from src.config.settings import Settings
from src.api.app import create_app


def main() -> None:
    """Start the API server with configured settings."""
    settings = Settings()
    reload_mode = "--reload" in sys.argv

    uvicorn.run(
        "src.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        reload=reload_mode,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
