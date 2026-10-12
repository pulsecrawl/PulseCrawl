"""Explicit OSS workspace connections to PulseCrawl Cloud.

Profiles never contain API-key material. Secrets live in the operating-system
keyring or in ``PULSECRAWL_API_KEY`` for ephemeral CI environments.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from pulsecrawl.adapters.outbound.http.client import API_KEY_ENV, PulseCrawl


CONFIG_HOME_ENV = "PULSECRAWL_CONFIG_HOME"
PROFILE_SERVICE = "pulsecrawl-cloud"
BUNDLE_VERSION = 1


from pulsecrawl.domain.synchronization.profiles import CloudProfile
from pulsecrawl.application.synchronization.profiles import ProfileService
from pulsecrawl.application.synchronization.service import WorkspaceSyncService
from pulsecrawl.adapters.outbound.credentials.profiles import (
    JsonProfileRepository,
    KeyringCredentialStore,
)
from pulsecrawl.adapters.outbound.http.workspace import HttpWorkspaceGateway

__all__ = [
    "CloudProfile",
    "CloudProfiles",
    "CloudWorkspaceSync",
    "export_workspace_bundle",
]


def _config_path() -> Path:
    override = os.environ.get(CONFIG_HOME_ENV)
    base = (
        Path(override).expanduser()
        if override
        else Path.home() / ".config" / "pulsecrawl"
    )
    return base / "profiles.json"


def _atomic_private_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _keyring():
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise ImportError(
            "persistent cloud profiles require the keyring extra: "
            "pip install 'pulsecrawl[cloud]'"
        ) from exc
    return keyring


def export_workspace_bundle(workspace) -> dict[str, Any]:
    """Return a portable, credential-free workspace definition bundle."""
    return {
        "bundleVersion": BUNDLE_VERSION,
        "workspace": {
            "workspaceId": workspace.config["workspaceId"],
            "name": workspace.config["name"],
        },
        "fields": workspace.fields.list(),
        "schemas": workspace.schemas.list(),
        "templates": workspace.templates.list(),
        "datasets": workspace.datasets.list(),
        "jobs": workspace.jobs.list(),
        "schedules": workspace.schedules.list(),
    }


class CloudProfiles(ProfileService):
    def __init__(self, path=None):
        self.path = Path(path).expanduser() if path is not None else _config_path()
        super().__init__(
            store=JsonProfileRepository(
                self.path, lambda path, value: _atomic_private_json(path, value)
            ),
            credentials=KeyringCredentialStore(lambda: _keyring()),
            client_factory=lambda **kwargs: PulseCrawl(**kwargs),
            environment_secret=lambda: os.environ.get(API_KEY_ENV),
        )


class CloudWorkspaceSync(WorkspaceSyncService):
    from pulsecrawl.domain.synchronization.planner import (
        WorkspaceSyncPlanner as _Planner,
    )

    _validate_bundle = staticmethod(_Planner._validate_bundle)

    def __init__(self, client):
        self.client = client
        super().__init__(HttpWorkspaceGateway(client))
