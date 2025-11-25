"""Service for generating SSH-based ZFS send/receive commands."""

import shlex
from typing import Optional

from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)


class SSHCommandGenerator:
    """Service for generating SSH-based ZFS send/receive commands."""

    @staticmethod
    def escape_shell_string(value: str) -> str:
        """
        Escape a string for safe use in shell commands.

        Args:
            value: String to escape

        Returns:
            Escaped string safe for shell use
        """
        return shlex.quote(value)

    @staticmethod
    def generate_ssh_command(
        hostname: str,
        user: Optional[str] = None,
        port: int = 22,
        command: str = "",
    ) -> str:
        """
        Generate SSH command string.

        Args:
            hostname: SSH hostname/IP
            user: SSH username (optional, uses system default if not provided)
            port: SSH port (default: 22)
            command: Command to execute remotely

        Returns:
            SSH command string
        """
        ssh_parts = ["ssh"]
        if port != 22:
            ssh_parts.append(f"-p {port}")
        
        # Build target (user@hostname or just hostname)
        # Note: We don't escape the target as it's part of SSH syntax
        if user:
            target = f"{user}@{hostname}"
        else:
            target = hostname
        
        ssh_parts.append(target)
        
        if command:
            # Command should be quoted as a single argument to SSH
            ssh_parts.append(SSHCommandGenerator.escape_shell_string(command))
        
        return " ".join(ssh_parts)

    @staticmethod
    def generate_zfs_send_command(
        pool: str,
        dataset: str,
        snapshot_name: str,
        ssh_hostname: str,
        ssh_user: Optional[str] = None,
        ssh_port: int = 22,
        incremental_base: Optional[str] = None,
    ) -> str:
        """
        Generate ZFS send command with SSH.

        Args:
            pool: ZFS pool name
            dataset: ZFS dataset name (may include pool prefix, e.g., "tank/data")
            snapshot_name: Snapshot name (without pool/dataset prefix)
            ssh_hostname: SSH hostname/IP for source system
            ssh_user: SSH username (optional)
            ssh_port: SSH port (default: 22)
            incremental_base: Base snapshot name for incremental send (optional)

        Returns:
            ZFS send command string ready to pipe to zfs receive
        """
        # Construct full snapshot path
        # Dataset may already include pool (e.g., "tank/data") or just be dataset name
        # Use dataset as-is if it contains '/', otherwise prepend pool
        if '/' in dataset:
            full_snapshot = f"{dataset}@{snapshot_name}"
        else:
            full_snapshot = f"{pool}/{dataset}@{snapshot_name}"

        if incremental_base:
            # Incremental send: zfs send -I base_snapshot latest_snapshot
            if '/' in dataset:
                base_snapshot = f"{dataset}@{incremental_base}"
            else:
                base_snapshot = f"{pool}/{dataset}@{incremental_base}"
            zfs_command = f"zfs send -I {SSHCommandGenerator.escape_shell_string(base_snapshot)} {SSHCommandGenerator.escape_shell_string(full_snapshot)}"
        else:
            # Full send: zfs send snapshot
            zfs_command = f"zfs send {SSHCommandGenerator.escape_shell_string(full_snapshot)}"

        ssh_cmd = SSHCommandGenerator.generate_ssh_command(
            hostname=ssh_hostname, user=ssh_user, port=ssh_port, command=zfs_command
        )

        return ssh_cmd

    @staticmethod
    def generate_zfs_receive_command(
        pool: str,
        dataset: str,
        force: bool = True,
    ) -> str:
        """
        Generate ZFS receive command.

        Args:
            pool: ZFS pool name
            dataset: ZFS dataset name (may include pool prefix, e.g., "tank/data")
            force: Use -F flag to force receive (default: True)

        Returns:
            ZFS receive command string
        """
        flags = "-F" if force else ""
        # Dataset may already include pool (e.g., "tank/data") or just be dataset name
        if '/' in dataset:
            target_dataset = dataset
        else:
            target_dataset = f"{pool}/{dataset}"
        return f"zfs receive {flags} {SSHCommandGenerator.escape_shell_string(target_dataset)}".strip()

    @staticmethod
    def generate_full_sync_command(
        pool: str,
        dataset: str,
        snapshot_name: str,
        ssh_hostname: str,
        ssh_user: Optional[str] = None,
        ssh_port: int = 22,
    ) -> str:
        """
        Generate complete sync command (SSH send piped to local receive).

        Args:
            pool: ZFS pool name
            dataset: ZFS dataset name
            snapshot_name: Snapshot name (without pool/dataset prefix)
            ssh_hostname: SSH hostname/IP for source system
            ssh_user: SSH username (optional)
            ssh_port: SSH port (default: 22)

        Returns:
            Complete command string: ssh ... 'zfs send ...' | zfs receive ...
        """
        send_cmd = SSHCommandGenerator.generate_zfs_send_command(
            pool=pool,
            dataset=dataset,
            snapshot_name=snapshot_name,
            ssh_hostname=ssh_hostname,
            ssh_user=ssh_user,
            ssh_port=ssh_port,
        )
        receive_cmd = SSHCommandGenerator.generate_zfs_receive_command(
            pool=pool, dataset=dataset, force=True
        )

        return f"{send_cmd} | {receive_cmd}"

    @staticmethod
    def generate_incremental_sync_command(
        pool: str,
        dataset: str,
        snapshot_name: str,
        incremental_base: str,
        ssh_hostname: str,
        ssh_user: Optional[str] = None,
        ssh_port: int = 22,
    ) -> str:
        """
        Generate complete incremental sync command.

        Args:
            pool: ZFS pool name
            dataset: ZFS dataset name
            snapshot_name: Snapshot name (without pool/dataset prefix)
            incremental_base: Base snapshot name for incremental send
            ssh_hostname: SSH hostname/IP for source system
            ssh_user: SSH username (optional)
            ssh_port: SSH port (default: 22)

        Returns:
            Complete incremental sync command string
        """
        send_cmd = SSHCommandGenerator.generate_zfs_send_command(
            pool=pool,
            dataset=dataset,
            snapshot_name=snapshot_name,
            ssh_hostname=ssh_hostname,
            ssh_user=ssh_user,
            ssh_port=ssh_port,
            incremental_base=incremental_base,
        )
        receive_cmd = SSHCommandGenerator.generate_zfs_receive_command(
            pool=pool, dataset=dataset, force=True
        )

        return f"{send_cmd} | {receive_cmd}"

