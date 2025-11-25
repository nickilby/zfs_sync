"""Integration tests for systems endpoints."""

import pytest
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

        # Then retrieve it
        response = test_client.get(f"/api/v1/systems/{system_id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == system_id
        assert data["hostname"] == "test-system-2"

    def test_list_systems(self, test_client):
        """Test listing all systems."""
        # Create a few systems
        for i in range(3):
            test_client.post(
                "/api/v1/systems",
                json={
                    "hostname": f"test-system-{i}",
                    "platform": "linux",
                    "connectivity_status": "online",
                },
            )

        # List all systems
        response = test_client.get("/api/v1/systems")
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

