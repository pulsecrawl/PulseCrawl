"""Immutable filesystem catalog repositories."""

import json
from pathlib import Path
from typing import Any
from pulsecrawl.domain.workspace.definitions import _safe_identifier
from pulsecrawl.adapters.outbound.filesystem.atomic import _atomic_json


class JsonCatalogRepository:
    directory = ""
    id_key = ""
    prefix = ""

    def __init__(self, root, directory, id_key):
        self.root, self.directory, self.id_key = root, directory, id_key

    def _path(self, identifier: str, *, origin: str = "custom") -> Path:
        _safe_identifier(identifier)
        base = self.root / self.directory
        if self.directory == "templates":
            base /= "system" if origin == "system" else "custom"
        return base / f"{identifier}.json"

    def list(self) -> list[dict[str, Any]]:
        base = self.root / self.directory
        files = (
            base.rglob("*.json")
            if self.directory == "templates"
            else base.glob("*.json")
        )
        return [json.loads(path.read_text()) for path in sorted(files)]

    def get(self, identifier: str) -> dict[str, Any]:
        for item in self.list():
            if item.get(self.id_key) == identifier:
                return item
        raise KeyError(f"unknown {self.directory.rstrip('s')}: {identifier}")

    def save(self, value: dict[str, Any]) -> dict[str, Any]:
        identifier = str(value[self.id_key])
        path = self._path(identifier, origin=str(value.get("origin", "custom")))
        if path.exists() and json.loads(path.read_text()) != value:
            raise ValueError(f"{identifier} already exists with different contents")
        _atomic_json(path, value)
        return value
