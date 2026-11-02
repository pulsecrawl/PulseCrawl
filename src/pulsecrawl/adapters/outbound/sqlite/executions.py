"""Transactional execution repository; never exposes SQL to use cases."""

from __future__ import annotations
import json
import time
from typing import Any, Mapping
from pulsecrawl.domain.workspace.definitions import _identifier, _safe_identifier
from pulsecrawl.domain.executions.lifecycle import Execution, freeze_intent


class SQLiteExecutionRepository:
    def __init__(self, state, jobs, now):
        self.state, self.jobs, self.now = state, jobs, now

    @staticmethod
    def _row(row) -> dict[str, Any]:
        stats = json.loads(row["stats_json"]) if row["stats_json"] else None
        return {
            "executionId": row["execution_id"],
            "jobId": row["job_id"],
            "datasetId": row["dataset_id"],
            "status": row["status"],
            "trigger": row["trigger"],
            "scheduledFor": row["scheduled_for"],
            "intent": json.loads(row["intent_json"]),
            "stats": stats,
            "error": row["error"],
            "reservedUrls": row["reserved_urls"],
            "createdAt": row["created_at"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "cancellationRequestedAt": row["cancellation_requested_at"],
            "cancellationMode": row["cancellation_mode"],
            "stopReason": stats.get("stop_reason") if stats else None,
            "pendingUrlsAtClose": stats.get("pending_urls_at_close") if stats else None,
        }

    def list(self, job_id: str | None = None) -> list[dict[str, Any]]:
        if job_id:
            rows = self.state.execute(
                "SELECT * FROM executions WHERE job_id=? ORDER BY created_at DESC",
                (job_id,),
            ).fetchall()
        else:
            rows = self.state.execute(
                "SELECT * FROM executions ORDER BY created_at DESC"
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, execution_id: str) -> dict[str, Any]:
        row = self.state.execute(
            "SELECT * FROM executions WHERE execution_id=?", (execution_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown execution: {execution_id}")
        return self._row(row)

    def finish(
        self,
        execution_id: str,
        *,
        status: str,
        stats: Mapping[str, Any] | None,
        error: str | None,
        finished_at: str,
        discard_staged: bool,
    ) -> None:
        """Atomically settle a reservation and publish terminal SQLite state.

        A process loss can now leave either a restartable `running` execution
        with its reservation, or a completely settled terminal execution; it
        cannot strand lifetime budget between those two states.
        """
        with self.state.transaction() as db:
            execution = db.execute(
                "SELECT job_id,reserved_urls,status FROM executions WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            if execution is None:
                raise KeyError(f"unknown execution: {execution_id}")
            Execution(execution_id, execution["status"]).require_terminal_transition(
                status
            )
            reservation = int(execution["reserved_urls"])
            actual = db.execute(
                """
                SELECT count(*) AS n FROM visited WHERE execution_id=?
                  AND (status IN ('fetched','failed') OR error LIKE 'redirect %')
                """,
                (execution_id,),
            ).fetchone()["n"]
            if reservation:
                db.execute(
                    """
                    UPDATE jobs SET urls_used=urls_used+?,
                      urls_reserved=max(urls_reserved-?,0) WHERE job_id=?
                    """,
                    (actual, reservation, execution["job_id"]),
                )
            db.execute(
                """
                UPDATE executions SET status=?,stats_json=?,error=?,finished_at=?,
                  reserved_urls=0 WHERE execution_id=?
                """,
                (
                    status,
                    json.dumps(stats, sort_keys=True) if stats is not None else None,
                    error,
                    finished_at,
                    execution_id,
                ),
            )
            time_limited = bool(
                stats and stats.get("stop_reason") == "time_limit_reached"
            )
            pending_status = "skipped" if time_limited else "failed"
            pending_error = (
                "execution time limit reached before URL completion"
                if time_limited
                else f"execution ended as {status} before URL completion"
            )
            db.execute(
                """
                UPDATE visited SET status=?,
                  error=coalesce(error,?)
                WHERE execution_id=? AND status='queued'
                """,
                (pending_status, pending_error, execution_id),
            )
            db.execute("DELETE FROM pending_urls WHERE execution_id=?", (execution_id,))
            if discard_staged:
                db.execute(
                    "DELETE FROM staged_records WHERE execution_id=?", (execution_id,)
                )

    def cancellation_requested(self, execution_id: str) -> bool:
        row = self.state.execute(
            "SELECT cancellation_requested_at FROM executions WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
        return row is not None and row["cancellation_requested_at"] is not None

    def prepare(
        self,
        job_id: str,
        *,
        trigger: str = "manual",
        scheduled_for: str | None = None,
        execution_id: str | None = None,
        max_urls_per_execution: int | None = None,
        max_depth: int | None = None,
        store_raw_pages: bool | None = None,
        publish_records: bool = True,
        max_duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Atomically freeze an intent and reserve its lifetime budget.

        The returned execution is queued but not run. This is useful to a
        scheduler or another local process; calling ``executions.resume``
        starts it without creating a second intent.
        """
        job = self.jobs.get(job_id)
        execution_id = execution_id or _identifier(
            "exec" if trigger == "manual" else "exec_sched"
        )
        _safe_identifier(execution_id, "execution_id")
        created = self.now()
        with self.state.transaction() as db:
            # BEGIN IMMEDIATE serializes this check with reservation and
            # insertion, including callers using other SQLite connections.
            # A retry must return the original intent before checking budget.
            existing = db.execute(
                "SELECT * FROM executions WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if existing is not None:
                return self._row(existing)
            budget = db.execute(
                "SELECT max_urls_total,urls_used,urls_reserved FROM jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            remaining = (
                int(budget["max_urls_total"])
                - int(budget["urls_used"])
                - int(budget["urls_reserved"])
            )
            intent, reservation = freeze_intent(
                job,
                remaining,
                max_urls_per_execution=max_urls_per_execution,
                max_depth=max_depth,
                store_raw_pages=store_raw_pages,
                publish_records=publish_records,
                max_duration_seconds=max_duration_seconds,
            )
            db.execute(
                "UPDATE jobs SET urls_reserved=urls_reserved+? WHERE job_id=?",
                (reservation, job_id),
            )
            db.execute(
                """
                INSERT INTO executions(
                  execution_id,job_id,dataset_id,status,trigger,scheduled_for,intent_json,
                  reserved_urls,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    execution_id,
                    job_id,
                    job["datasetId"],
                    "queued",
                    trigger,
                    scheduled_for,
                    json.dumps(intent, sort_keys=True),
                    reservation,
                    created,
                ),
            )
        return self.get(execution_id)

    def start(self, execution_id, started_at):
        self.state.execute(
            "UPDATE executions SET status='running',started_at=?,error=NULL WHERE execution_id=?",
            (started_at, execution_id),
        )

    def request_cancellation(self, execution_id, requested_at, mode):
        self.state.execute(
            "UPDATE executions SET status='cancelling',cancellation_requested_at=?,cancellation_mode=? WHERE execution_id=? AND status NOT IN ('succeeded','failed','cancelled')",
            (requested_at, mode, execution_id),
        )

    def abandoned(self, status):
        rows = self.state.execute(
            "SELECT e.execution_id FROM executions e LEFT JOIN execution_leases l ON l.execution_id=e.execution_id WHERE e.status=? AND (l.execution_id IS NULL OR l.lease_until<=?) ORDER BY e.created_at,e.execution_id",
            (status, time.time()),
        ).fetchall()
        return [str(row["execution_id"]) for row in rows]
