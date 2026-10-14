#!/usr/bin/env python3
"""Validate the actual PyPI archives, not just the source configuration."""

from __future__ import annotations

import argparse
import getpass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_names(names):
    for name in names:
        path = PurePosixPath(name)
        require(
            not path.is_absolute() and ".." not in path.parts,
            f"unsafe archive path: {name}",
        )
        require(
            not any(
                part in {".git", ".venv", "__pycache__", "config", "infra", "research"}
                for part in path.parts
            ),
            f"private/generated archive path: {name}",
        )
        require(
            not name.endswith((".pyc", ".pyo", ".env")),
            f"generated/secret archive path: {name}",
        )


def private_identities(extra=()):
    # Never store a contributor's identity in the public repository to ban it.
    # Local builds automatically check the builder's login; CI can receive
    # additional private values through arguments without committing them.
    login = getpass.getuser()
    return tuple(value.casefold().encode() for value in (*extra, login)
                 if len(value) >= 4 and value not in {"root", "runner"})


def check_privacy(body: bytes, location: str, identities):
    lowered = body.lower()
    require(not any(value in lowered for value in identities),
            f"private identity found in {location}")
    require(not re.search(rb"/(?:Users)/[^/\s]+/", body),
            f"personal filesystem path found in {location}")


def check(directory: Path, source: Path, *, identities=()) -> str:
    identities = private_identities(identities)
    package = source / "."
    if not (package / "pyproject.toml").is_file():
        package = source
    match = re.search(
        r'^__version__\s*=\s*"([^"]+)"',
        (package / "src/pulsecrawl/__init__.py").read_text(),
        re.MULTILINE,
    )
    require(match is not None, "missing source version")
    version = match.group(1)
    wheels, sdists = list(directory.glob("*.whl")), list(directory.glob("*.tar.gz"))
    require(
        len(wheels) == len(sdists) == 1,
        "expected exactly one wheel and one sdist; use a fresh output directory",
    )
    require(
        {file.name for file in directory.iterdir()} == {wheels[0].name, sdists[0].name},
        "distribution directory contains unexpected files",
    )
    require(
        wheels[0].name == f"pulsecrawl-{version}-py3-none-any.whl",
        "wheel identity/tag does not match source",
    )
    require(
        sdists[0].name == f"pulsecrawl-{version}.tar.gz",
        "sdist identity does not match source",
    )
    modules = {
        file.relative_to(package / "src").as_posix()
        for file in (package / "src/pulsecrawl").rglob("*.py")
    }
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        safe_names(names)
        for entry in wheel.infolist():
            check_privacy(entry.filename.encode(), "wheel filename", identities)
            check_privacy(entry.comment + entry.extra, "wheel entry metadata", identities)
            check_privacy(wheel.read(entry), entry.filename, identities)
        check_privacy(wheel.comment, "wheel comment", identities)
        info = f"pulsecrawl-{version}.dist-info"
        require(
            all(name.startswith(("pulsecrawl/", info + "/")) for name in names),
            "wheel contains an unexpected import namespace",
        )
        require(
            modules
            == {
                name
                for name in names
                if name.startswith("pulsecrawl/") and name.endswith(".py")
            },
            "wheel omits or adds package modules",
        )
        require(
            wheel.read(f"{info}/licenses/LICENSE") == (source / "LICENSE").read_bytes(),
            "wheel license mismatch",
        )
        metadata = BytesParser().parsebytes(wheel.read(f"{info}/METADATA"))
        require(metadata.get_all("Author") == ["PulseCrawl contributors"],
                "wheel author must be project-neutral")
        require(not any(metadata.get_all(key) for key in
                        ("Author-email", "Maintainer", "Maintainer-email")),
                "wheel must not contain personal maintainer metadata")
        for key, expected in {
            "Name": "pulsecrawl",
            "Version": version,
            "Requires-Python": ">=3.11",
            "License-Expression": "AGPL-3.0-only",
            "Description-Content-Type": "text/markdown",
        }.items():
            require(metadata[key] == expected, f"invalid wheel metadata: {key}")
        require(
            set(metadata.get_all("Provides-Extra", []))
            == {"sql", "workspace", "cloud", "dev"},
            "missing or unexpected extras",
        )
        require(
            metadata.get_payload().strip()
            == (package / "PYPI_README.md").read_text().strip(),
            "PyPI description mismatch",
        )
        require(
            "pulsecrawl = pulsecrawl.cli:main"
            in wheel.read(f"{info}/entry_points.txt").decode(),
            "missing CLI entry point",
        )
    with tarfile.open(sdists[0], "r:gz") as archive:
        members = archive.getmembers()
        safe_names(member.name for member in members)
        require(
            all(member.isfile() or member.isdir() for member in members),
            "sdist contains links or special files",
        )
        require(not archive.pax_headers, "sdist has unexpected global PAX metadata")
        for member in members:
            require((member.uid, member.gid, member.uname, member.gname) == (0, 0, "", ""),
                    "sdist ownership metadata must be neutral")
            require(not member.pax_headers, "sdist has unexpected PAX metadata")
            check_privacy(member.name.encode(), "sdist filename", identities)
            if member.isfile():
                check_privacy(archive.extractfile(member).read(), member.name, identities)
        prefix = f"pulsecrawl-{version}/"
        require(
            all(
                member.name == prefix.rstrip("/") or member.name.startswith(prefix)
                for member in members
            ),
            "unexpected sdist root",
        )
        files = {
            member.name.removeprefix(prefix) for member in members if member.isfile()
        }
        required = {
            "pyproject.toml",
            "_build_backend.py",
            "Dockerfile",
            "Dockerfile.dockerignore",
            "requirements-workspace.txt",
            "LICENSE",
            "README.md",
            "PYPI_README.md",
            "CHANGELOG.md",
            "CITATION.cff",
            "docs/PyPI.md",
            "scripts/check-distributions.py",
            "scripts/smoke-distribution.py",
            "tests/test_example_workflows.py",
            "examples/local_quickstart.py",
            "examples/workspace_quickstart.py",
            "examples/installed_package/crawl_page.py",
            "examples/installed_package/workspace_setup.py",
            "examples/shared/fixtures.py",
            "tools/soak_workspace.py",
        }
        require(
            required <= files,
            f"sdist is missing release/docs/example files: {sorted(required - files)}",
        )
        require(
            {"src/" + module for module in modules} <= files,
            "sdist omits package modules",
        )
        license_file = archive.extractfile(prefix + "LICENSE")
        require(
            license_file.read() == (source / "LICENSE").read_bytes(),
            "sdist license mismatch",
        )
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--private-identity", action="append", default=[],
                        help="additional identity to reject (never stored in the repo)")
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        version = check(args.directory, args.source_root, identities=args.private_identity)
    except (
        ValueError,
        KeyError,
        OSError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        parser.exit(1, f"Distribution validation failed: {error}\n")
    print(
        f"Validated pulsecrawl {version}: wheel, metadata, license, source boundary, and sdist"
    )


if __name__ == "__main__":
    main()
