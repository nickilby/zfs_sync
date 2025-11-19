# Automated ZFS Snapshot Sync Monitor & Recovery System

## 1. Project Overview
This project defines an automated system responsible for monitoring, validating, and repairing ZFS snapshot replication between primary SANs (HQS8 / HQS10) and offline backup SANs (HQS1 / HQS7). The goal is to eliminate manual intervention, ensure continuous replication, and provide complete visibility through a web interface.

The system runs as a containerised application on a dedicated witness machine and connects to all SANs over SSH.

---

## 2. Objectives
- Continuously monitor snapshot replication health.
- Detect loss of common snapshots and broken replication chains.
- Automatically repair replication using incremental or re-anchor sends.
- Provide a browser-based interface for visibility, configuration display, and manual actions.
- Run independently of SANs via a Docker container on a 3rd-party witness host.

---

## 3. Deployment Architecture
### Components Inside the Docker Container
- **FastAPI Web Server** — REST API + HTML UI.
- **Scheduler (APScheduler)** — Periodic scan and repair tasks.
- **Sync Engine** — Snapshot discovery, comparison, repair logic.
- **SQLite Database** — Stores runs, actions, state, logs.
- **Config Loader** — Reads `/config/app-config.yaml`.

### External Dependencies
- Witness host with Docker.
- SSH access to HQS8, HQS10, HQS1, HQS7 using key-based authentication.
- Bind-mounted volumes:
  - `/config` — configuration files
  - `/logs` — log output
  - `/data` — SQLite DB

---

## 4. Connectivity Model
The app connects to SANs using SSH:
```
ssh zfsadmin@hqs8 "zfs list -t snapshot ..."
```

Replication commands are orchestrated by the app using a two-hop SSH pipeline:
```
ssh primary "zfs send ..." | ssh backup "zfs receive -F ..."
```

---

## 5. Configuration Structure
### Example `/config/app-config.yaml`
```yaml
san_hosts:
  hqs8:
    hostname: hqs8.storage.local
    ssh_user: zfsadmin
  hqs10:
    hostname: hqs10.storage.local
    ssh_user: zfsadmin
  hqs1:
    hostname: hqs1.storage.local
    ssh_user: zfsadmin
  hqs7:
    hostname: hqs7.storage.local
    ssh_user: zfsadmin

pairs:
  - name: "HQS8 → HQS1"
    primary: "hqs8"
    backup: "hqs1"
    datasets:
      - name: "hqs8p1/HQS8DAT1"
        backup_dataset: "hqs1p1/HQS8DAT1"
        max_delay_hours: 72
        auto_repair: true
        dry_run: false
  - name: "HQS10 → HQS7"
    primary: "hqs10"
    backup: "hqs7"
    datasets:
      - name: "hqs10p1/HQS10DAT1"
        backup_dataset: "hqs7p1/HQS10DAT1"
        max_delay_hours: 72
        auto_repair: true

scheduler:
  interval_minutes: 30
```

---

## 6. Internal Data Model (SQLite)
### Tables
- **san_host** — SAN endpoints
- **san_pair** — Primary → Backup groupings
- **dataset** — Monitored dataset definitions
- **snapshot_state** — Last evaluated status for each dataset
- **run** — A full scan attempt (scheduled or manual)
- **action** — Actions taken during a run (repairs, checks)

---

## 7. Workflow Logic
### 7.1 Snapshot Discovery
For each dataset, retrieve snapshot lists from primary and backup:
```
zfs list -t snapshot -o name,creation -s creation -r <dataset>
```

### 7.2 Last Common Snapshot Logic
- Extract snapshot IDs from full names.
- Intersect primary and backup snapshot sets.
- Choose newest common snapshot.

### 7.3 Status Classification
| Status | Meaning |
|--------|---------|
| **HEALTHY** | Backup within acceptable delay threshold |
| **WARNING** | Delayed but still within max window |
| **BROKEN** | No common snapshot or beyond delay |
| **REPAIRING** | Repair in progress |

### 7.4 Auto-Repair Behaviour
- **Incremental Repair** — if last common snapshot exists
- **Re-anchor Repair** — if no common snapshot exists
- **Dry-Run Mode** — preview commands only

Incremental send example:
```
ssh primary "zfs send -I <base> <latest>" | \
ssh backup "zfs receive -F <dataset>"
```

Re-anchor example:
```
ssh primary "zfs send <snapshot>" | ssh backup "zfs receive -F <dataset>"
```

---

## 8. Scheduler
- Runs every X minutes (configurable).
- Performs full check of all SAN pairs and datasets.
- Logs run details and actions executed.

Manual trigger route also available via API and UI.

---

## 9. Web Interface
### Features
- **Dashboard** showing status of all datasets
- **Dataset Detail** view including snapshot times, repair options
- **Run Now** button
- **Repair Preview** (dry-run)
- **Logs** viewer
- **Config** view (read-only)

### Technology
- FastAPI backend
- Jinja2 templates (simple, lightweight)

---

## 10. API Endpoints
- `GET /api/status` — summary of all dataset states
- `POST /api/run` — run full scan and repair
- `GET /api/datasets` — list datasets
- `GET /api/datasets/{id}` — dataset detail
- `POST /api/datasets/{id}/run` — run for one dataset
- `GET /api/runs` — run history
- `GET /api/runs/{id}` — run detail
- `POST /api/config/reload` — reload config file

---

## 11. Docker Container Layout
```
/app      → Application code
/config   → Mounted config (app-config.yaml)
/logs     → Application logs
/data     → SQLite database
```

Dockerfile uses `python:3.12-slim`, installs:
- openssh-client
- fastapi, uvicorn
- apscheduler
- sqlalchemy
- pyyaml
- jinja2

Port: **8080**

---

## 12. Safety and Protection
- Dry-run mode for safe testing
- Warning banners for destructive ZFS operations (`receive -F`)
- Timeout and retry behaviour on SSH calls
- No automatic destructive dataset operations

---

## 13. Deliverables
- Fully functional Dockerised application
- Web dashboard (FastAPI/Jinja2)
- Sync engine with incremental and re-anchor repairs
- Configurable scheduler
- Historical logs and audit trail

---

# End of Document

