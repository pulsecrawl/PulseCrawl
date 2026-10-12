"""Shared-connection cursors must respect transaction synchronization."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

import pytest

from pulsecrawl.adapters.outbound.sqlite.state import SQLiteState


@pytest.mark.parametrize("operation", ["fetchone", "fetchall", "fetchmany", "next", "close"])
def test_cursor_operations_wait_for_connection_lock(tmp_path, operation):
    state = SQLiteState(tmp_path / "state.sqlite")
    started = Event()
    cursor = state.execute("SELECT 42 AS value UNION ALL SELECT 43")

    def read():
        started.set()
        return next(cursor) if operation == "next" else getattr(cursor, operation)()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with state._lock:
                result = pool.submit(read)
                assert started.wait(timeout=5)
                with pytest.raises(TimeoutError):
                    result.result(timeout=0.05)
            value = result.result(timeout=5)
        if operation != "close":
            row = value[0] if operation in {"fetchall", "fetchmany"} else value
            assert row["value"] == 42
    finally:
        cursor.close()
        state.close()


def test_parallel_cursors_keep_rows_and_metadata_isolated(tmp_path):
    state = SQLiteState(tmp_path / "state.sqlite")
    try:
        def read(worker):
            for iteration in range(100):
                expected = f"worker-{worker}-{iteration}"
                cursor = state.execute("SELECT ? AS value UNION ALL SELECT ?", (expected, expected))
                assert [row["value"] for row in cursor] == [expected, expected]
                assert cursor.description[0][0] == "value"
                cursor.close()

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(read, range(8)))
    finally:
        state.close()
