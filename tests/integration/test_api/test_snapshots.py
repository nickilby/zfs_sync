"""Integration tests for snapshots endpoints."""

from datetime import datetime, timezone

import pytest
from fastapi import status


class TestSnapshotsEndpoints:
    """Test suite for snapshots API endpoints."""

    def test_report_snapshot(self, test_client):
        """Test reporting a single snapshot."""
        # First register a system
        register_response = test_client.post(
            "/api/v1/systems",
            json={
                "hostname": "test-system-snapshot",
                "platform": "linux",
                "connectivity_status": "online",
            },
        )
        system_id = register_response.json()["id"]
        api_key = register_response.json()["api_key"]

        # Report a snapshot
        snapshot_data = {
            "name": "backup-20240115-120000",
            "pool": "tank",
            "dataset": "tank/data",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "size": 1024 * 1024,
        }

        response = test_client.post(
            f"/api/v1/snapshots",
            headers={"X-API-Key": api_key},
            json=snapshot_data,
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "id" in data
        assert data["name"] == snapshot_data["name"]

    def test_report_batch_snapshots(self, test_client):
        """Test reporting multiple snapshots in batch."""
        # Register a system
        register_response = test_client.post(
            "/api/v1/systems",
            json={
                "hostname": "test-system-batch",
                "platform": "linux",
                "connectivity_status": "online",
            },
        )
        system_id = register_response.json()["id"]
        api_key = register_response.json()["api_key"]

        # Report multiple snapshots
        snapshots = [
            {
                "name": f"backup-202401{15+i:02d}-120000",
                "pool": "tank",
                "dataset": "tank/data",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "size": 1024 * 1024 * (i + 1),
            }
            for i in range(3)
        ]

        response = test_client.post(
            f"/api/v1/snapshots/batch",
            headers={"X-API-Key": api_key},
            json={"snapshots": snapshots},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "created" in data
        assert data["created"] == 3

    def test_get_snapshots(self, test_client):
        """Test retrieving snapshots for a system."""
        # Register a system and report snapshots
        register_response = test_client.post(
            "/api/v1/systems",
            json={
                "hostname": "test-system-get",
                "platform": "linux",
                "connectivity_status": "online",
            },
        )
        system_id = register_response.json()["id"]
        api_key = register_response.json()["api_key"]

        # Report a snapshot
        snapshot_data = {
            "name": "backup-20240115-120000",
            "pool": "tank",
            "dataset": "tank/data",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "size": 1024 * 1024,
        }
        test_client.post(
            f"/api/v1/snapshots",
            headers={"X-API-Key": api_key},
            json=snapshot_data,
        )

        # Get snapshots
        response = test_client.get(
            f"/api/v1/snapshots",
            headers={"X-API-Key": api_key},
            params={"pool": "tank", "dataset": "tank/data"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "snapshots" in data
        assert len(data["snapshots"]) >= 1

