"""Configuration validation service."""

import os
import socket
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from zfs_sync.config.settings import Settings
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)


class ConfigurationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, message: str, suggestion: Optional[str] = None):
        """
        Initialize configuration error.

        Args:
            message: Error message
            suggestion: Optional suggestion for fixing the issue
        """
        self.message = message
        self.suggestion = suggestion
        full_message = message
        if suggestion:
            full_message = f"{message}\n\nSuggestion: {suggestion}"
        super().__init__(full_message)


def validate_configuration(settings: Settings) -> None:
    """
    Validate application configuration on startup.

    Performs comprehensive validation including:
    - Database connectivity
    - File and directory permissions
    - Network configuration
    - Configuration consistency

    Raises:
        ConfigurationError: If any validation fails
    """
    logger.info("Validating configuration...")

    errors = []

    # Validate database configuration
    try:
        validate_database_config(settings)
        logger.debug("Database configuration validated")
    except ConfigurationError as e:
        errors.append(str(e))

    # Validate log directory
    try:
        validate_log_directory()
        logger.debug("Log directory validated")
    except ConfigurationError as e:
        errors.append(str(e))

    # Validate network configuration
    try:
        validate_network_config(settings)
        logger.debug("Network configuration validated")
    except ConfigurationError as e:
        errors.append(str(e))

    # If any errors, raise them
    if errors:
        error_message = "Configuration validation failed:\n\n" + "\n\n".join(
            f"  • {error}" for error in errors
        )
        raise ConfigurationError(
            error_message,
            suggestion="Please review the errors above and fix the configuration issues before starting the application.",
        )

    logger.info("Configuration validation passed")


def validate_database_config(settings: Settings) -> None:
    """
    Validate database configuration and connectivity.

    Raises:
        ConfigurationError: If database configuration is invalid
    """
    database_url = settings.database_url

    if database_url.startswith("sqlite:///"):
        # Validate SQLite database path
        file_path = database_url.replace("sqlite:///", "", 1)

        # Handle absolute paths
        if file_path.startswith("/"):
            db_path = Path(file_path)
        else:
            db_path = Path(file_path)

        # Get parent directory
        parent_dir = db_path.parent

        # Check if parent directory exists and is writable
        if parent_dir.exists():
            if not os.access(parent_dir, os.W_OK):
                raise ConfigurationError(
                    f"Database directory '{parent_dir}' is not writable",
                    suggestion=(
                        f"Fix permissions with: chmod 755 {parent_dir}\n"
                        f"Or change ownership with: chown -R $(id -u):$(id -g) {parent_dir}"
                    ),
                )
        else:
            # Try to create the directory
            try:
                parent_dir.mkdir(parents=True, exist_ok=True)
                logger.info("Created database directory: %s", parent_dir)
            except (OSError, PermissionError) as e:
                raise ConfigurationError(
                    f"Cannot create database directory '{parent_dir}': {e}",
                    suggestion=(
                        f"Create the directory manually: mkdir -p {parent_dir}\n"
                        f"Then set permissions: chmod 755 {parent_dir}\n"
                        f"Or set ZFS_SYNC_DATABASE_URL to a path where the directory exists"
                    ),
                ) from e

        # Test database connection
        try:
            engine = create_engine(database_url, connect_args={"check_same_thread": False})
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.debug("SQLite database connection test passed")
        except OperationalError as e:
            raise ConfigurationError(
                f"Cannot connect to SQLite database at '{db_path}': {e}",
                suggestion=(
                    f"Check that the database file path is correct and the directory is writable.\n"
                    f"Current path: {db_path}\n"
                    f"Parent directory: {parent_dir}"
                ),
            ) from e

    elif database_url.startswith(("postgresql://", "postgresql+psycopg2://")):
        # Validate PostgreSQL connection
        try:
            engine = create_engine(database_url, connect_args={"connect_timeout": 5})
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.debug("PostgreSQL database connection test passed")
        except OperationalError as e:
            raise ConfigurationError(
                f"Cannot connect to PostgreSQL database: {e}",
                suggestion=(
                    "Check that:\n"
                    "  - PostgreSQL server is running\n"
                    "  - Database URL is correct (format: postgresql://user:password@host:port/dbname)\n"
                    "  - Database exists and user has access\n"
                    "  - Network connectivity to database server"
                ),
            ) from e
        except Exception as e:
            raise ConfigurationError(
                f"Error validating PostgreSQL connection: {e}",
                suggestion="Check database URL format and network connectivity",
            ) from e


def validate_log_directory() -> None:
    """
    Validate log directory exists and is writable.

    Raises:
        ConfigurationError: If log directory is invalid
    """
    # Check if log directory is configured via environment
    log_dir_env = os.getenv("ZFS_SYNC_LOG_DIR", None)
    if log_dir_env:
        log_dir = Path(log_dir_env)
    else:
        # Default log directory
        log_dir = Path("logs")

    # Create directory if it doesn't exist
    if not log_dir.exists():
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Created log directory: %s", log_dir)
        except (OSError, PermissionError) as e:
            raise ConfigurationError(
                f"Cannot create log directory '{log_dir}': {e}",
                suggestion=(
                    f"Create the directory manually: mkdir -p {log_dir}\n"
                    f"Or set ZFS_SYNC_LOG_DIR to a writable directory path"
                ),
            ) from e

    # Check if directory is writable
    if not os.access(log_dir, os.W_OK):
        raise ConfigurationError(
            f"Log directory '{log_dir}' is not writable",
            suggestion=(
                f"Fix permissions with: chmod 755 {log_dir}\n"
                f"Or change ownership: chown -R $(id -u):$(id -g) {log_dir}"
            ),
        )


def validate_network_config(settings: Settings) -> None:
    """
    Validate network configuration (host and port).

    Raises:
        ConfigurationError: If network configuration is invalid
    """
    host = settings.host
    port = settings.port

    # Check if port is already in use (only if host is 0.0.0.0 or localhost)
    if host in ("0.0.0.0", "127.0.0.1", "localhost"):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port))
            sock.close()

            if result == 0:
                raise ConfigurationError(
                    f"Port {port} is already in use on {host}",
                    suggestion=(
                        f"Choose a different port by setting ZFS_SYNC_PORT environment variable,\n"
                        f"or stop the service using port {port}"
                    ),
                )
        except socket.error as e:
            # Port check failed, but this is not critical - just log a warning
            logger.warning("Could not check if port %s is available: %s", port, e)

    # Validate host format (already done in field validator, but double-check)
    if host not in ("0.0.0.0", "127.0.0.1", "localhost", "*"):
        try:
            # Try to resolve hostname
            socket.gethostbyname(host)
        except socket.gaierror as e:
            raise ConfigurationError(
                f"Cannot resolve hostname '{host}': {e}",
                suggestion=(
                    f"Use a valid IP address (e.g., '0.0.0.0', '127.0.0.1') or ensure the hostname is resolvable.\n"
                    f"Current host: {host}"
                ),
            ) from e
