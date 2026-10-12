"""Local SQLite/filesystem health probes."""

import time
import tempfile
from typing import Any


class WorkspaceHealth:
    def __init__(self, workspace):
        self.workspace = workspace

    def health(self, *, readiness: bool = False) -> dict[str, Any]:
        errors: list[str] = []
        try:
            self.workspace.state.execute("SELECT 1").fetchone()
        except Exception as exc:
            errors.append(f"sqlite: {exc}")
        if readiness:
            try:
                with tempfile.NamedTemporaryFile(dir=self.workspace.path / "cache"):
                    pass
            except OSError as exc:
                errors.append(f"workspace write probe: {exc}")
            try:
                quick_check = self.workspace.state.execute(
                    "PRAGMA quick_check"
                ).fetchone()[0]
                if quick_check != "ok":
                    errors.append(f"sqlite quick check: {quick_check}")
            except Exception as exc:
                errors.append(f"sqlite quick check: {exc}")
            validation = self.workspace.validate()
            errors.extend(f"validation: {item}" for item in validation["errors"])
        active = self.workspace.state.execute(
            "SELECT count(*) AS n FROM execution_leases WHERE lease_until>?",
            (time.time(),),
        ).fetchone()["n"]
        return {
            "healthy": not errors,
            "ready": not errors if readiness else None,
            "errors": errors,
            "workspaceVersion": self.workspace.config["workspaceVersion"],
            "sqliteSchemaVersion": self.workspace.state.schema_version,
            "activeExecutions": int(active),
            "scheduler": self.workspace.schedules.status(),
        }
