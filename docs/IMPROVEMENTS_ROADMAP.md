# ZFS Sync Improvements Roadmap

A prioritized roadmap of feature and usability improvements for ZFS Sync v2.0 and beyond.

## Overview

This roadmap focuses on **usability enhancements** and **feature improvements** that will make ZFS Sync easier to use and more powerful. The priorities are based on impact and effort, with emphasis on features that improve the user experience.

## Priority 1: Usability Enhancements (High Impact, Low-Medium Effort)

### 1.1 Enhanced Dashboard Functionality

**Current State**: Dashboard is read-only, displays information only

**Proposed Enhancements**:

- **Write Operations via UI**
  - Create new systems directly from dashboard
  - Edit system configuration (hostname, SSH details, etc.)
  - Create and edit sync groups via forms
  - Add/remove systems from sync groups
  - Enable/disable sync groups

- **Manual Sync Trigger**
  - Button to manually initiate sync check for a sync group
  - Force sync check for specific system
  - View sync progress in real-time

- **Log Viewer**
  - View recent application logs in dashboard
  - Filter logs by level (ERROR, WARNING, INFO)
  - Search logs by keyword
  - Export logs for troubleshooting

- **Notification System**
  - In-dashboard alerts for:
    - System going offline
    - Sync failures
    - Conflict detection
    - High error rates
  - Dismissible notifications
  - Notification history

**Impact**: Reduces need for API/CLI usage, makes ZFS Sync accessible to non-technical users

**Effort**: Medium (requires frontend and backend changes)

**Dependencies**: None

---

### 1.2 Automated Sync Execution

**Current State**: ZFS Sync generates sync instructions, but systems must execute them manually

**Proposed Enhancements**:

- **Built-in Sync Executor**
  - Optional service that executes sync commands automatically
  - Configurable per sync group (auto-execute vs manual)
  - Queue sync operations to avoid overwhelming systems
  - Retry failed syncs with exponential backoff

- **SSH Connection Pooling**
  - Reuse SSH connections for efficiency
  - Reduce connection overhead
  - Support for SSH connection multiplexing

- **Sync Queue Management**
  - Queue sync operations when multiple are needed
  - Prioritize syncs (by dataset, by sync group)
  - Limit concurrent syncs per system
  - Progress tracking for queued syncs

**Impact**: Reduces manual intervention by 90%, enables true automation

**Effort**: Medium-High (requires SSH execution, queue management, error handling)

**Dependencies**: SSH configuration must be complete

---

### 1.3 CLI Tool

**Current State**: Only REST API available, requires curl/HTTPie for command-line usage

**Proposed Enhancements**:

- **Command-line Interface** (`zfs-sync-cli`)
  - Installable Python package or standalone binary
  - Commands for common operations:
    - `zfs-sync-cli system register --hostname srv01 --platform linux`
    - `zfs-sync-cli system list`
    - `zfs-sync-cli sync check --sync-group production`
    - `zfs-sync-cli sync execute --system srv01`
    - `zfs-sync-cli status --system srv01`
    - `zfs-sync-cli sync-group create --name prod --systems srv01,srv02`

- **Configuration File Support**
  - Store API URL and credentials in config file
  - Support for multiple environments (dev, prod)
  - Secure credential storage

- **Output Formats**
  - Human-readable (default)
  - JSON (for scripting)
  - CSV (for data export)

**Impact**: Enables scripted automation, easier for power users

**Effort**: Medium (new package, command parsing, API client)

**Dependencies**: None

---

### 1.4 Improved Error Messages

**Current State**: Error messages are technical, may not be actionable

**Proposed Enhancements**:

- **User-Friendly Error Messages**
  - Clear, plain English descriptions
  - Context about what went wrong
  - What the user should do next

- **Error Codes**
  - Standardized error codes (e.g., `E_SYSTEM_NOT_FOUND`, `E_SYNC_FAILED`)
  - Documentation for each error code
  - Error code reference in documentation

- **Suggested Fixes**
  - Include resolution hints in API responses
  - Link to relevant documentation
  - Provide example commands to fix issues

**Impact**: Reduces support burden, improves user experience

**Effort**: Low-Medium (update error handling, documentation)

**Dependencies**: None

---

## Priority 2: Monitoring & Observability (Medium Impact, Medium Effort)

### 2.1 Metrics and Monitoring

**Current State**: Basic health checks, no metrics export

**Proposed Enhancements**:

- **Prometheus Metrics Endpoint**
  - `/metrics` endpoint with Prometheus format
  - Key metrics:
    - `zfs_sync_systems_total` - Total number of systems
    - `zfs_sync_systems_online` - Number of online systems
    - `zfs_sync_sync_operations_total` - Total sync operations
    - `zfs_sync_sync_operations_success` - Successful syncs
    - `zfs_sync_sync_operations_failed` - Failed syncs
    - `zfs_sync_sync_duration_seconds` - Sync operation duration
    - `zfs_sync_snapshots_total` - Total snapshots tracked
    - `zfs_sync_conflicts_total` - Active conflicts
    - `zfs_sync_api_requests_total` - API request count
    - `zfs_sync_api_request_duration_seconds` - API latency

