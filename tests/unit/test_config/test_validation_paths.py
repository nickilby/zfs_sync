"""Log directory validation checks the directory that will actually be used.

It used to check ``Path("logs")`` relative to the working directory, which had
no relationship to ``settings.log_file``. Startup validation therefore passed
while the real log target was unwritable, and the failure surfaced only as a
UserWarning swallowed inside setup_logging -- so the service ran with no file
logging and said nothing about it.
"""

import os

import pytest

from zfs_sync.config.settings import Settings
from zfs_sync.config.validation import ConfigurationError, validate_log_directory


class TestDirectorySelection:
    def test_the_configured_log_file_decides_the_directory(self, tmp_path):
        target = tmp_path / "var" / "log" / "zfs_sync.log"
        settings = Settings(log_file=str(target))

        validate_log_directory(settings)

        assert target.parent.is_dir(), "the configured directory was not prepared"

    def test_an_unrelated_logs_directory_is_not_created(self, tmp_path, monkeypatch):
        """The old behaviour created ./logs wherever the process happened to run."""
        monkeypatch.chdir(tmp_path)
        settings = Settings(log_file=str(tmp_path / "elsewhere" / "app.log"))

        validate_log_directory(settings)

        assert (tmp_path / "elsewhere").is_dir()
        assert not (tmp_path / "logs").exists(), "created a directory nothing writes to"

    def test_the_environment_override_wins(self, tmp_path, monkeypatch):
        override = tmp_path / "override"
        monkeypatch.setenv("ZFS_SYNC_LOG_DIR", str(override))
        settings = Settings(log_file=str(tmp_path / "ignored" / "app.log"))

        validate_log_directory(settings)

        assert override.is_dir()
        assert not (tmp_path / "ignored").exists()

    def test_no_log_file_means_nothing_to_validate(self, tmp_path, monkeypatch):
        """With no log file configured there is no directory to check.

        Settings fills in a platform default for log_file on Linux, so this
        asserts the function's behaviour directly rather than going through a
        Settings instance whose log_file depends on the host.
        """
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ZFS_SYNC_LOG_DIR", raising=False)

        settings = Settings()
        object.__setattr__(settings, "log_file", None)

        validate_log_directory(settings)

        assert list(tmp_path.iterdir()) == [], "nothing should have been created"


class TestFailureIsReported:
    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
    def test_an_unwritable_directory_is_an_error(self, tmp_path):
        """The case that used to pass validation and then fail silently."""
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        settings = Settings(log_file=str(locked / "app.log"))

        try:
            with pytest.raises(ConfigurationError, match="not writable"):
                validate_log_directory(settings)
        finally:
            locked.chmod(0o700)

    def test_a_directory_that_cannot_be_created_is_an_error(self, tmp_path):
        # A file where a directory needs to be.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        settings = Settings(log_file=str(blocker / "nested" / "app.log"))

        with pytest.raises(ConfigurationError):
            validate_log_directory(settings)

    def test_the_error_names_the_directory(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        settings = Settings(log_file=str(blocker / "nested" / "app.log"))

        with pytest.raises(ConfigurationError) as raised:
            validate_log_directory(settings)

        assert "nested" in str(raised.value)


class TestEnvironmentConfiguration:
    """ZFS_SYNC_* variables must work with or without a config file.

    SettingsConfigDict had no env_prefix, and the prefix was applied by a
    manual loop inside Settings.from_file(). So environment configuration was
    only honoured when a config file happened to exist; a deployment
    configured purely through the environment -- a container, say -- silently
    fell back to platform defaults, including for database_url.
    """

    def test_the_prefix_is_declared_on_the_model(self):
        from zfs_sync.config.settings import Settings

        assert (
            Settings.model_config.get("env_prefix") == "ZFS_SYNC_"
        ), "without env_prefix, ZFS_SYNC_* is only honoured when a config file exists"

    def test_the_database_url_is_taken_from_the_environment(self, tmp_path, monkeypatch):
        from zfs_sync.config.settings import Settings

        expected = f"sqlite:///{tmp_path / 'from-env.db'}"
        monkeypatch.setenv("ZFS_SYNC_DATABASE_URL", expected)

        assert Settings().database_url == expected

    def test_other_settings_come_from_the_environment_too(self, monkeypatch):
        from zfs_sync.config.settings import Settings

        monkeypatch.setenv("ZFS_SYNC_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("ZFS_SYNC_PORT", "9999")

        settings = Settings()

        assert settings.log_level == "DEBUG"
        assert settings.port == 9999

    def test_the_environment_still_wins_over_a_config_file(self, tmp_path, monkeypatch):
        """from_file applies env as init kwargs so it takes precedence; the
        prefix must not have reversed that."""
        from zfs_sync.config.settings import Settings

        config = tmp_path / "zfs_sync.yaml"
        config.write_text('log_level: "WARNING"\nport: 1234\n', encoding="utf-8")
        monkeypatch.setenv("ZFS_SYNC_LOG_LEVEL", "DEBUG")

        settings = Settings.from_file(config)

        assert settings.log_level == "DEBUG", "the environment should override the file"
        assert settings.port == 1234, "unset variables leave the file's value alone"
