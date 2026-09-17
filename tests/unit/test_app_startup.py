"""Application startup, which no test used to reach.

Startup branched on ``PYTEST_CURRENT_TEST`` and returned early, so
configuration validation, ``init_db()`` and the scheduler were never exercised
by the suite. Those are exactly the paths where the scheduler no-op, the
blocked event loop and the wrong-directory log check lived: the code most
likely to be wrong was the code guaranteed not to be tested.

``create_app(settings=...)`` takes its settings as an argument, so these tests
exercise the real startup path without touching environment variables or
reloading a module.
"""

import pytest
from fastapi.testclient import TestClient

from zfs_sync.api.app import create_app
from zfs_sync.config.settings import Settings
from zfs_sync.config.validation import ConfigurationError


@pytest.fixture
def settings(tmp_path):
    """Settings pointed entirely at this test's own temporary directory."""
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'startup.db'}",
        log_file=str(tmp_path / "logs" / "zfs_sync.log"),
        auto_sync_enabled=False,
    )


class TestTheFactory:
    def test_settings_are_injectable(self, settings):
        app = create_app(settings=settings, configure_logging=False)

        assert app.state.settings is settings
        assert app.version == settings.app_version

    def test_two_apps_can_differ(self, tmp_path):
        """Impossible when settings were read once at import time."""
        first = create_app(
            settings=Settings(database_url=f"sqlite:///{tmp_path / 'a.db'}"),
            configure_logging=False,
        )
        second = create_app(
            settings=Settings(database_url=f"sqlite:///{tmp_path / 'b.db'}", api_prefix="/api/v2"),
            configure_logging=False,
        )

        assert first.state.settings.database_url != second.state.settings.database_url
        assert "/api/v2/health" in second.openapi()["paths"]


class TestStartupRunsForReal:
    def test_the_database_is_created_on_startup(self, settings, tmp_path):
        """init_db() is reached now, rather than skipped under pytest."""
        app = create_app(settings=settings, configure_logging=False)
        database_file = tmp_path / "startup.db"
        assert not database_file.exists()

        with TestClient(app):
            pass

        assert database_file.exists(), "startup did not initialise the database"

    def test_the_injected_database_url_is_the_one_used(self, settings, tmp_path):
        """Startup must not fall back to the process-wide settings.

        init_db() read the global settings rather than the app's, so an
        injected configuration was ignored and the database was created
        wherever the platform default pointed -- /var/lib/zfs-sync on Linux,
        which is not writable by an ordinary user.
        """
        from zfs_sync.config import get_settings

        global_url = get_settings().database_url
        assert settings.database_url != global_url, "fixture must differ from the global"

        app = create_app(settings=settings, configure_logging=False)
        with TestClient(app):
            pass

        assert (tmp_path / "startup.db").exists()
        # And the schema really is there, not merely an empty file.
        import sqlite3

        connection = sqlite3.connect(tmp_path / "startup.db")
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            connection.close()
        assert {"systems", "snapshots", "sync_groups"} <= tables

    def test_configuration_validation_runs(self, settings, monkeypatch):
        calls = []

        def record(config):
            calls.append(config)

        monkeypatch.setattr("zfs_sync.config.validation.validate_configuration", record)
        app = create_app(settings=settings, configure_logging=False)

        with TestClient(app):
            pass

        assert calls, "configuration validation was skipped"
        assert calls[0] is settings

    def test_invalid_configuration_stops_startup(self, settings, monkeypatch):
        """A bad configuration must not reach a serving state."""

        def explode(_config):
            raise ConfigurationError("deliberately invalid")

        monkeypatch.setattr("zfs_sync.config.validation.validate_configuration", explode)
        app = create_app(settings=settings, configure_logging=False)

        with pytest.raises(ConfigurationError, match="deliberately invalid"), TestClient(app):
            pass

    def test_the_log_directory_is_created(self, settings, tmp_path):
        """Validation now uses the configured log file's directory."""
        app = create_app(settings=settings, configure_logging=False)

        with TestClient(app):
            pass

        assert (tmp_path / "logs").is_dir()


class TestSchedulerLifecycle:
    def test_it_does_not_start_when_disabled(self, settings):
        app = create_app(settings=settings, configure_logging=False)

        with TestClient(app):
            assert not hasattr(app.state, "sync_scheduler")

    def test_it_starts_and_stops_when_enabled(self, tmp_path, monkeypatch):
        started, stopped = [], []

        class FakeScheduler:
            async def start_scheduler(self):
                started.append(True)

            async def stop_scheduler(self):
                stopped.append(True)

        monkeypatch.setattr("zfs_sync.services.sync_scheduler.SyncSchedulerService", FakeScheduler)
        app = create_app(
            settings=Settings(
                database_url=f"sqlite:///{tmp_path / 'sched.db'}",
                log_file=str(tmp_path / "logs" / "s.log"),
                auto_sync_enabled=True,
            ),
            configure_logging=False,
        )

        with TestClient(app):
            assert started, "scheduler did not start"
            assert not stopped

        assert stopped, "scheduler was not stopped on shutdown"

    def test_a_failing_scheduler_does_not_take_the_service_down(self, tmp_path, monkeypatch):
        """Snapshot reporting still works even if scheduling cannot start."""

        class BrokenScheduler:
            async def start_scheduler(self):
                raise RuntimeError("cannot start")

        monkeypatch.setattr(
            "zfs_sync.services.sync_scheduler.SyncSchedulerService", BrokenScheduler
        )
        app = create_app(
            settings=Settings(
                database_url=f"sqlite:///{tmp_path / 'broken.db'}",
                log_file=str(tmp_path / "logs" / "b.log"),
                auto_sync_enabled=True,
            ),
            configure_logging=False,
        )

        with TestClient(app) as client:
            assert client.get("/api/v1/health").status_code == 200


class TestDashboardAssets:
    """The dashboard page referenced assets that always 404'd.

    The static directory was resolved two levels up from app.py, landing on a
    repo-root `static/` that app.py then created empty -- so the mount was
    always skipped.
    """

    def test_the_page_and_its_assets_are_served(self, settings):
        app = create_app(settings=settings, configure_logging=False)
        client = TestClient(app)

        assert client.get("/dashboard").status_code == 200
        for asset in (
            "/static/dashboard/css/dashboard.css",
            "/static/dashboard/js/dashboard.js",
            "/static/dashboard/js/api-client.js",
        ):
            assert client.get(asset).status_code == 200, f"{asset} is not served"

    def test_no_empty_directory_is_created_at_the_repository_root(self, settings):
        from pathlib import Path

        from zfs_sync.api.app import PACKAGE_STATIC_DIR

        create_app(settings=settings, configure_logging=False)

        assert PACKAGE_STATIC_DIR.name == "static"
        assert (
            PACKAGE_STATIC_DIR.parent.name == "zfs_sync"
        ), "assets must resolve inside the package, not at the repo root"
        assert (PACKAGE_STATIC_DIR / "dashboard" / "index.html").is_file()
        assert isinstance(PACKAGE_STATIC_DIR, Path)

    def test_the_root_redirects_to_the_dashboard(self, settings):
        app = create_app(settings=settings, configure_logging=False)

        response = TestClient(app, follow_redirects=False).get("/")

        assert response.status_code in (307, 302)
        assert response.headers["location"] == "/dashboard"
