"""Unit tests for SystemRepository."""

from zfs_sync.database.repositories import SystemRepository


class TestSystemRepository:
    """Test suite for SystemRepository."""

    def test_create_system(self, test_db, sample_system_data):
        """Test creating a system."""
        repo = SystemRepository(test_db)
        system = repo.create(**sample_system_data)

        assert system is not None
        assert system.hostname == sample_system_data["hostname"]
        assert system.platform == sample_system_data["platform"]
        assert system.id is not None

    def test_get_system(self, test_db, sample_system_data):
        """Test retrieving a system by ID."""
        repo = SystemRepository(test_db)
        system = repo.create(**sample_system_data)

        retrieved = repo.get(system.id)
        assert retrieved is not None
        assert retrieved.id == system.id
        assert retrieved.hostname == system.hostname

    def test_get_by_hostname(self, test_db, sample_system_data):
        """Test retrieving a system by hostname."""
        repo = SystemRepository(test_db)
        repo.create(**sample_system_data)

        retrieved = repo.get_by_hostname(sample_system_data["hostname"])
        assert retrieved is not None
        assert retrieved.hostname == sample_system_data["hostname"]

    def test_update_system(self, test_db, sample_system_data):
        """Test updating a system."""
        repo = SystemRepository(test_db)
        system = repo.create(**sample_system_data)

        updated = repo.update(system.id, platform="freebsd")
        assert updated.platform == "freebsd"
        assert updated.hostname == sample_system_data["hostname"]  # Unchanged

    def test_delete_system(self, test_db, sample_system_data):
        """Test deleting a system."""
        repo = SystemRepository(test_db)
        system = repo.create(**sample_system_data)

        repo.delete(system.id)
        retrieved = repo.get(system.id)
        assert retrieved is None

    def test_list_all_systems(self, test_db, sample_system_data):
        """Test listing all systems."""
        repo = SystemRepository(test_db)

        # Create multiple systems
        for i in range(3):
            data = sample_system_data.copy()
            data["hostname"] = f"test-system-{i}"
            repo.create(**data)

        all_systems = repo.get_all()
        assert len(all_systems) >= 3