- **Grafana Dashboard Templates**
  - Pre-built Grafana dashboards
  - Visualizations for:
    - System health over time
    - Sync success rates
    - Sync duration trends
    - API performance
    - Snapshot growth

**Impact**: Enables production monitoring, alerting, and capacity planning

**Effort**: Medium (metrics collection, Prometheus format, Grafana dashboards)

**Dependencies**: None (Prometheus/Grafana are optional)

---

### 2.2 Audit Logging

**Current State**: Basic logging exists, no structured audit trail

**Proposed Enhancements**:

- **Comprehensive Audit Trail**
  - Log all configuration changes:
    - System registration/removal
    - Sync group creation/modification
    - API key generation/rotation
    - System configuration updates
  - Log all sync operations:
    - Sync start/completion
    - Sync failures
    - Conflict detection/resolution

- **Queryable Audit Log**
  - API endpoint: `GET /api/v1/audit`
  - Filter by:
    - Date range
    - Event type
    - System ID
    - User/API key
  - Export audit logs (JSON, CSV)

**Impact**: Improves security, compliance, troubleshooting

**Effort**: Medium (audit logging infrastructure, query API)

**Dependencies**: None

---

### 2.3 Health Checks Enhancement

**Current State**: Basic health check exists

**Proposed Enhancements**:

- **Detailed Health Endpoints**
  - Component-level health:
    - Database connectivity
    - Disk space
    - Memory usage
    - SSH connectivity tests (per system)
  - Sync lag detection:
    - Time since last successful sync per dataset
    - Alert on sync lag exceeding threshold

- **Health Check Aggregation**
  - Overall system health score
  - Health check history
  - Health trends over time

**Impact**: Better visibility into system health, proactive issue detection

**Effort**: Low-Medium (extend health check service)

**Dependencies**: None

---

## Priority 3: Integration & Automation (Medium Impact, Low-Medium Effort)

### 3.1 Client Agent/Daemon

**Current State**: Systems must manually report snapshots and execute syncs

**Proposed Enhancements**:

- **zfs-sync-agent** - Daemon running on ZFS systems
  - Auto-register with witness service on first run
  - Automatic snapshot reporting:
    - Monitor ZFS for new snapshots
    - Report snapshots immediately or on schedule
    - Use ZFS event daemon (zed) integration
  - Auto-execute sync instructions:
    - Poll for sync instructions
    - Execute sync commands automatically
    - Update sync state after completion
  - Periodic heartbeat
  - Configuration via config file

- **Deployment**
  - Package as systemd service
  - Support for systemd timers
  - Configuration in `/etc/zfs-sync/agent.conf`

**Impact**: Eliminates need for manual scripts, true automation

**Effort**: Medium-High (new agent application, ZFS monitoring, sync execution)

**Dependencies**: None (optional component)

---

### 3.2 Integration with ZFS Tools

**Current State**: Manual integration with existing tools

**Proposed Enhancements**:

- **Sanoid/Syncoid Integration**
  - Plugin or hook for Sanoid
  - Report snapshots after Sanoid creates them
  - Coordinate with Syncoid for sync operations

- **Zrepl Integration**
  - Complement zrepl functionality
  - Use ZFS Sync for coordination, zrepl for execution
  - Share snapshot metadata

- **ZFS Native Hooks**
  - Use ZFS event daemon (zed) for snapshot notifications
  - Automatic snapshot reporting when snapshots are created
  - No manual scripting required

**Impact**: Works with existing ZFS tooling, reduces setup complexity

**Effort**: Medium (integration code, documentation)

**Dependencies**: External tools (Sanoid, zrepl, zed)

---

### 3.3 Ansible/Terraform Modules

**Current State**: No infrastructure-as-code support

**Proposed Enhancements**:

- **Ansible Modules**
  - `zfs_sync_system` - Register/manage systems
  - `zfs_sync_sync_group` - Create/manage sync groups
  - `zfs_sync_snapshot` - Report snapshots
  - Example playbooks for common scenarios

- **Terraform Provider**
  - `zfs_sync_system` resource
  - `zfs_sync_sync_group` resource
  - State management for ZFS Sync configuration

**Impact**: Enables infrastructure-as-code, version control for configuration

**Effort**: Medium-High (new modules/provider, testing, documentation)

**Dependencies**: Ansible/Terraform (external tools)

---

## Priority 4: Advanced Sync Features (Lower Priority, Higher Effort)

### 4.1 Bandwidth Management

**Current State**: No bandwidth control

**Proposed Enhancements**:

- **Rate Limiting**
  - Limit sync bandwidth per system
  - Limit sync bandwidth per sync group
  - Configurable limits (MB/s, GB/hour)

