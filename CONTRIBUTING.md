# Contributing

## Getting set up

```bash
git clone <this repo> && cd zfs_sync
python -m venv .venv && . .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
pip install -e .
pytest
```

You do not need ZFS installed to develop or test. The service never runs `zfs`
itself — it generates commands for other hosts to run — so the whole suite
works against SQLite on any platform.

## Before you open a pull request

```bash
pytest                                  # all green
ruff check zfs_sync/ tests/ alembic/    # clean
alembic upgrade head && alembic downgrade base && alembic upgrade head
```

CI runs the same checks across Python 3.9–3.12, plus a Docker build and a
dependency audit.

## What a good change looks like

**Read `AGENTS.md` first.** It describes the boundaries that matter — what the
service must never do, how the sync core is layered, and the conventions that
exist because their absence caused a specific bug.

Beyond that:

- **Tests assert behaviour, not implementation.** Several bugs here survived
  for a long time because tests asserted that a function returned something
  rather than that the service did the right thing. A test that would still
  pass if the feature were disconnected is not protecting anything.
- **A bug fix starts with a failing test.** It is the only way to know the fix
  addresses the bug rather than something adjacent to it.
- **A deliberate behaviour change starts with a characterization test** of the
  old behaviour, so the diff shows what changed.
- **Explain the why, not the what, in comments.** The code says what it does.
  A comment earns its place by saying why it is that way — usually which
  failure it prevents.

## Commits

Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`) with a
body that explains the reasoning. If a change fixes something subtle, the
commit message is where the next person will look for why.

Do not bump the version in a commit. It is set at release time with
`python scripts/increment_version.py`; bumping per commit is what made every
branch conflict on the same four files.

## Reporting a bug

Useful reports include the version (`GET /api/v1/health`), what you expected,
what happened, and — if a dataset is not syncing — the output of:

```bash
curl -H "X-API-Key: $API_KEY" \
  "$WITNESS_API_URL/api/v1/sync/groups/$GROUP_ID/decisions"
```

That endpoint reports every pair the planner considered and why each one was or
was not actioned, which is usually the whole answer.

Security issues go to the maintainer privately — see `SECURITY.md`.
