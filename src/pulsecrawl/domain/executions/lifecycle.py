"""Execution lifecycle and budget invariants, independent of persistence."""

from dataclasses import dataclass
from pulsecrawl.domain.errors import WorkspaceError

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


@dataclass(frozen=True)
class Execution:
    execution_id: str
    status: str

    def require_runnable(self):
        if self.status not in ("queued", "running"):
            raise WorkspaceError(f"cannot execute a {self.status} execution")

    def require_terminal_transition(self, target: str):
        if target not in TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal execution status: {target}")
        if self.status in TERMINAL_STATUSES and self.status != target:
            raise WorkspaceError(f"cannot change a {self.status} execution to {target}")


@dataclass(frozen=True)
class BudgetReservation:
    urls: int

    @classmethod
    def allocate(cls, requested: int, total: int, used: int, reserved: int):
        amount = min(requested, total - used - reserved)
        if amount <= 0:
            raise WorkspaceError("job has reached maxUrlsTotal")
        return cls(amount)


def freeze_intent(
    job,
    remaining,
    *,
    max_urls_per_execution=None,
    max_depth=None,
    store_raw_pages=None,
    publish_records=True,
):
    configured_urls = int(job["scope"]["maxUrlsPerExecution"])
    if max_urls_per_execution is not None:
        if max_urls_per_execution <= 0:
            raise ValueError("max_urls_per_execution must be positive")
        configured_urls = min(configured_urls, int(max_urls_per_execution))
    configured_depth = int(job["scope"]["maxDepth"])
    if max_depth is not None:
        if max_depth < 0:
            raise ValueError("max_depth must not be negative")
        configured_depth = min(configured_depth, int(max_depth))
    reservation = BudgetReservation.allocate(configured_urls, remaining, 0, 0).urls
    return {
        "seeds": job["seeds"],
        "datasetId": job["datasetId"],
        "templateStack": job["templates"],
        "systemTemplates": job["systemTemplates"],
        "schema": job["schema"],
        "scope": {
            **job["scope"],
            "maxDepth": configured_depth,
            "maxUrlsPerExecution": reservation,
        },
        "politeness": job["politeness"],
        "storeRawPages": job["storeRawPages"]
        if store_raw_pages is None
        else bool(store_raw_pages),
        "publishRecords": bool(publish_records),
    }, reservation
