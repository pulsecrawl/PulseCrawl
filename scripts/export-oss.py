#!/usr/bin/env python3
"""Export the intentionally public PulseCrawl source boundary.

Only allowlisted tracked or non-ignored files are copied. Live cloud config,
hosted implementations, infrastructure, console code, and research records are
excluded by construction.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

ROOT_FILES = {
    ".gitignore",
    "CITATION.cff",
    "CODE_OF_CONDUCT.md",
    "DCO.md",
    "GOVERNANCE.md",
    "MAINTAINERS.md",
    "SECURITY.md",
    "SUPPORT.md",
    "docker-compose.local.yml",
}
OPTIONAL_ROOT_FILES = {"LICENSE", "NOTICE"}
ROOT_ALTERNATIVES = {
    "README.md": (
        "src/packages/pulsecrawl/README.md",
        "oss/README.md",
        "README.md",
    ),
    "CHANGELOG.md": ("oss/CHANGELOG.md", "CHANGELOG.md"),
    "CONTRIBUTING.md": ("oss/CONTRIBUTING.md", "CONTRIBUTING.md"),
}
EXACT_FILES = {
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/oss-ci.yml",
    ".github/workflows/oss-release.yml",
    "docs/AgentTemplateAuthoring.md",
    "docs/PackageArchitecture.md",
    "docs/PyPI.md",
    "docs/ResponsibleCrawling.md",
    "docs/ThreatModel.md",
    "scripts/check-doc-links.py",
    "scripts/check-secrets.py",
    "scripts/check-release.py",
    "scripts/check-distributions.py",
    "scripts/check-release-ci.py",
    "scripts/smoke-distribution.py",
    "scripts/export-oss.py",
}
PRIVATE_PACKAGE_PREFIX = "src/packages/pulsecrawl/"
PUBLIC_PACKAGE_PREFIXES = ("src/pulsecrawl/", "tests/", "examples/", "tools/")
PUBLIC_PACKAGE_FILES = {
    "_build_backend.py",
    "Dockerfile",
    "Dockerfile.dockerignore",
    "MANIFEST.in",
    "pyproject.toml",
    "PYPI_README.md",
    "requirements-workspace.txt",
}
PACKAGE_ROOT_COLLISIONS = {".gitignore", "LICENSE", "README.md"}
PACKAGE_EXCLUDED_PARTS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
PACKAGE_EXCLUDED_PATHS = {
    "examples/jobsearch/research.md",
    "examples/marketplace/clothes/research.md",
    "examples/marketplace/mro/research.md",
    "examples/marketplace/other_industries/research.md",
    "examples/marketplace/supermarkets/research.md",
    "examples/news/chihuahua/research.md",
    "examples/news/mexico/research.md",
    "examples/news/stocks/research.md",
}
FORBIDDEN_TEXT = {
    "development control-plane endpoint": re.compile(
        r"us-central1-pulsecrawl-ctrl-dev\.cloudfunctions\.net"
    ),
    "live environment identifier": re.compile(
        r"(?:billingAccountId|azureWorkerClientId|pulsecrawl-infra-(?:dev|test|prod))"
    ),
    "private infrastructure path": re.compile(r"(?:^|/)config/environments\.json"),
}
SECRET_RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "pulsecrawl-live-key": re.compile(r"\bpk_live_[A-Za-z0-9]{32,}\b"),
    "github-token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{32,}\b"),
    "azure-account-key": re.compile(r"\bAccountKey=[A-Za-z0-9+/]{32,}={0,2}\b"),
    "google-service-account-key": re.compile(r'"private_key"\s*:\s*"-----BEGIN'),
}


def command(root: Path, *args: str) -> str:
    return subprocess.check_output(args, cwd=root, text=True).strip()


def package_relative(path: str, private_layout: bool) -> str | None:
    if private_layout:
        if not path.startswith(PRIVATE_PACKAGE_PREFIX):
            return None
        return path.removeprefix(PRIVATE_PACKAGE_PREFIX)
    if path in PUBLIC_PACKAGE_FILES or path.startswith(PUBLIC_PACKAGE_PREFIXES):
        return path
    return None


def generated_package_path(path: str, private_layout: bool) -> bool:
    relative = package_relative(path, private_layout)
    if relative is None:
        return False
    if relative in PACKAGE_EXCLUDED_PATHS:
        return True
    parts = Path(relative).parts
    return any(
        part in PACKAGE_EXCLUDED_PARTS
        or part.endswith(".egg-info")
        or part.startswith(".coverage")
        for part in parts
    )


def selected(path: str, root_sources: set[str], private_layout: bool) -> bool:
    relative = package_relative(path, private_layout)
    package_file = relative is not None
    if (
        private_layout
        and relative in PACKAGE_ROOT_COLLISIONS
        and path not in root_sources
    ):
        package_file = False
    return (
        not generated_package_path(path, private_layout)
        and (
            path in ROOT_FILES
            or path in OPTIONAL_ROOT_FILES
            or path in EXACT_FILES
            or path in root_sources
            or package_file
        )
    )


def export_destination(
    path: str,
    resolved_roots: dict[str, str],
    private_layout: bool,
) -> str:
    if path in resolved_roots:
        return resolved_roots[path]
    if private_layout and path.startswith(PRIVATE_PACKAGE_PREFIX):
        return path.removeprefix(PRIVATE_PACKAGE_PREFIX)
    return path


def normalize_public_paths(path: Path, relative: str) -> None:
    """Make exported docs and automation work from the public package root."""
    if relative == "scripts/export-oss.py":
        return
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    content = content.replace("./src/packages/pulsecrawl", ".")
    content = content.replace("/src/packages/pulsecrawl", "/")
    content = content.replace("src/packages/pulsecrawl", ".")
    content = content.replace("../../../docs/", "docs/")
    path.write_text(content, encoding="utf-8")


def tracked_and_new(root: Path) -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
    )
    return sorted(item.decode() for item in output.split(b"\0") if item)


def scan_text(path: Path, relative: str) -> list[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    findings: list[str] = []
    rules = SECRET_RULES if relative == "scripts/export-oss.py" else {
        **FORBIDDEN_TEXT,
        **SECRET_RULES,
    }
    for name, pattern in rules.items():
        if pattern.search(content):
            findings.append(f"{name}: {relative}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    root = Path(command(Path.cwd(), "git", "rev-parse", "--show-toplevel"))
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {output}")
    if root == output or root in output.parents:
        raise SystemExit("output must be outside the source repository")
    if not args.allow_dirty and command(root, "git", "status", "--porcelain"):
        raise SystemExit("refusing to export a dirty worktree")
    if not (root / "LICENSE").is_file():
        raise SystemExit("LICENSE is required for a public OSS export")

    available = tracked_and_new(root)
    available_set = set(available)
    private_layout = f"{PRIVATE_PACKAGE_PREFIX}pyproject.toml" in available_set
    if not private_layout and "pyproject.toml" not in available_set:
        raise SystemExit("could not locate the PulseCrawl package")
    resolved_roots: dict[str, str] = {}
    for destination, candidates in ROOT_ALTERNATIVES.items():
        source = next((item for item in candidates if item in available_set), None)
        if source is None:
            raise SystemExit(
                f"missing required public file for {destination}: "
                + " or ".join(candidates)
            )
        resolved_roots[source] = destination
    chosen = [
        path
        for path in available
        if selected(path, set(resolved_roots), private_layout)
    ]
    required = ROOT_FILES | EXACT_FILES | set(resolved_roots)
    package_project = (
        f"{PRIVATE_PACKAGE_PREFIX}pyproject.toml" if private_layout else "pyproject.toml"
    )
    required.add(package_project)
    missing = sorted(path for path in required if path not in chosen)
    if missing:
        raise SystemExit("missing required public files: " + ", ".join(missing))

    findings: list[str] = []
    for relative in chosen:
        source = root / relative
        destination = output / export_destination(
            relative, resolved_roots, private_layout
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        normalize_public_paths(destination, relative)
        findings.extend(scan_text(destination, str(destination.relative_to(output))))
    if findings:
        shutil.rmtree(output)
        raise SystemExit("public-boundary scan failed:\n- " + "\n- ".join(findings))

    checksums: list[str] = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksums.append(f"{digest}  {path.relative_to(output).as_posix()}")
    (output / "PUBLIC_MANIFEST.sha256").write_text(
        "\n".join(checksums) + "\n", encoding="utf-8"
    )
    print(f"Exported {len(chosen)} files to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
