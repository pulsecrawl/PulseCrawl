"""Fail closed on malformed or incomplete release archives (no uploads)."""

import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tomllib
import zipfile

import pytest

ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "scripts/check-distributions.py").is_file()
)
SPEC = importlib.util.spec_from_file_location(
    "distribution_checks", ROOT / "scripts/check-distributions.py"
)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def test_pypi_metadata_labels_the_repository_explicitly_as_github():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["urls"]["GitHub"] == "https://github.com/pulsecrawl/PulseCrawl"
    assert "Source" not in project["urls"]


def test_pypi_description_promotes_github_before_installation():
    description = (ROOT / "PYPI_README.md").read_text()
    introduction = description.split("## Installation", 1)[0]
    assert "[GitHub repository](https://github.com/pulsecrawl/PulseCrawl)" in introduction
    assert "After a release is published to PyPI" not in description


@pytest.fixture
def candidate(tmp_path):
    source = tmp_path / "source"
    files = {
        "src/pulsecrawl/__init__.py": b'__version__ = "0.1.0"\n',
        "LICENSE": b"test license",
        "PYPI_README.md": b"# Release description\n",
    }
    for name in (
        "pyproject.toml",
        "_build_backend.py",
        "Dockerfile",
        "Dockerfile.dockerignore",
        "requirements-workspace.txt",
        "README.md",
        "CHANGELOG.md",
        "CITATION.cff",
        "docs/PyPI.md",
        "scripts/check-distributions.py",
        "scripts/smoke-distribution.py",
        "tests/test_example_workflows.py",
        "examples/local_quickstart.py",
        "examples/workspace_quickstart.py",
        "examples/shared/fixtures.py",
        "tools/soak_workspace.py",
    ):
        files[name] = b"fixture\n"
    for name, body in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    output = tmp_path / "dist"
    output.mkdir()
    info = "pulsecrawl-0.1.0.dist-info/"
    metadata = (
        "Metadata-Version: 2.4\nName: pulsecrawl\nVersion: 0.1.0\n"
        "Author: PulseCrawl contributors\n"
        "Requires-Python: >=3.11\nLicense-Expression: AGPL-3.0-only\n"
        "Description-Content-Type: text/markdown\n"
        "Provides-Extra: sql\nProvides-Extra: workspace\nProvides-Extra: cloud\nProvides-Extra: dev\n"
        "\n# Release description\n"
    )
    wheel_files = {
        "pulsecrawl/__init__.py": files["src/pulsecrawl/__init__.py"],
        info + "METADATA": metadata.encode(),
        info + "licenses/LICENSE": files["LICENSE"],
        info
        + "entry_points.txt": b"[console_scripts]\npulsecrawl = pulsecrawl.cli:main\n",
    }
    wheel = output / "pulsecrawl-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, body in wheel_files.items():
            archive.writestr(name, body)
    sdist = output / "pulsecrawl-0.1.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        for name, body in files.items():
            member = tarfile.TarInfo("pulsecrawl-0.1.0/" + name)
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
    return source, output, wheel, sdist


def rewrite_wheel(wheel, *, remove=None, add=None, replacement=None):
    with zipfile.ZipFile(wheel) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    if remove:
        entries.pop(remove)
    entries.update(add or {})
    if replacement:
        key, old, new = replacement
        entries[key] = entries[key].replace(old, new)
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)


def test_complete_candidate_and_cli_pass(candidate):
    source, output, _wheel, _sdist = candidate
    assert CHECKER.check(output, source) == "0.1.0"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check-distributions.py"),
            str(output),
            "--source-root",
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Validated pulsecrawl 0.1.0" in result.stdout


@pytest.mark.parametrize(
    "path",
    [
        "../escape.py",
        "/absolute.py",
        "infra/config.json",
        ".venv/token",
        "pulsecrawl/__pycache__/x.pyc",
    ],
)
def test_generated_private_and_traversal_paths_are_rejected(path):
    with pytest.raises(ValueError):
        CHECKER.safe_names([path])


@pytest.mark.parametrize(
    "old,new",
    [
        (b"Version: 0.1.0", b"Version: 9.9.9"),
        (b"AGPL-3.0-only", b"MIT"),
        (b"Provides-Extra: workspace\n", b""),
        (b"# Release description", b"wrong description"),
    ],
)
def test_metadata_mismatches_are_rejected(candidate, old, new):
    source, output, wheel, _sdist = candidate
    rewrite_wheel(wheel, replacement=("pulsecrawl-0.1.0.dist-info/METADATA", old, new))
    with pytest.raises(ValueError):
        CHECKER.check(output, source)


def test_missing_module_is_rejected(candidate):
    source, output, wheel, _sdist = candidate
    rewrite_wheel(wheel, remove="pulsecrawl/__init__.py")
    with pytest.raises(ValueError, match="modules"):
        CHECKER.check(output, source)


def test_unexpected_namespace_is_rejected(candidate):
    source, output, wheel, _sdist = candidate
    rewrite_wheel(wheel, add={"hosted_backend/secret.py": b""})
    with pytest.raises(ValueError, match="namespace"):
        CHECKER.check(output, source)


def test_license_mismatch_is_rejected(candidate):
    source, output, wheel, _sdist = candidate
    rewrite_wheel(
        wheel, add={"pulsecrawl-0.1.0.dist-info/licenses/LICENSE": b"wrong license"}
    )
    with pytest.raises(ValueError, match="license mismatch"):
        CHECKER.check(output, source)


def test_extra_distribution_file_is_rejected(candidate):
    source, output, _wheel, _sdist = candidate
    (output / "stale.whl").write_bytes(b"stale")
    with pytest.raises(ValueError, match="exactly one"):
        CHECKER.check(output, source)


def test_incomplete_source_archive_is_rejected(candidate):
    source, output, _wheel, sdist = candidate
    with tarfile.open(sdist, "w:gz"):
        pass
    with pytest.raises(ValueError, match="missing"):
        CHECKER.check(output, source)


def test_source_archive_link_is_rejected(candidate):
    source, output, _wheel, sdist = candidate
    with tarfile.open(sdist, "w:gz") as archive:
        link = tarfile.TarInfo("pulsecrawl-0.1.0/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    with pytest.raises(ValueError, match="links"):
        CHECKER.check(output, source)


def rewrite_sdist(sdist, transform):
    with tarfile.open(sdist, "r:gz") as archive:
        entries = [(member, archive.extractfile(member).read() if member.isfile() else None)
                   for member in archive]
    with tarfile.open(sdist, "w:gz") as archive:
        for member, body in entries:
            transform(member)
            archive.addfile(member, io.BytesIO(body) if body is not None else None)


@pytest.mark.parametrize("field,value", [
    ("uid", 501), ("gid", 20), ("uname", "personal-login"), ("gname", "staff"),
    ("pax_headers", {"comment": "personal-login"}),
])
def test_personal_archive_headers_are_rejected(candidate, field, value):
    source, output, _wheel, sdist = candidate
    rewrite_sdist(sdist, lambda member: setattr(member, field, value))
    with pytest.raises(ValueError, match="metadata"):
        CHECKER.check(output, source)


def test_private_identity_in_wheel_body_is_rejected(candidate):
    source, output, wheel, _sdist = candidate
    rewrite_wheel(wheel, add={"pulsecrawl/private.txt": b"Personal-Login"})
    with pytest.raises(ValueError, match="private identity"):
        CHECKER.check(output, source, identities=["personal-login"])


def test_personal_author_is_rejected(candidate):
    source, output, wheel, _sdist = candidate
    rewrite_wheel(wheel, replacement=("pulsecrawl-0.1.0.dist-info/METADATA",
                                    b"PulseCrawl contributors", b"Personal Author"))
    with pytest.raises(ValueError, match="project-neutral"):
        CHECKER.check(output, source)


def test_backend_neutralizes_all_sdist_headers(candidate, monkeypatch):
    _source, _output, _wheel, sdist = candidate
    spec = importlib.util.spec_from_file_location("release_backend", ROOT / "_build_backend.py")
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
    rewrite_sdist(sdist, lambda member: (
        setattr(member, "uid", 501), setattr(member, "gid", 20),
        setattr(member, "uname", "personal-login"), setattr(member, "gname", "staff"),
        setattr(member, "pax_headers", {"comment": "personal-login"}),
    ))
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1234567890")
    backend._neutralize_sdist(sdist)
    with tarfile.open(sdist) as archive:
        assert not archive.pax_headers
        for member in archive:
            assert (member.uid, member.gid, member.uname, member.gname) == (0, 0, "", "")
            assert member.mtime == 1234567890
            assert not member.pax_headers
    first = sdist.read_bytes()
    backend._neutralize_sdist(sdist)
    assert sdist.read_bytes() == first
