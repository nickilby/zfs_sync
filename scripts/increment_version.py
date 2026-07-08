#!/usr/bin/env python3
"""
Version increment script for ZFS Sync.

This script increments the patch version (e.g., 0.2.0 → 0.2.1) and updates
all version files in the repository.
"""

import re
import sys
from pathlib import Path


def get_current_version() -> str:
    """Extract current version from zfs_sync/__init__.py or pyproject.toml."""
    # Try __init__.py first
    init_file = Path("zfs_sync/__init__.py")
    if init_file.exists():
        content = init_file.read_text()
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)

    # Fallback to pyproject.toml
    pyproject_file = Path("pyproject.toml")
    if pyproject_file.exists():
        content = pyproject_file.read_text()
        match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)

    raise ValueError("Could not find version in zfs_sync/__init__.py or pyproject.toml")


def increment_patch_version(version: str) -> str:
    """Increment patch version (e.g., 0.2.0 → 0.2.1)."""
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Version must be in format X.Y.Z, got: {version}")

    try:
        major, minor, patch = map(int, parts)
        patch += 1
        return f"{major}.{minor}.{patch}"
    except ValueError as e:
        raise ValueError(f"Invalid version format: {version}") from e


def update_pyproject_toml(new_version: str) -> bool:
    """Update version in pyproject.toml."""
    pyproject_file = Path("pyproject.toml")
    if not pyproject_file.exists():
        return False

    content = pyproject_file.read_text()
    # Match: version = "0.2.0" or version = '0.2.0'
    pattern = r'(version\s*=\s*["\'])([^"\']+)(["\'])'
    replacement = rf"\g<1>{new_version}\g<3>"

    new_content = re.sub(pattern, replacement, content)
    if new_content != content:
        pyproject_file.write_text(new_content)
        return True
    return False


def update_init_py(new_version: str) -> bool:
    """Update version in zfs_sync/__init__.py."""
    init_file = Path("zfs_sync/__init__.py")
    if not init_file.exists():
        return False

    content = init_file.read_text()
    # Match: __version__ = "0.2.0" or __version__ = '0.2.0'
    pattern = r'(__version__\s*=\s*["\'])([^"\']+)(["\'])'
    replacement = rf"\g<1>{new_version}\g<3>"

    new_content = re.sub(pattern, replacement, content)
    if new_content != content:
        init_file.write_text(new_content)
        return True
    return False


def update_yaml_example(new_version: str) -> bool:
    """Update version in config/zfs_sync.yaml.example."""
    yaml_file = Path("config/zfs_sync.yaml.example")
    if not yaml_file.exists():
        return False

    content = yaml_file.read_text()
    # Match: app_version: "0.2.0" or app_version: '0.2.0'
    pattern = r'(app_version:\s*["\'])([^"\']+)(["\'])'
    replacement = rf"\g<1>{new_version}\g<3>"

    new_content = re.sub(pattern, replacement, content)
    if new_content != content:
        yaml_file.write_text(new_content)
        return True
    return False


def main():
    """Main function to increment version and update all files."""
    try:
        # Get current version
        current_version = get_current_version()
        print(f"Current version: {current_version}")

        # Increment patch version
        new_version = increment_patch_version(current_version)
        print(f"New version: {new_version}")

        # Update all version files
        updated_files = []
        if update_pyproject_toml(new_version):
            updated_files.append("pyproject.toml")
        if update_init_py(new_version):
            updated_files.append("zfs_sync/__init__.py")
        if update_yaml_example(new_version):
            updated_files.append("config/zfs_sync.yaml.example")

        if updated_files:
            print(f"Updated version in: {', '.join(updated_files)}")
            # Print new version for use in git hook
            print(f"VERSION={new_version}")
            return 0
        else:
            print("Warning: No version files were updated")
            return 1

    except Exception as e:
        print(f"Error incrementing version: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
