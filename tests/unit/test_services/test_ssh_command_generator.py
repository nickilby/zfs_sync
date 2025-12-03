"""Unit tests for SSHCommandGenerator."""

from zfs_sync.services.ssh_command_generator import SSHCommandGenerator


class TestSSHCommandGenerator:
    """Test suite for SSHCommandGenerator."""

    def test_generate_incremental_sync_command_snapshot_order(self):
        """Test that incremental sync command has snapshots in correct order."""
        # Base snapshot (earlier/common) should come first
        # Ending snapshot (later) should come second
        base_snapshot = "2025-12-01-000000"
        ending_snapshot = "2025-12-02-120000"

        command = SSHCommandGenerator.generate_incremental_sync_command(
            pool="tank",
            dataset="data",
            snapshot_name=ending_snapshot,  # Later snapshot
            incremental_base=base_snapshot,  # Earlier snapshot
            target_ssh_hostname="target.example.com",
            target_pool="backup",
            target_dataset="data",
        )

        # Verify command contains base snapshot before ending snapshot
        base_index = command.find(f"@{base_snapshot}")
        ending_index = command.find(f"@{ending_snapshot}")

        assert base_index != -1, f"Base snapshot {base_snapshot} not found in command"
        assert ending_index != -1, f"Ending snapshot {ending_snapshot} not found in command"
        assert (
            base_index < ending_index
        ), f"Base snapshot must come before ending snapshot. Command: {command}"

        # Verify using -I flag (uppercase) for incremental send
        assert "-I" in command, "Command should use -I flag for incremental send"
        assert "-i" not in command, "Command should not use lowercase -i flag"

        # Verify the exact order in the zfs send part
        # Extract the zfs send command part
        send_part = command.split("|")[0]
        assert (
            f"@{base_snapshot}" in send_part and f"@{ending_snapshot}" in send_part
        ), "Both snapshots should be in send command"

        # Verify order: base snapshot name appears before ending snapshot name
        base_pos = send_part.find(f"@{base_snapshot}")
        ending_pos = send_part.find(f"@{ending_snapshot}")
        assert (
            base_pos < ending_pos
        ), f"Base snapshot must appear before ending snapshot in send command. Send part: {send_part}"

    def test_generate_incremental_sync_command_format(self):
        """Test that incremental sync command has correct format."""
        command = SSHCommandGenerator.generate_incremental_sync_command(
            pool="tank",
            dataset="data",
            snapshot_name="2025-12-02-120000",
            incremental_base="2025-12-01-000000",
            target_ssh_hostname="target.example.com",
        )

        # Should contain zfs send with -c and -I flags
        assert "zfs send" in command
        assert "-c" in command, "Should use compression flag"
        assert "-I" in command, "Should use -I flag for incremental send"

        # Should contain pipe to ssh
        assert "|" in command
        assert "ssh" in command
        assert "target.example.com" in command

        # Should contain zfs receive
        assert "zfs receive" in command

    def test_generate_full_sync_command(self):
        """Test that full sync command has correct format."""
        command = SSHCommandGenerator.generate_full_sync_command(
            pool="tank",
            dataset="data",
            snapshot_name="2025-12-02-120000",
            target_ssh_hostname="target.example.com",
            target_pool="backup",
        )

        # Should contain zfs send with -c flag (compression)
        assert "zfs send" in command
        assert "-c" in command, "Should use compression flag"

        # Should NOT contain incremental flags
        assert "-I" not in command
        assert "-i" not in command

        # Should contain pipe to ssh
        assert "|" in command
        assert "ssh" in command
        assert "target.example.com" in command

        # Should contain zfs receive
        assert "zfs receive" in command

    def test_generate_zfs_send_command_incremental(self):
        """Test that zfs_send_command with incremental_base has correct order."""
        command = SSHCommandGenerator.generate_zfs_send_command(
            pool="tank",
            dataset="data",
            snapshot_name="2025-12-02-120000",  # Later snapshot
            ssh_hostname="source.example.com",
            incremental_base="2025-12-01-000000",  # Earlier snapshot
        )

        # Verify using -I flag
        assert "-I" in command, "Should use -I flag for incremental send"

        # Verify snapshot order
        base_index = command.find("2025-12-01-000000")
        ending_index = command.find("2025-12-02-120000")

        assert base_index != -1, "Base snapshot should be in command"
        assert ending_index != -1, "Ending snapshot should be in command"
        assert (
            base_index < ending_index
        ), f"Base snapshot must come before ending snapshot. Command: {command}"
