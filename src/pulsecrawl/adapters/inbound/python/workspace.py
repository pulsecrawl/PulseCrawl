"""Stable synchronous workspace facade; construction lives in bootstrap."""

from __future__ import annotations
from pathlib import Path
from pulsecrawl.adapters.outbound.filesystem.atomic import _atomic_json
from pulsecrawl.adapters.outbound.filesystem.workspace import WORKSPACE_VERSION
from pulsecrawl.adapters.outbound.sqlite.clock import utc_now
from pulsecrawl.domain.workspace.definitions import _identifier
from pulsecrawl.adapters.inbound.python.resources import (
    WorkspaceExecutions,
    WorkspaceJobs,
)

__all__ = ["Workspace", "WorkspaceExecutions", "WorkspaceJobs", "WORKSPACE_VERSION"]


class Workspace:
    """A self-contained local PulseCrawl installation rooted at one directory."""

    def __init__(self, path: str | Path) -> None:
        from pulsecrawl.bootstrap.workspace import configure_workspace

        configure_workspace(self, path)

    @classmethod
    def init(cls, path: str | Path, *, name: str | None = None) -> "Workspace":
        root = Path(path).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        for directory in (
            "fields",
            "schemas",
            "templates/system",
            "templates/custom",
            "template-drafts",
            "jobs",
            "schedules",
            "executions",
            "datasets",
            "state",
            "cache",
            ".maintenance",
        ):
            (root / directory).mkdir(parents=True, exist_ok=True)
        config = root / "pulsecrawl.json"
        if not config.exists():
            _atomic_json(
                config,
                {
                    "workspaceVersion": WORKSPACE_VERSION,
                    "workspaceId": _identifier("ws"),
                    "name": name or root.name,
                    "orgId": "local",
                    "createdAt": utc_now(),
                },
            )
        return cls(root)

    def close(self) -> None:
        self.state.close()

    def __enter__(self) -> "Workspace":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def validate(self):
        return self._validation.validate()

    def health(self, *, readiness=False):
        return self._health.health(readiness=readiness)
