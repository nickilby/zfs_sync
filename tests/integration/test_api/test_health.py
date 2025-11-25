"""Integration tests for health endpoints."""


class TestHealthEndpoints:
    """Test suite for health check endpoints."""

    def test_health_check(self, test_client):
        """Test basic health check endpoint."""
        response = test_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"

    def test_health_live(self, test_client):
        """Test liveness probe endpoint."""
        response = test_client.get("/api/v1/health/live")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_health_ready(self, test_client):
        """Test readiness probe endpoint."""
        response = test_client.get("/api/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
