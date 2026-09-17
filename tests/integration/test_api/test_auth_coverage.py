"""Every endpoint that touches fleet data must require authentication.

Only 6 of 54 routes were protected. The open ones included DELETE /systems/{id}
(which cascades to its snapshots), DELETE /snapshots/system/{id}, PUT
/systems/{id} (which writes the ssh_hostname that ends up in a command the hub
runs as root), and GET /sync/instructions/{id}, which returns the fleet's SSH
topology.

The exemptions are listed explicitly so that adding an unauthenticated endpoint
is a deliberate act with a name attached, rather than an omission.
"""

from typing import ClassVar

import pytest
from fastapi import status

from zfs_sync.api.app import app

#: Paths that are intentionally reachable without a key, and why.
EXEMPT = {
    "/": "redirects to the dashboard",
    "/favicon.ico": "browser noise",
    "/dashboard": "the dashboard page itself; its data comes from the API",
    "/assets/{path}": "static assets",
    "/api/v1/health": "liveness probes must not need credentials",
    "/api/v1/health/live": "liveness probe",
    "/api/v1/health/ready": "readiness probe",
    "/api/v1/dashboard/events": "browser event stream; carries no fleet data today",
    "/api/v1/systems": "registration must be reachable; gated by registration_token",
}


def routes_without_security():
    schema = app.openapi()
    found = []
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            if "security" not in operation:
                found.append((method.upper(), path))
    return found


class TestAuthCoverage:
    def test_no_unlisted_endpoint_is_open(self):
        unexpected = [
            (method, path) for method, path in routes_without_security() if path not in EXEMPT
        ]

        assert not unexpected, (
            "these endpoints require no authentication and are not listed as exempt: "
            f"{unexpected}. Protect them, or add them to EXEMPT with a reason."
        )

    def test_only_registration_is_open_on_the_systems_router(self):
        """GET /systems returned the whole fleet's SSH topology."""
        open_system_routes = {
            (method, path)
            for method, path in routes_without_security()
            if path.startswith("/api/v1/systems")
        }

        assert open_system_routes == {("POST", "/api/v1/systems")}

    def test_every_exemption_still_corresponds_to_a_real_route(self):
        """Stops the list rotting into a licence for anything."""
        schema = app.openapi()
        known = set(schema["paths"]) | {"/dashboard", "/favicon.ico", "/", "/assets/{path}"}

        stale = [path for path in EXEMPT if path not in known]
        assert not stale, f"EXEMPT lists routes that no longer exist: {stale}"


class TestDestructiveRoutesAreProtected:
    DESTRUCTIVE: ClassVar[list] = [
        ("delete", "/api/v1/systems/{system_id}"),
        ("delete", "/api/v1/snapshots/system/{system_id}"),
        ("delete", "/api/v1/sync-groups/{group_id}"),
        ("put", "/api/v1/systems/{system_id}"),
        ("post", "/api/v1/snapshots/batch"),
    ]

    @pytest.mark.parametrize("method,path", DESTRUCTIVE)
    def test_it_requires_a_key(self, method, path):
        operation = app.openapi()["paths"][path][method]

        assert "security" in operation, f"{method.upper()} {path} is unauthenticated"


class TestRejectionBehaviour:
    def test_a_missing_key_is_401(self, test_client):
        response = test_client.get("/api/v1/systems")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers.get("WWW-Authenticate") == "ApiKey"

    def test_an_unknown_key_is_401(self, test_client):
        response = test_client.get(
            "/api/v1/systems", headers={"X-API-Key": "not-a-real-key"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_a_valid_key_is_accepted(self, test_client):
        created = test_client.post(
            "/api/v1/systems",
            json={"hostname": "hub1", "platform": "linux", "connectivity_status": "online"},
        ).json()

        response = test_client.get(
            "/api/v1/systems", headers={"X-API-Key": created["api_key"]}
        )

        assert response.status_code == status.HTTP_200_OK

    def test_the_topology_is_not_readable_without_a_key(self, test_client):
        """The instructions endpoint names SSH hosts, pools and datasets."""
        created = test_client.post(
            "/api/v1/systems",
            json={"hostname": "hub2", "platform": "linux", "ssh_hostname": "hub2-san"},
        ).json()

        response = test_client.get(f"/api/v1/sync/instructions/{created['id']}")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_a_system_cannot_edit_another(self, test_client):
        victim = test_client.post(
            "/api/v1/systems", json={"hostname": "victim", "platform": "linux"}
        ).json()
        attacker = test_client.post(
            "/api/v1/systems", json={"hostname": "attacker", "platform": "linux"}
        ).json()

        response = test_client.put(
            f"/api/v1/systems/{victim['id']}",
            headers={"X-API-Key": attacker["api_key"]},
            json={"ssh_hostname": "attacker-controlled-host"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
