"""Logging configuration for ZFS Sync."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from zfs_sync.config import get_settings


def setup_logging(log_file: Optional[Path] = None) -> None:
    """Configure structured logging for the application."""
    settings = get_settings()

    # Create logs directory if it doesn't exist
    # Handle permission errors gracefully (e.g., in test environments)
    use_file_logging = False
    if log_file:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            use_file_logging = True
        except PermissionError:
            # In test environments or when running without permissions,
            # skip file logging but continue with console logging
            use_file_logging = False

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, settings.log_level))
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation
    if use_file_logging and log_file:
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=settings.log_max_bytes,
                backupCount=settings.log_backup_count,
            )
            file_handler.setLevel(getattr(logging, settings.log_level))
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except (PermissionError, OSError) as e:
            # If we can't create or write to the log file (e.g., in test environments),
            # skip file logging but continue with console logging
            import warnings

            warnings.warn(
                f"Could not set up file logging to {log_file}: {e}. "
                "Continuing with console logging only.",
                UserWarning,
            )

    # Set levels for third-party libraries
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)
