"""Backup, restore, retention, health, and repair for local workspaces."""

from __future__ import annotations

import secrets
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from pulsecrawl.domain.errors import WorkspaceBusyError
from pulsecrawl.adapters.outbound.sqlite.clock import utc_now


class SQLiteMaintenanceLease:
    def __init__(self, state):
        self.state = state

    @contextmanager
    def hold(self, *, timeout_s: float = 300.0) -> Iterator[None]:
        """Own the global maintenance lease and reject live execution writers."""
        if timeout_s < 3:
            raise ValueError("maintenance lock timeout must be at least 3 seconds")
        owner = secrets.token_hex(16)
        now = time.time()
        with self.state.transaction() as db:
            db.execute("DELETE FROM maintenance_leases WHERE lease_until<=?", (now,))
            active = db.execute(
                "SELECT execution_id FROM execution_leases WHERE lease_until>? LIMIT 1",
                (now,),
            ).fetchone()
            if active is not None:
                raise WorkspaceBusyError(
                    f"execution {active['execution_id']} is currently writing the workspace"
                )
            existing = db.execute(
                "SELECT owner_token FROM maintenance_leases WHERE name='global'"
            ).fetchone()
            if existing is not None:
                raise WorkspaceBusyError(
                    "another maintenance operation owns the workspace"
                )
            db.execute(
                "INSERT INTO maintenance_leases VALUES('global',?,?,?)",
                (owner, now + timeout_s, utc_now()),
            )
        stop_renewal = threading.Event()
        lease_lost = threading.Event()

        def renew() -> None:
            while not stop_renewal.wait(timeout_s / 3):
                updated = self.state.execute(
                    """
                    UPDATE maintenance_leases SET lease_until=?
                    WHERE name='global' AND owner_token=?
                    """,
                    (time.time() + timeout_s, owner),
                )
                if updated.rowcount != 1:
                    lease_lost.set()
                    return

        heartbeat = threading.Thread(
            target=renew, name="pulsecrawl-maintenance-lease", daemon=True
        )
        heartbeat.start()
        try:
            yield
            if lease_lost.is_set():
                raise WorkspaceBusyError("maintenance lease ownership was lost")
        finally:
            stop_renewal.set()
            heartbeat.join(timeout=min(timeout_s / 3 + 1, 10))
            self.state.execute(
                "DELETE FROM maintenance_leases WHERE name='global' AND owner_token=?",
                (owner,),
            )