- **QoS Support**
  - Prioritize certain sync operations
  - High-priority sync groups get more bandwidth
  - Low-priority syncs can be throttled

- **Compression**
  - Enable/force compression for sync transfers
  - Configurable compression level
  - Trade-off between CPU and bandwidth

**Impact**: Better network resource management, prevents bandwidth saturation

**Effort**: High (requires ZFS send/receive integration, bandwidth monitoring)

**Dependencies**: ZFS compression support

---

### 4.2 Encryption Support

**Current State**: Relies on ZFS native encryption

**Proposed Enhancements**:

- **Encrypted Sync**
  - Support for encrypted ZFS sends
  - Verify encryption keys match
  - Handle encrypted dataset syncs

- **Key Management**
  - Store/manage encryption keys (optional)
  - Integration with key management systems
  - Key rotation support

- **End-to-End Encryption**
  - Encrypt data in transit (TLS for API)
  - Encrypt sync data streams
  - Certificate management

**Impact**: Enhanced security for sensitive data

**Effort**: High (encryption integration, key management)

**Dependencies**: ZFS encryption, TLS support

---

### 4.3 Smart Conflict Resolution

**Current State**: Basic conflict detection exists

**Proposed Enhancements**:

- **Automatic Resolution Strategies**
  - More sophisticated auto-resolution:
    - Use newest snapshot (existing)
    - Use largest snapshot (existing)
    - Use majority vote (new)
    - Use source of truth system (new)
  - Configurable per sync group

- **Conflict Prevention**
  - Detect potential conflicts before they happen
  - Warn about diverging snapshots
  - Suggest preventive actions

**Impact**: Reduces manual conflict resolution, improves reliability

**Effort**: Medium-High (enhanced conflict detection, resolution logic)

**Dependencies**: None

---

### 4.4 Cross-Platform Snapshot Translation

**Current State**: Basic cross-platform support exists

**Proposed Enhancements**:

- **Platform Differences Handling**
  - Handle ZFS implementation differences (Linux vs FreeBSD)
  - Feature detection per system
  - Compatibility mode for incompatible features

- **Feature Negotiation**
  - Detect available ZFS features per system
  - Use lowest common denominator for syncs
  - Warn about feature mismatches

**Impact**: Better cross-platform compatibility

**Effort**: Medium (feature detection, compatibility layer)

**Dependencies**: ZFS feature detection

---

## Implementation Timeline

### Immediate (Next 1-2 Weeks)
1. ✅ **Create documentation** - Setup, Operations, Troubleshooting, Dashboard guides
2. ✅ **Update existing documentation** - Cross-references and links

### Short-term (Next 1-2 Months)
1. **Enhanced Dashboard Functionality** - Write operations, manual sync trigger
2. **Improved Error Messages** - User-friendly errors with suggested fixes
3. **CLI Tool** - Basic command-line interface

### Medium-term (Next 3-6 Months)
1. **Automated Sync Execution** - Built-in sync executor with queue management
2. **Client Agent/Daemon** - Automated snapshot reporting and sync execution
3. **Prometheus Metrics** - Full observability stack
4. **Audit Logging** - Comprehensive audit trail

### Long-term (6+ Months)
1. **Ansible/Terraform Modules** - Infrastructure-as-code support
2. **Integration Plugins** - Sanoid, Syncoid, Zrepl integration
3. **Advanced Sync Features** - Bandwidth management, encryption support
4. **Smart Conflict Resolution** - Enhanced conflict handling

---

## Success Metrics

### Usability Metrics
- **Time to create sync group**: Reduce from 10+ API calls to single dashboard action
- **Manual intervention**: Reduce by 90% with automated sync execution
- **Error resolution time**: Reduce by 50% with improved error messages
- **CLI adoption**: 80% of power users use CLI tool

### Feature Metrics
- **Dashboard usage**: 70% of users use dashboard for daily operations
- **Automation rate**: 95% of syncs executed automatically
- **Monitoring coverage**: 100% of production deployments use metrics
- **Integration adoption**: 50% of users integrate with existing tools

---

## Decision Log

### Excluded Features (Per User Requirements)

The following features were considered but excluded from this roadmap:

- **Webhook/Notification System** - Not needed per user requirements
- **Snapshot Policy Engine** - Not needed per user requirements
- **Advanced Scheduling** - Not needed per user requirements
- **Multi-tenancy Support** - Not needed per user requirements

These features may be reconsidered in the future if requirements change.

---

## Related Documentation

- [SETUP_GUIDE.md](SETUP_GUIDE.md) - Current setup procedures
- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) - Current operations procedures
- [TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md) - Current troubleshooting
- [ARCHITECTURE.md](../ARCHITECTURE.md) - System architecture

---

## Contributing

If you'd like to contribute to any of these improvements:

1. Review the existing codebase and architecture
2. Check for existing issues or create a new one
3. Discuss the approach before implementing
4. Follow the project's coding standards and testing requirements
5. Update documentation as needed
