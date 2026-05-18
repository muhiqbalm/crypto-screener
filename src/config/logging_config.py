"""Structured JSON logging configuration with file rotation.

Provides setup_logging() to configure application-wide logging with:
- JSON structured format for machine readability
- RotatingFileHandler (max 10 files, 10MB each)
- Dual output: file + stdout
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from pythonjsonlogger import jsonlogger


LOG_DIR = os.environ.get("SCREENER_LOG_DIR", os.path.join("output", "logs"))
LOG_FILE = os.path.join(LOG_DIR, "api_server.log")

# 10 MB max per file
MAX_BYTES = 10 * 1024 * 1024
# Keep up to 10 backup files
BACKUP_COUNT = 10


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """JSON formatter that adds standard fields to every log record."""

    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["timestamp"] = self.formatTime(record, self.datefmt)
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured JSON logging with file rotation and stdout output.

    Args:
        log_level: Logging level string (e.g. "DEBUG", "INFO", "WARNING", "ERROR").
    """
    # Resolve log level string to numeric value
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Ensure log directory exists
    os.makedirs(LOG_DIR, exist_ok=True)

    # Create JSON formatter
    formatter = CustomJsonFormatter(
        fmt="%(timestamp)s %(level)s %(logger)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates on re-initialization
    root_logger.handlers.clear()

    # File handler with rotation
    file_handler = RotatingFileHandler(
        filename=LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(numeric_level)
    stdout_handler.setFormatter(formatter)
    root_logger.addHandler(stdout_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging configured",
        extra={"log_level": log_level, "log_file": LOG_FILE},
    )
