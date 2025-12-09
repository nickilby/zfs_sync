# ZFS Sync Documentation

Welcome to the ZFS Sync documentation. ZFS Sync is a witness service that coordinates ZFS snapshot synchronization across multiple systems, ensuring data consistency and enabling reliable backup and replication workflows.

## What is ZFS Sync?

ZFS Sync acts as a centralized witness that:
- Tracks snapshot states across multiple ZFS systems
- Detects when snapshots are missing or out of sync
- Coordinates synchronization operations between systems
- Monitors system health and connectivity
- Supports both bidirectional and directional (hub-and-spoke) sync modes

## Quick Start

New to ZFS Sync? Start here:

1. **[Setup Guide](SETUP_GUIDE.md)** - Complete setup instructions for first-time installation
2. **[Quick Start Guide](../QUICK_START.md)** - Fast setup for Linux systems
3. **[How to Use](../HOW_TO_USE.md)** - Beginner-friendly API usage guide

## Documentation

### Getting Started

- **[Setup Guide](SETUP_GUIDE.md)** - Installation, configuration, system registration, SSH setup, and sync group creation
- **[Quick Start](../QUICK_START.md)** - Fast setup guide for experienced users
- **[Architecture](../ARCHITECTURE.md)** - Technical architecture and design documentation

### Operations

- **[Operations Guide](OPERATIONS_GUIDE.md)** - Daily operations, automation examples, maintenance tasks, performance tuning, and backup/recovery
- **[Dashboard Guide](DASHBOARD_GUIDE.md)** - Web dashboard usage and features

### Troubleshooting

- **[Troubleshooting Guide](TROUBLESHOOTING_GUIDE.md)** - Systematic diagnostic steps and solutions for common issues

### Development

- **[Improvements Roadmap](IMPROVEMENTS_ROADMAP.md)** - Future improvements and feature roadmap
- **[Project Setup Guide](../PROJECT_SETUP_GUIDE.md)** - Developer setup and CI/CD configuration

## Key Features

- **Pool-Agnostic Dataset Comparison** - Sync datasets across systems with different pool names
- **Bidirectional Sync** - All systems in a group sync with each other
- **Directional Sync** - Hub-and-spoke distribution from master to replicas
- **SSH Integration** - Automated sync command generation with SSH support
- **Web Dashboard** - Real-time monitoring via web interface
- **RESTful API** - Complete API for automation and integration
- **Conflict Detection** - Automatic detection and resolution of snapshot conflicts
- **Health Monitoring** - System health tracking and heartbeat mechanism

## Use Cases

- **Multi-Site Backup** - Keep snapshots synchronized across geographically distributed systems
- **Disaster Recovery** - Ensure critical snapshots exist on multiple systems
- **Data Replication** - Coordinate snapshot creation before replication operations
- **Backup Verification** - Verify that backup snapshots are consistent across systems

## API Documentation

When running ZFS Sync, interactive API documentation is available at:

```
http://your-server:8000/docs
```

This provides a Swagger/OpenAPI interface where you can test all API endpoints.

## Getting Help

- **Troubleshooting**: See the [Troubleshooting Guide](TROUBLESHOOTING_GUIDE.md) for common issues and solutions
- **Operations**: See the [Operations Guide](OPERATIONS_GUIDE.md) for daily operations and maintenance
- **GitHub Repository**: View the source code and issues in the repository

## Version

This documentation is for **ZFS Sync v2.0**.

---

**Note**: This documentation is also available in the GitHub repository. For the latest updates and source code, visit the repository.
