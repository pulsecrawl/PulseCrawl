"""Execution lifecycle orchestration through persistence and runtime ports."""

from __future__ import annotations
import asyncio
import dataclasses
import logging
from typing import Any
from pulsecrawl.application.ports.workspace import (
    ExecutionRepository,
    ExecutionLease,
    ExecutionRuntimeFactory,
    DefinitionSnapshots,
    ExecutionTasks,
)
from pulsecrawl.domain.crawling.model import Completed
from pulsecrawl.domain.executions.lifecycle import Execution
from pulsecrawl.domain.errors import WorkspaceError
from pulsecrawl.application.telemetry import event as log_event

LOGGER = logging.getLogger("pulsecrawl.workspace")


class ExecutionService:
    _LEASE_SECONDS = 60.0
    _HEARTBEAT_SECONDS = 10.0

    def __init__(
        self,
        *,
        repository: ExecutionRepository,
        leases: ExecutionLease,
        runtime: ExecutionRuntimeFactory,
        datasets,
        readers,
        snapshots: DefinitionSnapshots,
        now,
        id_factory,
        tasks: ExecutionTasks,
    ):
        self._repository, self._leases, self._runtime = repository, leases, runtime
        self._datasets, self._readers, self._snapshots = datasets, readers, snapshots
        self._now, self._id = now, id_factory
        self._tasks = tasks

    def list(self, job_id=None):
        return self._repository.list(job_id)

    def get(self, execution_id):
        return self._repository.get(execution_id)

    def _write_snapshot(self, execution_id):
        self._snapshots.write("executions", execution_id, self.get(execution_id))

    def _claim(self, execution_id, owner_token):
        self._leases.claim(execution_id, owner_token, self._LEASE_SECONDS)

    def _heartbeat(self, execution_id, owner_token):
        return self._leases.heartbeat(execution_id, owner_token, self._LEASE_SECONDS)

    def _release(self, execution_id, owner_token):
        self._leases.release(execution_id, owner_token)

    def recoverable(self):
        return self._repository.abandoned("queued") + self._repository.abandoned(
            "running"
        )

    def _cancellation_requested(self, execution_id):
        return self._repository.cancellation_requested(execution_id)

    def cancel(self, execution_id: str, *, force: bool = False) -> dict[str, Any]:
        execution = self.get(execution_id)
        if execution["status"] in ("succeeded", "failed", "cancelled"):
            return execution
        requested_at = self._now()
        mode = "force" if force else "graceful"
        self._repository.request_cancellation(execution_id, requested_at, mode)
        if force:
            self._tasks.cancel(execution_id)
        if not self._leases.active(execution_id):
            self._finish(
                execution_id,
                status="cancelled",
                stats=execution.get("stats"),
                error="execution cancelled",
                finished_at=self._now(),
                discard_staged=force,
            )
        self._write_snapshot(execution_id)
        return self.get(execution_id)

    def settle_abandoned_cancellations(self) -> list[str]:
        abandoned = self._repository.abandoned("cancelling")
        settled: list[str] = []
        for execution_id in abandoned:
            execution = self.get(execution_id)
            self._finish(
                execution_id,
                status="cancelled",
                stats=execution.get("stats"),
                error="execution cancelled",
                finished_at=self._now(),
                # A terminal cancelled execution cannot be resumed.  Any
                # records left by a runner that disappeared before observing
                # the request must not become permanent orphan state.
                discard_staged=True,
            )
            self._write_snapshot(execution_id)
            settled.append(execution_id)
        return settled

    def prepare(self, job_id, **options):
        prepared = self._repository.prepare(job_id, **options)
        self._write_snapshot(prepared["executionId"])
        return prepared

    async def execute(self, execution_id, **options):
        return await self._execute(execution_id, **options)

    async def _execute(
        self,
        execution_id: str,
        *,
        fetcher=None,
        allow_private_networks: bool = False,
        should_stop=None,
    ) -> dict[str, Any]:
        execution = self.get(execution_id)
        if execution["status"] == "succeeded":
            return execution
        if execution["status"] == "cancelling":
            self.settle_abandoned_cancellations()
            return self.get(execution_id)
        Execution(execution_id, execution["status"]).require_runnable()
        owner_token = self._id("runner")
        started = execution["startedAt"] or self._now()
        with self._leases.hold(
            execution_id, owner_token, self._LEASE_SECONDS, self._HEARTBEAT_SECONDS
        ):
            return await self._run_claimed(
                execution,
                started,
                fetcher=fetcher,
                allow_private_networks=allow_private_networks,
                should_stop=should_stop,
            )

    async def _run_claimed(
        self, execution, started, *, fetcher, allow_private_networks, should_stop
    ):
        execution_id = execution["executionId"]
        current_task = asyncio.current_task()
        self._tasks.register(execution_id, current_task)
        try:
            self._repository.start(execution_id, started)
            async with self._runtime.open(
                execution,
                started,
                fetcher=fetcher,
                allow_private_networks=allow_private_networks,
                should_stop=lambda: (
                    self._cancellation_requested(execution_id)
                    or bool(should_stop and should_stop())
                ),
            ) as runtime:
                return await self._run_runtime(execution, runtime, should_stop)
        finally:
            self._tasks.unregister(execution_id, current_task)

    async def _run_runtime(self, execution, runtime, should_stop):
        execution_id = execution["executionId"]
        log_event(
            LOGGER,
            "execution_started",
            execution_id=execution_id,
            job_id=execution["jobId"],
        )
        self._write_snapshot(execution_id)
        intent, writer, engine = runtime.intent, runtime.writer, runtime.engine
        admitted, pending_urls = runtime.admitted, runtime.pending_urls
        try:
            if admitted == 0 and pending_urls.pending_count() == 0:
                await engine.seed(intent)
            outcome = await engine.run(intent)
            if self._cancellation_requested(execution_id):
                cancellation = self.get(execution_id)
                stats = dataclasses.asdict(outcome.stats)
                if cancellation.get("cancellationMode") == "graceful":
                    # Graceful cancellation finishes the current page and
                    # publishes all durable work completed before the stop.
                    item = writer.finalize(completed_at=self._now())
                    stats["materializedRows"] = item["rows"] if item else 0
                else:
                    stats["materializedRows"] = 0
                self._finish(
                    execution_id,
                    status="cancelled",
                    stats=stats,
                    error="execution cancelled",
                    finished_at=self._now(),
                    discard_staged=True,
                )
                self._write_snapshot(execution_id)
                log_event(LOGGER, "execution_cancelled", execution_id=execution_id)
                return self.get(execution_id)
            if should_stop and should_stop():
                raise asyncio.CancelledError
            if not isinstance(outcome, Completed):
                raise RuntimeError("local execution unexpectedly parked")
            item = writer.finalize(completed_at=self._now())
            stats = dataclasses.asdict(outcome.stats)
            stats["materializedRows"] = item["rows"] if item else 0
            finished = self._now()
            # Cancellation can arrive while synchronous Parquet finalization
            # is in progress.  The file is already durable at this point, so
            # report a cancelled execution with its committed partial output
            # instead of silently overwriting the request with "succeeded".
            if self._cancellation_requested(execution_id):
                self._finish(
                    execution_id,
                    status="cancelled",
                    stats=stats,
                    error="execution cancelled after output commit",
                    finished_at=finished,
                    discard_staged=True,
                )
                self._write_snapshot(execution_id)
                log_event(LOGGER, "execution_cancelled", execution_id=execution_id)
                return self.get(execution_id)
            self._finish(
                execution_id,
                status="succeeded",
                stats=stats,
                error=None,
                finished_at=finished,
                discard_staged=True,
            )
            log_event(
                LOGGER,
                "execution_succeeded",
                execution_id=execution_id,
                stats=stats,
            )
        except asyncio.CancelledError:
            if self._cancellation_requested(execution_id):
                current = self.get(execution_id)
                self._finish(
                    execution_id,
                    status="cancelled",
                    stats=current.get("stats"),
                    error="execution cancelled",
                    finished_at=self._now(),
                    discard_staged=True,
                )
                self._write_snapshot(execution_id)
                log_event(LOGGER, "execution_cancelled", execution_id=execution_id)
                return self.get(execution_id)
            # A graceful scheduler/container stop is resumable.  Durable
            # pending_urls, staged rows, lifetime reservation, and running state
            # remain intact; the runner lease is released in ``finally``.
            self._write_snapshot(execution_id)
            raise
        except Exception as exc:
            finished = self._now()
            self._finish(
                execution_id,
                status="failed",
                stats=None,
                error=str(exc),
                finished_at=finished,
                discard_staged=False,
            )
            self._write_snapshot(execution_id)
            log_event(
                LOGGER,
                "execution_failed",
                level=logging.ERROR,
                execution_id=execution_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        self._write_snapshot(execution_id)
        return self.get(execution_id)

    def _finish(self, execution_id, **options):
        self._repository.finish(execution_id, **options)

    async def resume(
        self,
        execution_id: str,
        *,
        fetcher=None,
        allow_private_networks: bool = False,
        should_stop=None,
    ) -> dict[str, Any]:
        execution = self.get(execution_id)
        if execution["status"] not in ("queued", "running"):
            raise WorkspaceError("only queued or running executions can be resumed")
        return await self._execute(
            execution_id,
            fetcher=fetcher,
            allow_private_networks=allow_private_networks,
            should_stop=should_stop,
        )

    def urls(self, execution_id: str, **filters: Any) -> dict[str, Any]:
        execution = self.get(execution_id)
        reader = self._readers(self._datasets.get(execution["datasetId"]))
        return reader.execution_urls(execution_id, **filters)
