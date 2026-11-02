"""Transactional schedule claims and tick settlement."""

import secrets
import time
from typing import Any


def _row(row) -> dict[str, Any]:
    return {
        "jobId": row["job_id"],
        "cron": row["cron"],
        "timezone": row["timezone"],
        "status": row["status"],
        "nextRunAt": row["next_run_at"],
        "lastRunAt": row["last_run_at"],
        "lastError": row["last_error"],
        "failureCount": row["failure_count"],
        "maxDurationSeconds": row["max_duration_seconds"],
        "misfirePolicy": row["misfire_policy"],
        "missedRunCount": row["missed_run_count"],
        "lastMissedAt": row["last_missed_at"],
    }


class SQLiteScheduleRepository:
    def __init__(self, state):
        self.state = state

    def get(self, job_id):
        row = self.state.execute(
            "SELECT * FROM schedules WHERE job_id=?", (job_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"job {job_id} has no schedule")
        return dict(row)

    def list(self):
        return [
            _row(row)
            for row in self.state.execute(
                "SELECT * FROM schedules ORDER BY job_id"
            ).fetchall()
        ]

    def set(
        self, job_id, cron, timezone_name, next_run,
        *, max_duration_seconds=None, misfire_policy="skip"
    ):
        self.state.execute(
            "INSERT INTO schedules(job_id,cron,timezone,status,next_run_at,last_run_at,"
            "claimed_at,max_duration_seconds,misfire_policy) "
            "VALUES(?,?,?,'active',?,NULL,NULL,?,?) ON CONFLICT(job_id) DO UPDATE SET "
            "cron=excluded.cron,timezone=excluded.timezone,status='active',"
            "next_run_at=excluded.next_run_at,claimed_at=NULL,claim_token=NULL,"
            "last_error=NULL,failure_count=0,max_duration_seconds=excluded.max_duration_seconds,"
            "misfire_policy=excluded.misfire_policy",
            (job_id, cron, timezone_name, next_run, max_duration_seconds, misfire_policy),
        )

    def set_status(self, job_id, status, next_run):
        self.state.execute(
            "UPDATE schedules SET status=?,next_run_at=?,claimed_at=NULL,claim_token=NULL WHERE job_id=?",
            (status, next_run, job_id),
        )

    def has_other_execution(self, job_id, execution_id):
        return (
            self.state.execute(
                "SELECT 1 FROM executions WHERE job_id=? AND status IN "
                "('queued','running','cancelling') AND execution_id<>? LIMIT 1",
                (job_id, execution_id),
            ).fetchone()
            is not None
        )

    def complete(self, schedule, next_run, error=None, *, missed_runs=0, last_missed_at=None):
        self.state.execute(
            "UPDATE schedules SET next_run_at=?,last_run_at=?,claimed_at=NULL,"
            "claim_token=NULL,last_error=?,failure_count=CASE WHEN ? IS NULL THEN 0 "
            "ELSE failure_count+1 END,missed_run_count=missed_run_count+?,"
            "last_missed_at=coalesce(?,last_missed_at) "
            "WHERE job_id=? AND claim_token=?",
            (
                next_run,
                schedule["next_run_at"],
                error,
                error,
                missed_runs,
                last_missed_at,
                schedule["job_id"],
                schedule["claim_token"],
            ),
        )

    def release(self, schedule):
        self.state.execute(
            "UPDATE schedules SET claimed_at=NULL,claim_token=NULL WHERE job_id=? AND claim_token=?",
            (schedule["job_id"], schedule["claim_token"]),
        )

    def status(self):
        row = self.state.execute(
            "SELECT * FROM scheduler_state WHERE singleton=1"
        ).fetchone()
        return {
            "active": bool(
                row["owner_token"]
                and row["lease_until"] is not None
                and float(row["lease_until"]) > time.time()
            ),
            "ownerToken": row["owner_token"],
            "heartbeatAt": row["heartbeat_at"],
            "leaseUntil": row["lease_until"],
            "stopping": bool(row["stopping"]),
            "lastError": row["last_error"],
        }

    def claim_due(self, now, stale):
        claimed = []
        with self.state.transaction() as db:
            rows = db.execute(
                """
                SELECT * FROM schedules WHERE status='active' AND next_run_at<=?
                  AND (claimed_at IS NULL OR claimed_at<?)
                ORDER BY next_run_at,job_id
                """,
                (now.isoformat(), stale),
            ).fetchall()
            for row in rows:
                claim_token = secrets.token_hex(16)
                updated = db.execute(
                    """
                    UPDATE schedules SET claimed_at=?,claim_token=? WHERE job_id=?
                      AND (claimed_at IS NULL OR claimed_at<?)
                    """,
                    (now.isoformat(), claim_token, row["job_id"], stale),
                )
                if updated.rowcount == 1:
                    claimed.append({**dict(row), "claim_token": claim_token})

        return claimed
