"""Unit tests for configuration validation helpers."""

import socket

import pytest

from zfs_sync.config.settings import Settings
from zfs_sync.config.validation import (
    ConfigurationError,
    validate_configuration,
    validate_database_config,
    validate_network_config,
)


def test_validate_database_config_creates_missing_sqlite_directory(tmp_path):
    """SQLite validation should create missing parent directories when possible."""
    db_path = tmp_path / "nested" / "path" / "zfs_sync.db"
    settings = Settings(database_url=f"sqlite:///{db_path.as_posix()}")

    validate_database_config(settings)

    assert db_path.parent.exists()


def test_validate_network_config_raises_for_unresolvable_hostname(monkeypatch):
    """Network validation should fail with a clear configuration error for bad hosts."""
    settings = Settings(host="witness.internal", port=8000)

    def _raise_gaierror(_host: str):
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr("zfs_sync.config.validation.socket.gethostbyname", _raise_gaierror)

    with pytest.raises(ConfigurationError, match="Cannot resolve hostname"):
        validate_network_config(settings)


def test_validate_configuration_aggregates_errors(monkeypatch):
    """Top-level validation should include all failing checks in one message."""

    def _db_fail(_settings):
        raise ConfigurationError("db check failed")

    def _log_fail(_settings=None):
        # Takes settings now: it validates the directory of the configured
        # log_file rather than a hardcoded Path("logs").
        raise ConfigurationError("log dir check failed")

    def _network_fail(_settings):
        raise ConfigurationError("network check failed")

    monkeypatch.setattr("zfs_sync.config.validation.validate_database_config", _db_fail)
    monkeypatch.setattr("zfs_sync.config.validation.validate_log_directory", _log_fail)
    monkeypatch.setattr("zfs_sync.config.validation.validate_network_config", _network_fail)

    with pytest.raises(ConfigurationError) as exc_info:
        validate_configuration(Settings())

    message = str(exc_info.value)
    assert "db check failed" in message
    assert "log dir check failed" in message
    assert "network check failed" in message
