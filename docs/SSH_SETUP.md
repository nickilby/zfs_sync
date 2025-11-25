# SSH Setup Guide for ZFS Sync

This guide explains how to configure SSH authentication for ZFS snapshot synchronization between systems.

## Overview

The ZFS Sync witness service provides sync instructions that include SSH connection details. Systems execute `zfs send` and `zfs receive` commands via SSH to synchronize snapshots. SSH keys must already be configured on each system - this application does not store or manage SSH keys.

## Prerequisites

- SSH key-based authentication must already be configured between systems
- Each system must have SSH access to other systems in the sync group
- SSH keys should be configured with appropriate permissions (600 for private keys)

## System Registration with SSH Details

When registering a system with the witness service, you can optionally provide SSH connection details:

- `ssh_hostname`: The hostname or IP address for SSH connections (can differ from API hostname)
- `ssh_user`: The SSH username for key-based authentication
- `ssh_port`: The SSH port (default: 22)

### Example: Registering a System with SSH Details

```bash
curl -X POST "http://witness-service:8000/api/v1/systems" \
  -H "Content-Type: application/json" \
  -d '{
    "hostname": "backup-server-01",
    "platform": "linux",
    "ssh_hostname": "backup-server-01.internal",
    "ssh_user": "zfsadmin",
    "ssh_port": 22
  }'
```

### Example: Updating SSH Details

```bash
curl -X PUT "http://witness-service:8000/api/v1/systems/{system_id}" \
  -H "Content-Type: application/json" \
  -d '{
    "ssh_hostname": "backup-server-01.new-domain.com",
    "ssh_port": 2222
  }'
```

## SSH Key Configuration

### Key Requirements

1. **Private Key Permissions**: SSH private keys must have permissions `600` (read/write for owner only)
   ```bash
   chmod 600 ~/.ssh/id_rsa_zfs_sync
   ```

2. **Public Key Distribution**: Public keys must be added to `~/.ssh/authorized_keys` on target systems

3. **SSH Config**: Consider using SSH config files (`~/.ssh/config`) to simplify connection management

### Example SSH Config Entry

```ssh-config
Host backup-server-01
    HostName backup-server-01.internal
    User zfsadmin
    Port 22
    IdentityFile ~/.ssh/id_rsa_zfs_sync
    StrictHostKeyChecking yes
```

## Testing SSH Connectivity

Before configuring sync groups, verify SSH connectivity between systems:

```bash
# Test SSH connection
ssh -i ~/.ssh/id_rsa_zfs_sync -p 22 zfsadmin@backup-server-01.internal "echo 'SSH connection successful'"

# Test ZFS command execution
ssh -i ~/.ssh/id_rsa_zfs_sync -p 22 zfsadmin@backup-server-01.internal "zfs list"
```

## Sync Command Execution

When systems query the witness service for sync instructions, they receive commands like:

```bash
# Full send example
ssh -p 22 zfsadmin@backup-server-01.internal 'zfs send tank/data@backup-20240115-120000' | zfs receive -F tank/data

# Incremental send example
ssh -p 22 zfsadmin@backup-server-01.internal 'zfs send -I tank/data@backup-20240114-120000 tank/data@backup-20240115-120000' | zfs receive -F tank/data
```

## Security Best Practices

1. **Key Rotation**: Regularly rotate SSH keys used for ZFS sync
2. **Key Isolation**: Use dedicated SSH keys for ZFS sync operations (not your personal keys)
3. **Access Control**: Limit SSH access to only necessary commands using `authorized_keys` command restrictions
4. **Network Security**: Use VPNs or private networks for SSH connections when possible
5. **Audit Logging**: Monitor SSH access logs for unauthorized access attempts

### Example: Restricted SSH Key

Add to `~/.ssh/authorized_keys` on target system:

```
command="zfs list || zfs send || zfs receive" ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ... zfs-sync-key
```

This restricts the key to only execute ZFS-related commands.

## Troubleshooting

### SSH Connection Failures

- Verify SSH keys are correctly configured
- Check SSH key permissions (`chmod 600`)
- Verify network connectivity between systems
- Check SSH server logs (`/var/log/auth.log` on Linux)

### ZFS Command Failures

- Ensure the SSH user has permissions to execute `zfs send` and `zfs receive`
- Verify dataset names match exactly between systems
- Check ZFS pool availability on both source and target systems

### Sync Command Generation

If sync commands are not generated:
- Verify SSH details are configured for the source system
- Check that systems are properly registered in sync groups
- Review witness service logs for errors

## Next Steps

- See `docs/templates/system_ssh_config.yaml` for example system registration configurations
- See `docs/templates/sync_executor.sh` for a script template to execute sync commands
- See `HOW_TO_USE.md` for complete usage instructions

