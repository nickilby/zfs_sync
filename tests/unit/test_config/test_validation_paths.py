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
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ZFS_SYNC_LOG_DIR", raising=False)

        validate_log_directory(Settings(log_file=None))

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
