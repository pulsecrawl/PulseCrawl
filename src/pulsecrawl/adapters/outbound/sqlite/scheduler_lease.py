"""Local scheduler process lease, independent of signal handling."""

import time
from pulsecrawl.domain.errors import WorkspaceBusyError
from pulsecrawl.adapters.outbound.sqlite.clock import utc_now


class SQLiteSchedulerLease:
    def __init__(self, state):
        self.state = state

    def claim(self, owner, seconds):
        now = time.time()
        with self.state.transaction() as db:
            row = db.execute(
                "SELECT owner_token,lease_until FROM scheduler_state WHERE singleton=1"
            ).fetchone()
            if (
                row["owner_token"]
                and row["lease_until"] is not None
                and float(row["lease_until"]) > now
            ):
                raise WorkspaceBusyError("another scheduler process is active")
            db.execute(
                "UPDATE scheduler_state SET owner_token=?,heartbeat_at=?,stopping=0,last_error=NULL,lease_until=? WHERE singleton=1",
                (owner, utc_now(), now + seconds),
            )

    def heartbeat(self, owner, seconds):
        result = self.state.execute(
            "UPDATE scheduler_state SET heartbeat_at=?,stopping=0,lease_until=? WHERE singleton=1 AND owner_token=?",
            (utc_now(), time.time() + seconds, owner),
        )
        return result.rowcount == 1

    def error(self, owner, error):
        self.state.execute(
            "UPDATE scheduler_state SET last_error=? WHERE singleton=1 AND owner_token=?",
            (error, owner),
        )

    def release(self, owner):
        self.state.execute(
            "UPDATE scheduler_state SET heartbeat_at=?,stopping=1,owner_token=NULL,lease_until=NULL WHERE singleton=1 AND owner_token=?",
            (utc_now(), owner),
        )
