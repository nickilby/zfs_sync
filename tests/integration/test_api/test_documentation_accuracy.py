"""Documentation must describe endpoints that exist.

Six documents and two shell scripts referenced `include_commands=true`, a query
parameter no endpoint has ever accepted, and four referenced
`POST /systems/register`, a route that does not exist. FastAPI ignores an
unknown query parameter silently, so nothing ever surfaced the drift.

This checks the claim automatically, so documentation rots loudly rather than
quietly.
"""

import re
import subprocess
from pathlib import Path

import pytest

from zfs_sync.api.app import app

ROOT = Path(__file__).resolve().parents[3]

#: Documents that deliberately describe history or proposals rather than the
#: current API, and are annotated as such.
EXCLUDED = {
    "docs/plans/",  # planning artefacts
    "docs/IMPROVEMENTS_ROADMAP.md",  # proposes future endpoints
    "PROJECT_SETUP_GUIDE.md",  # generic material, not about this service
    "GITHUB_ACTIONS_GUIDE.md",
    "GITHUB_ACTIONS_PROMPTS.md",
}


def tracked_markdown():
    listing = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [
        name
        for name in listing
        if not any(name.startswith(prefix) or name == prefix for prefix in EXCLUDED)
    ]


def normalise(path: str) -> str:
    """Reduce a path to its shape, so {id} and $VAR compare equal."""
    path = re.sub(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", "{}", path)
    path = re.sub(r"\{[^}]*\}", "{}", path)
    return path.rstrip("/")


@pytest.fixture(scope="module")
def known_paths():
    return {normalise(path) for path in app.openapi()["paths"]}


class TestDocumentedEndpointsExist:
    def test_every_documented_api_path_is_real(self, known_paths):
        problems = {}
        for name in tracked_markdown():
            text = (ROOT / name).read_text(encoding="utf-8")
            for raw in set(re.findall(r"/api/v1/[A-Za-z0-9/_{}$<>-]*", text)):
                candidate = normalise(raw)
                if candidate and candidate not in known_paths:
                    problems.setdefault(name, set()).add(raw)

        assert not problems, "documentation references endpoints that do not exist: " + "; ".join(
            f"{name}: {sorted(paths)}" for name, paths in sorted(problems.items())
        )

    def test_no_document_references_the_phantom_parameter(self):
        offenders = [
            name
            for name in tracked_markdown()
            if "include_commands" in (ROOT / name).read_text(encoding="utf-8")
        ]

        assert not offenders, f"include_commands is not a real parameter: {offenders}"

    def test_no_document_references_the_nonexistent_register_route(self):
        offenders = [
            name
            for name in tracked_markdown()
            if "/systems/register" in (ROOT / name).read_text(encoding="utf-8")
        ]

        assert not offenders, f"the route is POST /systems: {offenders}"


class TestDocumentLinksResolve:
    def test_every_relative_markdown_link_points_at_a_real_file(self):
        problems = {}
        for name in tracked_markdown():
            source = ROOT / name
            text = source.read_text(encoding="utf-8")
            for target in re.findall(r"\]\(([^)#:]+\.md)[^)]*\)", text):
                resolved = (source.parent / target).resolve()
                if not resolved.exists():
                    problems.setdefault(name, set()).add(target)

        assert not problems, "documents link to files that do not exist: " + "; ".join(
            f"{name}: {sorted(links)}" for name, links in sorted(problems.items())
        )


class TestVersionIsStatedOnce:
    def test_the_package_is_the_only_source_of_the_version(self):
        """Three different version stories coexisted: 0.1.80, 0.2.0 and "v2.0".

        The version now lives in one place; pyproject reads it from there.
        """
        try:
            import tomllib  # Python 3.11+
        except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
            import tomli as tomllib

        with open(ROOT / "pyproject.toml", "rb") as handle:
            pyproject = tomllib.load(handle)

        assert "version" in pyproject["project"].get(
            "dynamic", []
        ), "pyproject should derive the version, not restate it"
        assert "version" not in pyproject["project"]
