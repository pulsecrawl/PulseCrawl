"""Backup, restore, retention, health, and repair for local workspaces."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class LocalDoctorAdapter:
    def __init__(self, *, root, state, datasets, readers, validate, lock):
        self.root, self.state, self.datasets = root, state, datasets
        self.readers, self.validate, self.lock = readers, validate, lock

    def doctor(self, *, repair_safe: bool = False) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        repaired: list[str] = []
        integrity = self.state.integrity_check()
        if integrity != ["ok"]:
            errors.extend(f"sqlite: {item}" for item in integrity)
        validation = self.validate()
        errors.extend(validation["errors"])
        now = time.time()
        expired_executions = self.state.execute(
            "SELECT execution_id FROM execution_leases WHERE lease_until<=?", (now,)
        ).fetchall()
        expired_maintenance = self.state.execute(
            "SELECT name FROM maintenance_leases WHERE lease_until<=?", (now,)
        ).fetchall()
        if expired_executions:
            warnings.append(f"{len(expired_executions)} expired execution lease(s)")
        if expired_maintenance:
            warnings.append(f"{len(expired_maintenance)} expired maintenance lease(s)")
        temporary = [path for path in self.root.rglob(".*.tmp") if path.is_file()]
        if temporary:
            warnings.append(f"{len(temporary)} abandoned temporary file(s)")
        orphaned: list[Path] = []
        for dataset in self.datasets.list():
            root = self.root / "datasets" / dataset["datasetId"]
            referenced: set[str] = set()
            manifests = self.readers(dataset).manifests
            for manifest_path in manifests.version_paths():
                try:
                    value = json.loads(manifest_path.read_text(encoding="utf-8"))
                    referenced.update(
                        str(item["path"]) for item in value.get("files", [])
                    )
                except Exception as exc:
                    errors.append(
                        f"dataset version manifest {manifest_path.name}: {exc}"
                    )
            orphaned.extend(
                path
                for path in (root / "data").rglob("*")
                if path.is_file()
                and path.relative_to(root).as_posix() not in referenced
            )
        if orphaned:
            warnings.append(f"{len(orphaned)} unreferenced dataset file(s)")
        if repair_safe:
            with self.lock():
                self.state.execute(
                    "DELETE FROM execution_leases WHERE lease_until<=?", (now,)
                )
                self.state.execute(
                    "DELETE FROM maintenance_leases WHERE lease_until<=?", (now,)
                )
                for path in temporary:
                    path.unlink(missing_ok=True)
                # Re-check references under the maintenance lease so a file
                # completed immediately before lock acquisition is preserved.
                safe_orphans: list[Path] = []
                for dataset in self.datasets.list():
                    root = self.root / "datasets" / dataset["datasetId"]
                    referenced: set[str] = set()
                    manifests = self.readers(dataset).manifests
                    for manifest_path in manifests.version_paths():
                        value = json.loads(manifest_path.read_text(encoding="utf-8"))
                        referenced.update(
                            str(item["path"]) for item in value.get("files", [])
                        )
                    safe_orphans.extend(
                        path
                        for path in (root / "data").rglob("*")
                        if path.is_file()
                        and path.relative_to(root).as_posix() not in referenced
                    )
                for path in safe_orphans:
                    path.unlink(missing_ok=True)
                if expired_executions:
                    repaired.append("expired execution leases")
                if expired_maintenance:
                    repaired.append("expired maintenance leases")
                if temporary:
                    repaired.append("abandoned temporary files")
                if safe_orphans:
                    repaired.append("unreferenced dataset files")
        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "repaired": repaired,
            "sqliteSchemaVersion": self.state.schema_version,
        }
