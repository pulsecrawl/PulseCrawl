"""Windows snapshot replacement retries preserve atomicity and fail closed."""

import errno
import json
from pathlib import Path

import pytest

from pulsecrawl.adapters.outbound.filesystem import atomic
from pulsecrawl.domain.errors import WorkspaceReadOnlyError


def denied(code):
    error = PermissionError(errno.EACCES, "replacement denied")
    error.winerror = code
    return error


@pytest.mark.parametrize("code", [5, 32, 33])
def test_transient_windows_denial_reuses_complete_temp_file(tmp_path, monkeypatch, code):
    target = tmp_path / "snapshot.json"
    target.write_text('{"old": true}')
    replace = atomic.os.replace
    calls, waits = [], []

    def conflict_then_replace(source, destination):
        calls.append(source)
        assert destination == target
        assert json.loads(Path(source).read_text()) == {"new": True}
        assert json.loads(target.read_text()) == {"old": True}
        if len(calls) < 3:
            raise denied(code)
        replace(source, destination)

    monkeypatch.setattr(atomic, "_REPLACE_ATTEMPTS", 8)
    monkeypatch.setattr(atomic.os, "replace", conflict_then_replace)
    monkeypatch.setattr(atomic.time, "sleep", waits.append)
    atomic._atomic_json(target, {"new": True})
    assert len(calls) == 3 and len(set(calls)) == 1
    assert waits == [0.01, 0.02]
    assert json.loads(target.read_text()) == {"new": True}
    assert list(tmp_path.iterdir()) == [target]


def test_persistent_windows_denial_is_bounded_and_keeps_original(tmp_path, monkeypatch):
    target = tmp_path / "snapshot.json"
    target.write_text('{"old": true}')
    calls, waits = [], []

    def always_denied(source, destination):
        calls.append(source)
        raise denied(5)

    monkeypatch.setattr(atomic, "_REPLACE_ATTEMPTS", 8)
    monkeypatch.setattr(atomic.os, "replace", always_denied)
    monkeypatch.setattr(atomic.time, "sleep", waits.append)
    with pytest.raises(WorkspaceReadOnlyError):
        atomic._atomic_json(target, {"new": True})
    assert len(calls) == 8 and len(set(calls)) == 1
    assert sum(waits) == pytest.approx(1.27)
    assert json.loads(target.read_text()) == {"old": True}
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("code,attempts", [(None, 8), (87, 8), (5, 1)])
def test_other_permission_errors_and_non_windows_writes_do_not_retry(
    tmp_path, monkeypatch, code, attempts
):
    calls = []

    def fail(source, destination):
        calls.append(source)
        raise denied(code)

    def no_wait(delay):
        raise AssertionError("unexpected retry")

    monkeypatch.setattr(atomic, "_REPLACE_ATTEMPTS", attempts)
    monkeypatch.setattr(atomic.os, "replace", fail)
    monkeypatch.setattr(atomic.time, "sleep", no_wait)
    with pytest.raises(WorkspaceReadOnlyError):
        atomic._atomic_json(tmp_path / "snapshot.json", {"new": True})
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []
