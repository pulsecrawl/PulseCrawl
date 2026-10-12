"""Keep the reproducible container lock compatible with package requirements."""

from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def test_workspace_lock_satisfies_declared_runtime_dependencies():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    locked = {}
    for line in (root / "requirements-workspace.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        requirement = Requirement(line)
        pins = list(requirement.specifier)
        assert len(pins) == 1 and pins[0].operator == "==", line
        locked[canonicalize_name(requirement.name)] = pins[0].version
    for declared in (
        project["dependencies"] + project["optional-dependencies"]["workspace"]
    ):
        requirement = Requirement(declared)
        # This lock targets the Linux container, not the test runner's OS.
        if requirement.marker and not requirement.marker.evaluate(
            {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"}
        ):
            continue
        name = canonicalize_name(requirement.name)
        assert name in locked, f"Missing container pin: {name}"
        assert locked[name] in requirement.specifier, (
            f"Container pin {name}=={locked[name]} violates {declared}"
        )
