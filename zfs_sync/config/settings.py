"""Application settings and configuration."""

import os
import platform
import re
import socket
from pathlib import Path
from typing import Optional

import yaml  # type: ignore[import-untyped]
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Optional TOML support
try:
    import tomli
except ImportError:
    tomli = None  # type: ignore[assignment, misc]


def get_default_database_url() -> str:
    """Get default database URL based on platform."""
    system = platform.system().lower()

    if system == "linux":
        # Linux: Use persistent system directory
        return "sqlite:////var/lib/zfs-sync/zfs_sync.db"
    elif system == "windows":
        # Windows: Use AppData directory for persistence
        appdata = os.getenv("APPDATA", os.path.expanduser("~"))
        db_path = Path(appdata) / "zfs-sync" / "zfs_sync.db"
        # Convert Windows path to SQLite URL format
        return f"sqlite:///{str(db_path).replace(chr(92), '/')}"
    else:
        # macOS and other Unix-like systems: Use user data directory
        home = Path.home()
        db_path = home / ".local" / "share" / "zfs-sync" / "zfs_sync.db"
        return f"sqlite:///{db_path}"


class Settings(BaseSettings):
    """Application settings with environment variable and file support."""

    # Application
    app_name: str = Field(default="zfs-sync", description="Application name")
    app_version: str = Field(default="0.1.14", description="Application version")
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # Server
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    api_prefix: str = Field(default="/api/v1", description="API prefix")

    # Database
    database_url: str = Field(
        default_factory=get_default_database_url,
        description="Database connection URL (defaults to platform-specific persistent location)",
    )

    # Security
    secret_key: Optional[str] = Field(
        default=None, description="Secret key for JWT/session management"
    )
    api_key_length: int = Field(default=32, description="Length of generated API keys")

    # Sync Settings
    default_sync_interval_seconds: int = Field(
        default=3600, description="Default sync interval in seconds"
    )
    heartbeat_timeout_seconds: int = Field(
        default=300, description="Timeout for system heartbeat in seconds"
    )

    # File paths
    config_file: Optional[Path] = Field(
        default=None, description="Path to configuration file (YAML/TOML)"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Validate database URL format."""
        if not v.startswith(("sqlite:///", "postgresql://", "postgresql+psycopg2://")):
            raise ValueError(
                "database_url must start with sqlite:///, postgresql://, or postgresql+psycopg2://"
            )
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number is in valid range."""
        if not (1 <= v <= 65535):
            raise ValueError(f"port must be between 1 and 65535, got {v}")
        return v

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, v: str) -> str:
        """Validate API prefix format."""
        if not v.startswith("/"):
            raise ValueError(f"api_prefix must start with '/', got '{v}'")
        if not v.endswith("/") and len(v) > 1:
            # Allow trailing slash but normalize
            pass
        # Check for valid URL path characters
        if not re.match(r"^/[a-zA-Z0-9/_-]*$", v):
            raise ValueError(
                "api_prefix contains invalid characters. Use only alphanumeric, '/', '_', and '-'"
            )
        return v.rstrip("/") if v != "/" else v

    @field_validator("api_key_length")
    @classmethod
    def validate_api_key_length(cls, v: int) -> int:
        """Validate API key length is reasonable."""
        if not (8 <= v <= 128):
            raise ValueError(f"api_key_length must be between 8 and 128, got {v}")
        return v

    @field_validator("default_sync_interval_seconds")
    @classmethod
    def validate_sync_interval(cls, v: int) -> int:
        """Validate sync interval is positive."""
        if v <= 0:
            raise ValueError(f"default_sync_interval_seconds must be positive, got {v}")
        return v

    @field_validator("heartbeat_timeout_seconds")
    @classmethod
    def validate_heartbeat_timeout(cls, v: int) -> int:
        """Validate heartbeat timeout is positive."""
        if v <= 0:
            raise ValueError(f"heartbeat_timeout_seconds must be positive, got {v}")
        return v

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate host is a valid IP address or hostname."""
        # Allow common special values
        if v in ("0.0.0.0", "127.0.0.1", "localhost", "*"):
            return v

        # Try to validate as IP address
        try:
            socket.inet_aton(v)
            return v
        except (socket.error, OSError):
            pass

        # Validate as hostname (basic check)
        if not re.match(
            r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$",
            v,
        ):
            raise ValueError(
                f"host must be a valid IP address or hostname, got '{v}'. "
                f"Valid examples: '0.0.0.0', '127.0.0.1', 'localhost', or a valid hostname"
            )
        return v

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "Settings":
        """Validate cross-field dependencies."""
        # Ensure heartbeat timeout is less than sync interval (if both are set)
        if (
            self.heartbeat_timeout_seconds >= self.default_sync_interval_seconds
            and self.default_sync_interval_seconds > 0
        ):
            raise ValueError(
                f"heartbeat_timeout_seconds ({self.heartbeat_timeout_seconds}) should be "
                f"less than default_sync_interval_seconds ({self.default_sync_interval_seconds}) "
                f"to ensure systems are detected as offline before sync operations"
            )
        return self

    @classmethod
    def from_file(cls, config_path: Path) -> "Settings":
        """Load settings from a YAML or TOML file."""
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        suffix = config_path.suffix.lower()
        if suffix == ".yaml" or suffix == ".yml":
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                raise ValueError(f"Error parsing YAML file: {exc}") from exc
        elif suffix == ".toml":
            if tomli is None:
                raise ImportError(
                    "TOML support requires 'tomli' package. Install with: pip install tomli"
                )
            with open(config_path, "rb") as f:
                config_data = tomli.load(f)
        else:
            raise ValueError(f"Unsupported configuration file format: {suffix}")

        # Override with environment variables
        env_overrides = {}
        for key, value in os.environ.items():
            if key.startswith("ZFS_SYNC_"):
                config_key = key.replace("ZFS_SYNC_", "").lower()
                env_overrides[config_key] = value

        # Merge file config with env overrides
        if config_data:
            config_data.update(env_overrides)
            return cls(**config_data)  # type: ignore[arg-type]
        else:
            return cls(**env_overrides)  # type: ignore[arg-type]


# Module-level settings cache (singleton pattern)
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        # Check for config file in common locations
        config_paths = [
            Path("zfs_sync.yaml"),
            Path("zfs_sync.yml"),
            Path("zfs_sync.toml"),
            Path("config/zfs_sync.yaml"),
            Path("config/zfs_sync.yml"),
            Path("config/zfs_sync.toml"),
        ]

        config_file = None
        for path in config_paths:
            if path.exists():
                config_file = path
                break

        if config_file:
            _settings = Settings.from_file(config_file)
        else:
            _settings = Settings()

    # Type assertion: _settings is guaranteed to be non-None after the if block
    assert _settings is not None, "Settings should be initialized"
    return _settings
