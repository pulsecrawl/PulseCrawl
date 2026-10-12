"""Schedule registration, due dispatch and recovery through explicit ports."""

from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Any
from pulsecrawl.domain.scheduling.identity import _execution_id
from pulsecrawl.application.telemetry import event as log_event

LOGGER = logging.getLogger("pulsecrawl.scheduler")


class ScheduleService:
    def __init__(self, *, repository, jobs, executions, snapshots, calculator, clock):
        self._repository, self._jobs, self._executions = repository, jobs, executions
        self._snapshots, self._calculator, self._clock = snapshots, calculator, clock

    def _snapshot(self, job_id):
        value = next(item for item in self.list() if item["jobId"] == job_id)
        self._snapshots.write("schedules", job_id, value)
        return value

    def list(self):
        return self._repository.list()

    def status(self):
        return {**self._repository.status(), "schedules": len(self.list())}

    def set(self, job_id, cron, *, timezone_name="UTC"):
        self._jobs.get(job_id)
        normalized, zone = self._calculator.validate(cron, timezone_name)
        next_run = self._calculator.next(normalized, zone, self._clock.now())
        self._repository.set(job_id, normalized, timezone_name, next_run)
        return self._snapshot(job_id)

    def set_status(self, job_id, status):
        if status not in ("active", "paused"):
            raise ValueError("schedule status must be active or paused")
        row = self._repository.get(job_id)
        next_run = row["next_run_at"]
        if status == "active":
            _, zone = self._calculator.validate(row["cron"], row["timezone"])
            next_run = self._calculator.next(row["cron"], zone, self._clock.now())
        self._repository.set_status(job_id, status, next_run)
        return self._snapshot(job_id)

    def run_due(self, *, fetcher=None, should_stop=None) -> list[dict[str, Any]]:
        now = self._clock.now()
        stale = (now - timedelta(minutes=5)).isoformat()
        claimed: list[dict[str, Any]] = []
        claimed = self._repository.claim_due(now, stale)

        results: list[dict[str, Any]] = []
        for schedule in claimed:
            scheduled_for = schedule["next_run_at"]
            try:
                active = self._repository.has_other_execution(
                    schedule["job_id"], _execution_id(schedule["job_id"], scheduled_for)
                )
                if not active:
                    results.append(
                        self._jobs.run(
                            schedule["job_id"],
                            trigger="schedule",
                            scheduled_for=scheduled_for,
                            fetcher=fetcher,
                            execution_id=_execution_id(
                                schedule["job_id"], scheduled_for
                            ),
                            should_stop=should_stop,
                        )
                    )
                _, zone = self._calculator.validate(
                    schedule["cron"], schedule["timezone"]
                )
                next_run = self._calculator.next(
                    schedule["cron"],
                    zone,
                    datetime.fromisoformat(scheduled_for.replace("Z", "+00:00")),
                )
                self._repository.complete(schedule, next_run)
                self._snapshot(schedule["job_id"])
            except Exception as exc:
                log_event(
                    LOGGER,
                    "scheduled_execution_failed",
                    level=logging.ERROR,
                    job_id=schedule["job_id"],
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                _, zone = self._calculator.validate(
                    schedule["cron"], schedule["timezone"]
                )
                next_run = self._calculator.next(
                    schedule["cron"],
                    zone,
                    datetime.fromisoformat(scheduled_for.replace("Z", "+00:00")),
                )
                self._repository.complete(
                    schedule, next_run, f"{type(exc).__name__}: {exc}"[:1000]
                )
                continue
            except BaseException:
                self._repository.release(schedule)
                raise
        return results

    def recover_incomplete(
        self, *, fetcher=None, should_stop=None
    ) -> list[dict[str, Any]]:
        """Resume queued or expired-running executions after a process restart."""
        self._executions.settle_abandoned_cancellations()
        results: list[dict[str, Any]] = []
        for execution_id in self._executions.recoverable():
            try:
                results.append(
                    self._executions.resume(
                        execution_id, fetcher=fetcher, should_stop=should_stop
                    )
                )
            except RuntimeError as exc:
                # A concurrent process may claim it between discovery and resume.
                if "already has an active runner" not in str(exc):
                    raise
        return results
