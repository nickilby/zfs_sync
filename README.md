# zfs_sync

A witness service that tracks ZFS snapshots across a fleet and coordinates
replication between hosts.

ZFS hosts report what snapshots they hold. `zfs_sync` compares those
inventories, works out which datasets are behind and by how much, and returns
the `zfs send | ssh … zfs receive` commands needed to catch them up. It never
runs `zfs` or `ssh` itself — it is a coordinator, not an agent, so it can live
somewhere other than the storage hosts.

The thing it gives you that a per-host tool cannot: **one place that knows
whether the whole fleet is actually in the state you think it is**, and that
tells you *why* when it is not.

## How it works

```
      ┌──────────────────────────────────────────┐
      │              zfs_sync                    │
      │   inventories → plan → instructions      │
      │            ↑                ↓            │
      └────────────┼────────────────┼────────────┘
                   │                │
         reports   │                │  instructions + outcomes
                   │                ↓
        ┌──────────┴───┐    ┌───────────────┐
        │  hub (ZFS)   │───▶│  spoke (ZFS)  │
        └──────────────┘    └───────────────┘
              zfs send -I … | ssh … zfs receive
```

1. Each host reports its snapshot inventory.
2. `zfs_sync` plans every `(dataset, source, target)` pair and decides, for
   each, whether a sync is needed — recording a reason either way.
3. The source host fetches its instructions, runs them, and reports what
   happened.
4. The recorded outcome drives the status summary and dashboard.

Every pair the planner considered appears in the response, including the ones
it declined. An empty result always says why.

## Status

Working, and under active hardening. The sync core, the execution feedback
loop, authentication, and migrations are in place and tested. See
`docs/IMPROVEMENTS_ROADMAP.md` for what is planned next.

## Quick start

```bash
git clone <this repo> && cd zfs_sync
python -m venv .venv && . .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements.txt
pip install -e .

# Bring the database up to date (creates it if absent).
alembic upgrade head

uvicorn zfs_sync.api.app:app --host 0.0.0.0 --port 8000
```

Or with Docker:

```bash
docker compose up -d
```

Then open <http://localhost:8000/dashboard>, or the API docs at
<http://localhost:8000/docs>.

Register a host and keep the key it returns — it is shown once and stored only
as a digest:

```bash
curl -X POST http://localhost:8000/api/v1/systems \
  -H "Content-Type: application/json" \
  -d '{"hostname": "hub1", "platform": "linux", "ssh_hostname": "hub1-san"}'
```

Full instructions, including sync groups and SSH setup, are in
[docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md).

## Why a dataset is not syncing

The question this service exists to answer:

```bash
curl -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/v1/sync/groups/$GROUP_ID/decisions" | jq '.decisions'
```

Every pair, with a reason:

| Reason | Meaning |
|---|---|
| `in_sync_within_window` | Nothing to do. The healthy answer. |
| `no_eligible_ending_snapshot` | Nothing old enough to send, or the naming pattern does not match your snapshots. |
| `no_common_base` | The two sides share no snapshot; a full send is planned. |
| `target_diverged` | The target holds its own snapshots; the sync will use `zfs receive -F`, discarding them. |
| `missing_ssh_identity` | The target has no `ssh_hostname` recorded. |
| `group_not_directional` / `group_hub_not_set` | The sync group needs a hub. |

## Using it with znapzend

`zfs_sync` is happy to let something else own snapshot creation and retention.
If you run znapzend, the usual split is: znapzend creates and expires
snapshots; `zfs_sync` observes the fleet, verifies backups landed, and plans
replication where znapzend is not already doing it.

One setting matters — the snapshot naming pattern. See
[docs/ZNAPZEND_INTEGRATION.md](docs/ZNAPZEND_INTEGRATION.md).

## Documentation

| Document | For |
|---|---|
| [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md) | First-time setup |
| [docs/OPERATIONS_GUIDE.md](docs/OPERATIONS_GUIDE.md) | Running it day to day |
| [docs/TROUBLESHOOTING_GUIDE.md](docs/TROUBLESHOOTING_GUIDE.md) | When something is not syncing |
| [docs/MIGRATION_RECOVERY.md](docs/MIGRATION_RECOVERY.md) | Bringing an existing database under Alembic |
| [docs/ZNAPZEND_INTEGRATION.md](docs/ZNAPZEND_INTEGRATION.md) | Running alongside znapzend |
| [docs/DASHBOARD_GUIDE.md](docs/DASHBOARD_GUIDE.md) | The web dashboard |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How it is built |
| [AGENTS.md](AGENTS.md) | Changing the code |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Submitting a change |
| [SECURITY.md](SECURITY.md) | Threat model and hardening |

## Security

The API is a privileged control plane: it tells root-capable machines what to
run. Every endpoint that reads or writes fleet data requires an API key, keys
are stored hashed, and a system may act only for itself.

Two settings to review before exposing it anywhere:
`registration_token` (registration issues a working key) and
`cors_allow_origins`. See [SECURITY.md](SECURITY.md).

## Requirements

- Python 3.9+
- SQLite (default) or PostgreSQL
- ZFS on the hosts being coordinated — not on the machine running this service

## Licence

MIT. See [LICENSE](LICENSE).
