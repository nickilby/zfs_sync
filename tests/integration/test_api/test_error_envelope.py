"""The same condition must produce the same response on every route.

Previously "sync group not found" returned 404 from `/analysis` and 500 from
`/mismatches` and `/actions`, because each route decided independently whether
to catch the bare ValueError the service raised.
"""

import uuid

from fastapi import status


class TestUnknownSyncGroup:
    UNKNOWN = str(uuid.uuid4())

    def test_decisions_returns_404(self, auth_client):
        response = auth_client.get(f"/api/v1/sync/groups/{self.UNKNOWN}/decisions")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["error"]["code"] == "sync_group_not_found"

    def test_analysis_returns_404(self, auth_client):
        response = auth_client.get(f"/api/v1/sync/groups/{self.UNKNOWN}/analysis")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["error"]["code"] == "sync_group_not_found"

    def test_both_routes_agree(self, auth_client):
        decisions = auth_client.get(f"/api/v1/sync/groups/{self.UNKNOWN}/decisions")
        analysis = auth_client.get(f"/api/v1/sync/groups/{self.UNKNOWN}/analysis")

        assert decisions.status_code == analysis.status_code
        assert decisions.json()["error"]["code"] == analysis.json()["error"]["code"]

    def test_the_envelope_names_the_group(self, auth_client):
        response = auth_client.get(f"/api/v1/sync/groups/{self.UNKNOWN}/decisions")

        assert response.json()["error"]["sync_group_id"] == self.UNKNOWN

    def test_detail_is_retained_for_existing_clients(self, auth_client):
        response = auth_client.get(f"/api/v1/sync/groups/{self.UNKNOWN}/decisions")

        assert "detail" in response.json()


class TestValidationErrors:
    def test_a_malformed_uuid_is_a_422_with_the_envelope(self, auth_client):
        response = auth_client.get("/api/v1/sync/groups/not-a-uuid/decisions")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        body = response.json()
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["errors"], "the offending field should be named"


class TestUnhandledErrors:
    def test_a_correlation_id_is_returned_and_logged(
        self, test_db, registered_system, monkeypatch, caplog
    ):
        """No internal detail in the body; a correlation id links it to the log."""
        import logging

        from fastapi.testclient import TestClient

        from zfs_sync.api.app import app
        from zfs_sync.database.base import get_db
        from zfs_sync.services.sync import planner as planner_module

        def explode(self, *args, **kwargs):
            raise RuntimeError("database on fire at /secret/path with SELECT *")

        monkeypatch.setattr(planner_module.SyncPlanner, "plan_group", explode)

        _system_id, api_key = registered_system

        app.dependency_overrides[get_db] = lambda: iter([test_db])
        # The handler's response is what a real client sees; the default
        # TestClient re-raises instead of letting it through. This one is built
        # here rather than taken from a fixture, so it carries the key itself.
        client = TestClient(app, raise_server_exceptions=False)
        client.headers.update({"X-API-Key": api_key})
        try:
            with caplog.at_level(logging.ERROR):
                response = client.get(f"/api/v1/sync/groups/{uuid.uuid4()}/decisions")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        body = response.json()
        assert body["error"]["code"] == "internal_error"

        correlation_id = body["error"]["correlation_id"]
        assert correlation_id
        # The body must not leak internals, but the log must be findable.
        assert "secret/path" not in response.text
        assert "SELECT" not in response.text
        assert correlation_id in caplog.text
