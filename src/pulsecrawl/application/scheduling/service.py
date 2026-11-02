"""Schedule registration, due dispatch and recovery through explicit ports."""

from __future__ import annotations
import logging
from datetime import datetime, timedelta
import math
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

    def set(
        self,
        job_id,
        cron,
        *,
        timezone_name="UTC",
        max_duration_seconds=None,
        misfire_policy="skip",
    ):
        self._jobs.get(job_id)
        if max_duration_seconds is not None and (
            isinstance(max_duration_seconds, bool)
            or not isinstance(max_duration_seconds, (int, float))
            or not math.isfinite(max_duration_seconds)
            or max_duration_seconds <= 0
        ):
            raise ValueError("max_duration_seconds must be finite and positive")
        if misfire_policy != "skip":
            raise ValueError("misfire_policy must be 'skip'")
        normalized, zone = self._calculator.validate(cron, timezone_name)
        next_run = self._calculator.next(normalized, zone, self._clock.now())
        self._repository.set(
            job_id,
            normalized,
            timezone_name,
            next_run,
            max_duration_seconds=(
                float(max_duration_seconds)
                if max_duration_seconds is not None
                else None
            ),
            misfire_policy=misfire_policy,
        )
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
                normalized, zone = self._calculator.validate(
                    schedule["cron"], schedule["timezone"]
                )
                scheduled_time = datetime.fromisoformat(
                    scheduled_for.replace("Z", "+00:00")
                )
                following = self._calculator.next(normalized, zone, scheduled_time)
                following_time = datetime.fromisoformat(
                    following.replace("Z", "+00:00")
                )
                interval_seconds = (following_time - scheduled_time).total_seconds()
                closing_buffer = max(30.0, min(120.0, interval_seconds * 0.10))
                maximum_window = max(interval_seconds - closing_buffer, 1.0)
                configured_window = schedule.get("max_duration_seconds")
                execution_window = min(
                    float(configured_window)
                    if configured_window is not None
                    else maximum_window,
                    maximum_window,
                )
                active = self._repository.has_other_execution(
                    schedule["job_id"], _execution_id(schedule["job_id"], scheduled_for)
                )
                deadline = scheduled_time + timedelta(seconds=execution_window)
                missed_current = active or deadline <= now
                if not missed_current:
                    results.append(
                        self._jobs.run(
                            schedule["job_id"],
                            trigger="schedule",
                            scheduled_for=scheduled_for,
                            fetcher=fetcher,
                            execution_id=_execution_id(
                                schedule["job_id"], scheduled_for
                            ),
                            max_duration_seconds=execution_window,
                            should_stop=should_stop,
                        )
                    )
                next_run, skipped, last_missed = self._next_future(
                    normalized, zone, following, self._clock.now()
                )
                if missed_current:
                    skipped += 1
                    last_missed = scheduled_for
                self._repository.complete(
                    schedule,
                    next_run,
                    missed_runs=skipped,
                    last_missed_at=last_missed,
                )
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
                normalized, zone = self._calculator.validate(
                    schedule["cron"], schedule["timezone"]
                )
                following = self._calculator.next(
                    normalized,
                    zone,
                    datetime.fromisoformat(scheduled_for.replace("Z", "+00:00")),
                )
                next_run, skipped, last_missed = self._next_future(
                    normalized, zone, following, self._clock.now()
                )
                self._repository.complete(
                    schedule,
                    next_run,
                    f"{type(exc).__name__}: {exc}"[:1000],
                    missed_runs=skipped,
                    last_missed_at=last_missed,
                )
                continue
            except BaseException:
                self._repository.release(schedule)
                raise
        return results

    def _next_future(self, cron, zone, candidate, now):
        """Coalesce elapsed occurrences instead of launching catch-up bursts."""
        skipped = 0
        last_missed = None
        value = candidate
        while datetime.fromisoformat(value.replace("Z", "+00:00")) <= now:
            skipped += 1
            last_missed = value
            value = self._calculator.next(
                cron,
                zone,
                datetime.fromisoformat(value.replace("Z", "+00:00")),
            )
        return value, skipped, last_missed

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
