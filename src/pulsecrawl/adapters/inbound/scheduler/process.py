"""Native process driver: signals, sleeping and heartbeat-thread ownership."""

from __future__ import annotations
import secrets
import signal
import threading
from typing import Any


def serve(
    service,
    lease,
    *,
    poll_seconds: float = 30.0,
    shutdown_event: threading.Event | None = None,
) -> None:
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    stopping = shutdown_event or threading.Event()
    owner_token = secrets.token_hex(16)
    lease_seconds = max(poll_seconds * 3, 30.0)
    previous_handlers: dict[int, Any] = {}
    heartbeat_stop = threading.Event()
    heartbeat: threading.Thread | None = None

    def request_stop(_signum=None, _frame=None) -> None:
        stopping.set()

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
    try:
        lease.claim(owner_token, lease_seconds)

        def keep_scheduler_lease() -> None:
            while not heartbeat_stop.wait(min(lease_seconds / 3, 10.0)):
                if not lease.heartbeat(owner_token, lease_seconds):
                    stopping.set()
                    return

        heartbeat = threading.Thread(
            target=keep_scheduler_lease,
            name="pulsecrawl-scheduler-heartbeat",
            daemon=True,
        )
        heartbeat.start()
        service.recover_incomplete(should_stop=stopping.is_set)
        while not stopping.is_set():
            lease.heartbeat(owner_token, lease_seconds)
            service.run_due(should_stop=stopping.is_set)
            stopping.wait(poll_seconds)
    except BaseException as exc:
        lease.error(owner_token, f"{type(exc).__name__}: {exc}"[:1000])
        raise
    finally:
        heartbeat_stop.set()
        if heartbeat is not None:
            heartbeat.join(timeout=min(lease_seconds / 3 + 1, 11))
        lease.release(owner_token)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
