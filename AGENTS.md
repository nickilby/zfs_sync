# Working on zfs_sync

Guidance for anyone — human or agent — changing this codebase.

This replaces `.github/agent-instructions.md`, which contained eight claims
that were false against the code: that API keys were stored hashed, that
logging was structured JSON, that SQLAlchemy was used asynchronously, that
connection pooling was configured, that a `get_api_key_auth` dependency
existed, that incremental sends used `-i`, that the health endpoint was at
`/health`, and an unsourced completion percentage. Acting on any of them would
have made things worse, so the accuracy of this file matters more than its
length.

## What this service is

A witness. It holds every host's snapshot inventory, decides which datasets are
behind, and returns `zfs send | ssh … zfs receive` commands for those hosts to
run. **It never executes `zfs` or `ssh` itself.** Do not add direct execution;
that boundary is the reason the service can be run somewhere other than the
storage hosts.

It is a privileged control plane: it tells root-capable machines what to run.
Treat anything that influences a generated command — `ssh_hostname`,
`ssh_user`, pool and dataset names, snapshot inventories — as security-relevant
input.

## Layout

```
zfs_sync/
├── api/
│   ├── app.py            create_app() builds the application
│   ├── errors.py         one place that maps domain errors to status codes
│   ├── middleware/auth.py
│   ├── routes/           HTTP only; no business logic
│   └── schemas/          Pydantic request/response models
├── services/
│   └── sync/
│       ├── policy.py     pure send-window rules; no DB, no clock, no logging
│       ├── planner.py    the only stage that touches the database
│       ├── renderer.py   the only stage that builds command strings
│       ├── types.py      typed domain objects
│       ├── state.py      the sync_states projection
│       └── outcomes.py   reported execution results
├── database/
│   ├── models.py         SQLAlchemy models
│   ├── errors.py         typed integrity errors
│   └── repositories/     data access
├── config/               settings and startup validation
└── enums.py
```

## The sync core

Read `services/sync/policy.py` before changing planning behaviour. The pipeline
is deliberately one-directional:

```
repositories -> planner -> policy -> SyncDecision -> renderer / response
```

Three rules keep it that way:

- **`policy.py` stays pure.** No database, no `datetime.now()`, no logger. Time
  is a parameter. A test asserts this. The previous implementation spread the
  same rules across two modules, and the functions that had unit tests were not
  the ones the service called — the suite stayed green while the policy did
  something else entirely.
- **The unit of work is `(dataset, source, target)`**, never the dataset alone.
  Consolidating on dataset is what silently dropped every target after the
  first.
- **A decision is emitted for every pair considered**, including declined ones,
  with a machine-readable reason. An empty instruction list must always explain
  itself. Do not add a code path that filters silently.

## Conventions

- **Errors**: raise typed domain errors (`SyncGroupNotFound`,
  `DuplicateRecord`, `InvalidReference`, `CommandRenderError`) and let
  `api/errors.py` map them. Do not decide status codes in a route; that is how
  the same condition came to return 404 on one endpoint and 500 on two others.
- **Logging**: lazy `%s` formatting, not f-strings. WARNING means an operator
  should act — routine outcomes are INFO or DEBUG. Logging is plain text, not
  JSON.
- **Database**: SQLAlchemy 2.0, fully synchronous. No pooling is configured. Any
  blocking database work reached from an async context belongs in a worker
  thread — the scheduler stalled the single-worker API for the length of a scan
  before that was fixed.
- **Schema changes**: a model change needs an Alembic revision. `create_all()`
  never alters an existing table, which is how deployments drifted away from
  the models. Run `alembic upgrade head` and `alembic downgrade` before
  committing; CI asserts a single head and a full round trip.
- **Naming conventions are configuration.** Do not hardcode a snapshot naming
  rule. `snapshot_anchor_pattern` exists because `endswith("-000000")` silently
  produced zero sync detection at any site not using that convention.
- **Commands**: every interpolated value goes through `shlex.quote`, including
  the SSH target. Clients rebuild commands from structured fields rather than
  evaluating the rendered string.

## Tests

```bash
pytest                 # everything
pytest -m unit         # fast, no HTTP
pytest -m integration  # through the API
pytest -n 4            # parallel; each test gets its own database
```

Markers are applied by location, so a test in `tests/unit/` is a unit test
without a decorator.

Two habits worth keeping:

- When fixing a bug, **write the failing test first**, and make it assert the
  behaviour rather than the implementation. Several bugs here survived because
  the test suite asserted that a function returned something, not that the
  service did the right thing.
- When changing behaviour deliberately, **characterize the old behaviour
  first** in a test, so the diff shows what changed rather than leaving it to
  be discovered in production.

## What not to do

- Do not execute `zfs` or `ssh` from the service.
- Do not add an endpoint without authentication. It is applied per router in
  `create_app`; `test_auth_coverage.py` fails if an unlisted open endpoint
  appears.
- Do not return a shorter list to indicate partial failure. Say what failed and
  why.
- Do not put `eval` in a client script.
- Do not reintroduce a per-commit version bump. Rewriting the version in
  several tracked files on every commit is what made every merge conflict in
  those files, which is how unresolved conflict markers reached `main`. Bump at
  release: `python scripts/increment_version.py`.

## Related documents

| Document | What it covers |
|---|---|
| `ARCHITECTURE.md` | Design and component boundaries |
| `SECURITY.md` | Threat model, authentication, hardening |
| `CONTRIBUTING.md` | How to get set up and submit a change |
| `docs/MIGRATION_RECOVERY.md` | Bringing an existing database under Alembic |
| `docs/ZNAPZEND_INTEGRATION.md` | Running alongside znapzend |
| `docs/OPERATIONS_GUIDE.md` | Day-to-day operation |
| `docs/TROUBLESHOOTING_GUIDE.md` | Diagnosing a fleet that is not syncing |
