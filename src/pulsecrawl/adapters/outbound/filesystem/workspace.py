"""Workspace metadata migration and human-readable operational snapshots."""

import json
from pathlib import Path
from typing import Any
from pulsecrawl.domain.errors import WorkspaceError
from pulsecrawl.domain.workspace.definitions import _identifier, _safe_identifier
from pulsecrawl.adapters.outbound.filesystem.atomic import _atomic_json

WORKSPACE_VERSION = 2


def _load_workspace_config(path: Path) -> dict[str, Any]:
    """Load and sequentially migrate the small workspace metadata document."""
    value = json.loads(path.read_text(encoding="utf-8"))
    version = value.get("workspaceVersion")
    if isinstance(version, bool) or not isinstance(version, int):
        raise WorkspaceError("workspaceVersion must be an integer")
    if version > WORKSPACE_VERSION:
        raise WorkspaceError(
            f"workspace version {version} is newer than supported version "
            f"{WORKSPACE_VERSION}"
        )
    original = dict(value)
    while version < WORKSPACE_VERSION:
        next_version = version + 1
        if (version, next_version) == (1, 2):
            value.setdefault("workspaceId", _identifier("ws"))
            value["workspaceVersion"] = 2
        else:  # pragma: no cover - every released step must be explicit
            raise WorkspaceError(
                f"no workspace migration from version {version} to {next_version}"
            )
        version = next_version
    if value != original:
        backup = path.with_name(
            f"{path.name}.pre-migration-v{original['workspaceVersion']}"
            f"-to-v{WORKSPACE_VERSION}.backup"
        )
        if not backup.exists():
            _atomic_json(backup, original)
        try:
            _atomic_json(path, value)
        except BaseException:
            _atomic_json(path, original)
            raise
    return value


class JsonDefinitionSnapshots:
    def __init__(self, root):
        self.root = root

    def _path(self, kind, identifier):
        if kind not in ("jobs", "datasets", "executions", "schedules"):
            raise ValueError("unsupported snapshot kind")
        _safe_identifier(identifier)
        if kind == "datasets":
            return self.root / kind / identifier / "dataset.json"
        if kind == "executions":
            return self.root / kind / identifier / "execution.json"
        return self.root / kind / f"{identifier}.json"

    def write(self, kind, identifier, value):
        _atomic_json(self._path(kind, identifier), value)

    def read(self, kind, identifier):
        return json.loads(self._path(kind, identifier).read_text(encoding="utf-8"))
