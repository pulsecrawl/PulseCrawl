"""Single-machine runner leases with bounded heartbeat resource ownership."""

import threading
import time
from contextlib import contextmanager
from pulsecrawl.domain.errors import WorkspaceBusyError


class SQLiteExecutionLease:
    def __init__(self, state):
        self.state = state

    def claim(self, execution_id: str, owner_token: str, lease_seconds: float) -> None:
        """Claim one execution, reclaiming only an expired local runner.

        The heartbeat makes native scheduler recovery safe without requiring
        Redis.  If a process disappears, its lease expires and the next
        scheduler start resets any abandoned frontier leases before resuming.
        """
        now = time.time()
        with self.state.transaction() as db:
            maintenance = db.execute(
                "SELECT owner_token FROM maintenance_leases "
                "WHERE name='global' AND lease_until>?",
                (now,),
            ).fetchone()
            if maintenance is not None:
                raise WorkspaceBusyError(
                    "workspace maintenance is active; execution cannot start"
                )
            current = db.execute(
                "SELECT owner_token,lease_until FROM execution_leases WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            if current is not None and float(current["lease_until"]) > now:
                raise WorkspaceBusyError(
                    f"execution {execution_id} already has an active runner"
                )
            # No live execution lease means any frontier lease belongs to a
            # dead or gracefully cancelled runner. Reclaim it immediately;
            # waiting for the per-item lease timeout would make an otherwise
            # recoverable local execution appear hung.
            db.execute(
                """
                UPDATE frontier SET state='pending',lease_until=NULL
                WHERE execution_id=? AND state='leased'
                """,
                (execution_id,),
            )
            db.execute(
                """
                INSERT INTO execution_leases(execution_id,owner_token,lease_until,heartbeat_at)
                VALUES(?,?,?,?)
                ON CONFLICT(execution_id) DO UPDATE SET
                  owner_token=excluded.owner_token,
                  lease_until=excluded.lease_until,
                  heartbeat_at=excluded.heartbeat_at
                """,
                (execution_id, owner_token, now + lease_seconds, now),
            )

    def heartbeat(
        self, execution_id: str, owner_token: str, lease_seconds: float
    ) -> bool:
        now = time.time()
        updated = self.state.execute(
            """
            UPDATE execution_leases SET lease_until=?,heartbeat_at=?
            WHERE execution_id=? AND owner_token=?
            """,
            (now + lease_seconds, now, execution_id, owner_token),
        )
        return updated.rowcount == 1

    def release(self, execution_id: str, owner_token: str) -> None:
        self.state.execute(
            "DELETE FROM execution_leases WHERE execution_id=? AND owner_token=?",
            (execution_id, owner_token),
        )

    def active(self, execution_id):
        row = self.state.execute(
            "SELECT lease_until FROM execution_leases WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
        return row is not None and float(row["lease_until"]) > time.time()

    @contextmanager
    def hold(self, execution_id, owner_token, lease_seconds, heartbeat_seconds):
        self.claim(execution_id, owner_token, lease_seconds)
        stop = threading.Event()

        def renew():
            while not stop.wait(heartbeat_seconds):
                if not self.heartbeat(execution_id, owner_token, lease_seconds):
                    return

        thread = threading.Thread(
            target=renew, name=f"pulsecrawl-lease-{execution_id}", daemon=True
        )
        try:
            thread.start()
            yield
        finally:
            stop.set()
            if thread.ident is not None:
                thread.join(timeout=heartbeat_seconds + 1)
            self.release(execution_id, owner_token)
