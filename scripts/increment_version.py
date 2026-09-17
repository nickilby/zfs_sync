#!/usr/bin/env python3
"""Release-time version bump for ZFS Sync.

There is exactly one source of truth for the version: ``__version__`` in
``zfs_sync/__init__.py``. ``pyproject.toml`` reads it via setuptools' dynamic
version, and ``Settings.app_version`` defaults to it, so nothing else needs to
be kept in step.

This used to run from the pre-commit hook and rewrite the version in four
tracked files on *every* commit. That meant two branches committing in parallel
always diverged in those four files, so every merge between them conflicted
there -- which is how unresolved conflict markers ended up committed to main.
Run this deliberately when cutting a release instead::

    python scripts/increment_version.py            # 0.2.7 -> 0.2.8
    python scripts/increment_version.py --minor    # 0.2.7 -> 0.3.0
    python scripts/increment_version.py --major    # 0.2.7 -> 1.0.0
    python scripts/increment_version.py --set 1.2.3
"""

import argparse
import re
import sys
from pathlib import Path

INIT_FILE = Path("zfs_sync/__init__.py")
VERSION_PATTERN = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def read_version() -> str:
    """Return the current version from the single source of truth."""
    if not INIT_FILE.exists():
        raise SystemExit(f"{INIT_FILE} not found -- run this from the repository root.")

    matches = VERSION_PATTERN.findall(INIT_FILE.read_text(encoding="utf-8"))
    if not matches:
        raise SystemExit(f"No __version__ assignment found in {INIT_FILE}.")
    if len(matches) > 1:
        raise SystemExit(
            f"{INIT_FILE} defines __version__ {len(matches)} times ({', '.join(matches)}). "
            "Resolve that before bumping."
        )
    return matches[0]


def bump(version: str, part: str) -> str:
    """Return ``version`` with the requested part incremented."""
    major, minor, patch = (int(piece) for piece in version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def write_version(new_version: str) -> None:
    """Replace the version in the single source of truth."""
    content = INIT_FILE.read_text(encoding="utf-8")
    updated = VERSION_PATTERN.sub(f'__version__ = "{new_version}"', content, count=1)
    INIT_FILE.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--major", action="store_true", help="Bump the major version")
    group.add_argument("--minor", action="store_true", help="Bump the minor version")
    group.add_argument("--set", dest="explicit", metavar="X.Y.Z", help="Set an exact version")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report the new version without writing it"
    )
    args = parser.parse_args()

    current = read_version()

    if args.explicit:
        if not SEMVER_PATTERN.match(args.explicit):
            raise SystemExit(f"'{args.explicit}' is not a valid X.Y.Z version.")
        new_version = args.explicit
    else:
        part = "major" if args.major else "minor" if args.minor else "patch"
        new_version = bump(current, part)

    if args.dry_run:
        print(f"{current} -> {new_version} (dry run, nothing written)")
        return 0

    write_version(new_version)
    print(f"{current} -> {new_version}")
    print(f"Updated {INIT_FILE}. pyproject.toml and Settings read from it.")
    print(f"Next: git commit -am 'chore: release v{new_version}' && git tag v{new_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
