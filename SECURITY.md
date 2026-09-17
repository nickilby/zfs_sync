# Security

## Reporting a vulnerability

Please report security issues privately to the maintainer rather than opening a
public issue. Include the version or commit, what you observed, and how to
reproduce it.

## What this service is, in security terms

`zfs_sync` is a coordinator. It never runs `zfs` or `ssh` itself, but it *does*
tell other machines what to run, and those machines run it with enough
privilege to send and receive ZFS streams. Treat the API as a privileged
control plane, not as a reporting tool.

Two properties follow from that:

- Anything that can write a system's `ssh_hostname` can influence where a hub
  sends data.
- Anything that can write a snapshot inventory can influence which snapshots a
  hub is told to send, and which it is told are missing.

Both are authenticated.

## Authentication

Every endpoint that reads or writes fleet data requires an API key in an
`X-API-Key` header. The exceptions are the health probes, the dashboard page
and its assets, and system registration; they are listed explicitly in
`tests/integration/test_api/test_auth_coverage.py`, which fails if a new
unauthenticated endpoint appears.

Keys are stored as a SHA-256 digest and returned exactly once, at registration
or rotation.

A digest rather than a password KDF is deliberate, and worth explaining because
static analysis flags it. KDFs exist because passwords are low-entropy and
human-chosen, so an attacker holding the hashes can guess them cheaply against
a fast hash. These are not passwords: `secrets.token_urlsafe` produces at least
128 bits of entropy, which no amount of hashing speed brings within reach of a
brute force. A KDF would add latency to every authenticated request -- the
digest is checked on each one -- for no gain.

That argument depends entirely on the token being large, so the assumption is
enforced rather than trusted: `api_key_length` is rejected below 16 bytes. The
previous floor was 8 bytes (64 bits), which a well-resourced attacker holding
the database could have exhausted offline.

A system may act only for itself. It cannot report another system's snapshots,
edit another system's record, or rotate another system's key.

## Hardening checklist

| Setting | Why |
|---|---|
| `registration_token` | Registration issues a working API key. Without this, anyone who can reach the service can mint credentials for it. |
| `cors_allow_origins` | Defaults to `*` for local development. Name your dashboard's origin in production; credentialed requests are only permitted when specific origins are named. |
| `secret_key` | Set via `ZFS_SYNC_SECRET_KEY`. |
| Network exposure | The API returns SSH hostnames, pools and dataset names. Keep it on a management network rather than the public internet. |
| `POSTGRES_PASSWORD` | Required with no default; `docker compose` refuses to start without it. |

## Executing generated commands

The API returns a rendered `zfs send | ssh … zfs receive` string for display
and dry runs. **Do not `eval` it.** The shipped executor rebuilds the command
from the structured fields in the response and runs it as an argument vector,
so nothing the API returns is interpreted as shell syntax. A contract test
asserts the executor contains no `eval`.

Values that reach a command are quoted with `shlex.quote`, and `ssh_hostname`
and `ssh_user` are additionally validated at the schema layer to exclude shell
metacharacters.

## Destructive operations

`zfs receive -F` discards snapshots on the target taken since the incremental
base. The planner requests it only when the target has genuinely diverged, and
says so: the instruction carries `requires_rollback: true` and the client logs
it before running. If your targets hold snapshots that are not reproducible
from the hub, review those instructions before enabling automatic execution.
