# Migration recovery

How to bring an existing `zfs_sync` database under Alembic control.

## Why this is needed

Migrations have never run anywhere. The repository had `alembic/versions/` but
no `alembic.ini` and no `alembic/env.py`, so every `alembic` command failed
before it read a single revision. Two revisions both claimed to follow `001`
with incompatible identifiers, and one named a `down_revision` that did not
exist. Nothing created the base tables that the other revisions add columns to.

In practice the schema was created by `Base.metadata.create_all()` at startup.
That call creates missing tables and **never alters existing ones**, so as the
models changed, deployed databases silently stayed behind.

The visible symptom: `sync_groups` has no `directional` or `hub_system_id`
column, while the planner branches on both. Every sync group is reported as
unplannable, and the service appears to work while synchronising nothing.

`docs/fix_sync_states_schema.sql` was the manual `DROP TABLE` workaround
adopted instead of fixing this. It should not be needed again.

## Before you start

- **Take a backup.** For SQLite, copy the file. For PostgreSQL, `pg_dump`.
  Every step below has been rehearsed, but a recovery that cannot be undone is
  not one you should run on a backup coordinator.
- Stop the service. Migrations rebuild tables on SQLite, and a writer mid-flight
  will either fail or be lost.
- Know your database URL. `alembic` reads it from application settings, so run
  these commands with the same configuration the service uses, or pass
  `-x db_url=...` explicitly.

## Step 1: determine the schema's actual state

Run this against the database you are recovering:

```bash
python - <<'PY'
from sqlalchemy import create_engine, inspect
from zfs_sync.config import get_settings

engine = create_engine(get_settings().database_url)
inspector = inspect(engine)
tables = set(inspector.get_table_names())

def columns(table):
    return {c["name"] for c in inspector.get_columns(table)} if table in tables else set()

if not tables:
    print("EMPTY -> run: alembic upgrade head")
elif "alembic_version" in tables and list(
    engine.connect().execute(__import__("sqlalchemy").text("SELECT version_num FROM alembic_version"))
):
    print("ALREADY UNDER ALEMBIC -> run: alembic upgrade head")
elif "directional" in columns("sync_groups") and "sync_runs" in tables:
    print("AT HEAD -> run: alembic stamp head")
elif "dataset" in columns("sync_states"):
    print("AT 003 -> run: alembic stamp 003 && alembic upgrade head")
elif "description" in columns("sync_groups"):
    print("AT 002 -> run: alembic stamp 002 && alembic upgrade head")
elif "ssh_hostname" in columns("systems"):
    print("AT 001 -> run: alembic stamp 001 && alembic upgrade head")
else:
    print("AT 000 -> run: alembic stamp 000 && alembic upgrade head")
PY
```

The revisions, in order:

| Revision | Adds |
|---|---|
| `000` | Base tables (the baseline that was missing) |
| `001` | `systems.ssh_hostname`, `ssh_user`, `ssh_port` |
| `002` | `sync_groups.description` |
| `003` | `sync_states`: `snapshot_id` replaced by `dataset` |
| `004` | `sync_groups.directional`, `hub_system_id` |
| `005` | `sync_runs` table; snapshot sizes widened to `BigInteger` |

## Step 2: stamp, then upgrade

`stamp` records where the database already is **without running anything**. It
is the step that stops Alembic replaying revisions against a schema that has
already had them applied by `create_all()`.

```bash
alembic stamp <revision from step 1>
alembic upgrade head
```

A database that reported `AT 002` — the state the development database was
found in — takes `003`, `004` and `005`.

## Step 3: verify

```bash
alembic current          # should print the head revision
python - <<'PY'
from sqlalchemy import create_engine, inspect
from zfs_sync.config import get_settings
from zfs_sync.database.base import Base
import zfs_sync.database.models  # noqa

engine = create_engine(get_settings().database_url)
actual = {t for t in inspect(engine).get_table_names() if t != "alembic_version"}
expected = set(Base.metadata.tables)
print("missing tables:", sorted(expected - actual) or "none")
print("unexpected tables:", sorted(actual - expected) or "none")
PY
```

## Step 4: set a hub on existing sync groups

This is the step that is easy to miss, and without it nothing will sync.

Groups created before revision `004` have `directional = false` and
`hub_system_id = NULL`, because those columns did not exist when the rows were
written. The planner will report them as:

- `group_not_directional` — the group is still in the (unreachable)
  bidirectional mode, or
- `group_hub_not_set` — directional, but no hub has been chosen.

Set both through the API for each group that should replicate:

```bash
curl -X PUT "$WITNESS_API_URL/api/v1/sync-groups/$GROUP_ID" \
  -H "Content-Type: application/json" \
  -d '{"directional": true, "hub_system_id": "<the system that holds the data>"}'
```

The hub **must be one of the group's own systems**. Choosing a system that is
not a member reports `hub_not_in_group`.

Then confirm the group plans:

```bash
curl "$WITNESS_API_URL/api/v1/sync/groups/$GROUP_ID/decisions" | jq '.skipped_reason, .decision_count'
```

`skipped_reason` should be `null`.

### Step 5: give every target an SSH identity

Rehearsing this recovery on the development database produced exactly one
decision, and it was `missing_ssh_identity`: the target system had no
`ssh_hostname`, so no command could be addressed to it. Commands are sent over
SSH from the hub, so each target needs one:

```bash
curl -X PUT "$WITNESS_API_URL/api/v1/systems/$SYSTEM_ID" \
  -H "Content-Type: application/json" \
  -d '{"ssh_hostname": "spoke1-san", "ssh_user": "backup", "ssh_port": 22}'
```

`ssh_hostname` may be an ssh_config alias, which is usually the tidiest option
since it keeps key selection and jump hosts out of this service.

### Reading the outcome

`/decisions` reports one entry per (dataset, target) pair, each with a reason.
The ones you are most likely to see straight after a recovery:

| Reason | Meaning |
|---|---|
| `group_not_directional` | The group predates directional sync. Step 4. |
| `group_hub_not_set` | Directional, but no hub chosen. Step 4. |
| `hub_not_in_group` | The chosen hub is not a member of the group. |
| `missing_ssh_identity` | The target has no `ssh_hostname`. Step 5. |
| `in_sync_within_window` | Nothing to do. This is the healthy answer. |
| `target_diverged` | The target has its own snapshots; the sync will use `zfs receive -F`, discarding them. |

## New databases

No recovery is needed. `init_db()` creates the schema and stamps it at head, so
`alembic upgrade head` is a no-op afterwards. `init_db()` no longer touches a
database that already has tables — it warns instead, because silently leaving a
drifted table exactly as it is was the original problem.

## If something goes wrong

Every revision has a tested `downgrade`, and the round trip is exercised in CI:

```bash
alembic downgrade <the revision you stamped>
```

If a migration fails part way on SQLite, restore the backup rather than
attempting to continue: batch migrations rebuild tables, and a half-applied
rebuild is not a state worth reasoning about.
