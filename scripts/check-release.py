#!/usr/bin/env python3
"""Fail when an OSS release tag, metadata, or legal files are inconsistent."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import tomllib

VERSION = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
EXPECTED_LICENSE = "AGPL-3.0-only"


def version(path: Path) -> str:
    match = VERSION.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"could not find __version__ in {path}")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tag",
        help="optional release tag, for example v0.1.0; omit for an unpublished candidate",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    package = (
        root / "."
        if (root / "./pyproject.toml").is_file()
        else root
    )
    license_path = root / "LICENSE"
    if not license_path.is_file() or len(license_path.read_text(encoding="utf-8").strip()) < 100:
        raise SystemExit("a non-placeholder root LICENSE is required")
    package_license = package / "LICENSE"
    if not package_license.is_file() or package_license.read_bytes() != license_path.read_bytes():
        raise SystemExit(f"{package_license} must exactly match the root LICENSE")
    metadata = tomllib.loads(
        (package / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    if metadata.get("name") != "pulsecrawl":
        raise SystemExit("the public distribution must be named 'pulsecrawl'")
    if metadata.get("license") != EXPECTED_LICENSE:
        raise SystemExit(
            f"pyproject.toml must declare license={EXPECTED_LICENSE!r}"
        )
    if metadata.get("license-files") != ["LICENSE"]:
        raise SystemExit("pyproject.toml must package LICENSE")

    package_version = version(package / "src/pulsecrawl/__init__.py")
    tag = args.tag.removeprefix("v") if args.tag else package_version
    if not re.fullmatch(
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", tag
    ):
        raise SystemExit(f"release version is not stable SemVer: {args.tag or tag}")
    if package_version != tag:
        raise SystemExit(f"version mismatch: tag={tag}, package={package_version}")

    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    if f'version: "{tag}"' not in citation:
        raise SystemExit("CITATION.cff version does not match the release tag")
    state = "tag" if args.tag else "unpublished candidate"
    print(f"Release metadata is consistent for v{tag} ({state})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
