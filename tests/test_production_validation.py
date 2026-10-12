"""OS-level production validation for the self-contained OSS runtime.

These tests deliberately cross process and persistence boundaries. They are
kept deterministic and offline so the same gates run on developer machines
and every supported CI platform.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from pulsecrawl.core.model import FetchResult

from pulsecrawl import Workspace
from pulsecrawl.errors import DatasetCorruptionError
from pulsecrawl.local_dataset import _contained_path, validate_select_only


FIELDS = [
    {"fieldId": "fld_title", "name": "title", "type": "string"},
    {"fieldId": "fld_url", "name": "canonical", "type": "url"},
]


class Fetcher:
    async def fetch(self, url, *, user_agent):
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            headers={"Content-Type": "text/html"},
            body=f'<h1>{url}</h1><link rel="canonical" href="{url}">',
            error=None,
            fetched_at=time_to_datetime(),
        )


def time_to_datetime():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def add_job(workspace: Workspace, *, max_urls_total: int = 100):
    dataset = workspace.datasets.create("production-data", fields=FIELDS)
    job = workspace.jobs.create(
        "production-job",
        seeds=["https://production.example/"],
        dataset_id=dataset["datasetId"],
        templates=[{
            "engine": "css",
            "mappings": {"fld_title": "h1", "fld_url": "link@href"},
        }],
        scope={
            "maxDepth": 0,
            "maxUrlsPerExecution": 1,
            "maxUrlsTotal": max_urls_total,
        },
        politeness={"respectRobotsTxt": False, "requestsPerSecond": 1000},
    )
    return dataset, job


@pytest.fixture
def workspace(tmp_path):
    value = Workspace.init(tmp_path / "workspace", name="production-validation")
    yield value
    value.close()


def run_script(source: str, *args: object, timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source), *(str(arg) for arg in args)],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def start_workers(
    source: str,
    argument_sets: list[tuple[object, ...]],
    gate: Path,
    *,
    timeout: float = 20,
) -> list[dict[str, object]]:
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                textwrap.dedent(source),
                *(str(value) for value in arguments),
                str(gate),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for arguments in argument_sets
    ]
    gate.write_text("go", encoding="utf-8")
    reports = []
    for process, arguments in zip(processes, argument_sets):
        stdout, stderr = process.communicate(timeout=timeout)
        assert process.returncode == 0, (stdout, stderr)
        reports.append(json.loads(Path(arguments[-1]).read_text(encoding="utf-8")))
    return reports


def test_simultaneous_processes_execute_an_intent_only_once(workspace, tmp_path):
    dataset, job = add_job(workspace)
    prepared = workspace.jobs.prepare(job["jobId"])
    gate = tmp_path / "execution.gate"
    results = [tmp_path / f"execution-{index}.json" for index in range(4)]
    script = r"""
import asyncio, json, sys, time
from datetime import datetime, timezone
from pathlib import Path
from pulsecrawl import Workspace
from pulsecrawl.errors import WorkspaceBusyError, WorkspaceError
from pulsecrawl.core.model import FetchResult

workspace_path, execution_id, marker_path, result_path, gate_path = sys.argv[1:]
while not Path(gate_path).exists():
    time.sleep(0.005)

class SlowFetcher:
    async def fetch(self, url, *, user_agent):
        Path(marker_path).write_text("fetched", encoding="utf-8")
        await asyncio.sleep(0.75)
        return FetchResult(
            url=url, final_url=url, status=200, headers={},
            body=f'<h1>{url}</h1><link rel="canonical" href="{url}">',
            error=None, fetched_at=datetime.now(timezone.utc),
        )

try:
    with Workspace(workspace_path) as workspace:
        result = workspace.executions.resume(execution_id, fetcher=SlowFetcher())
    report = {"outcome": "completed", "status": result["status"]}
except WorkspaceBusyError as exc:
    report = {"outcome": "busy", "message": str(exc)}
except WorkspaceError as exc:
    report = {"outcome": "already_done", "message": str(exc)}
Path(result_path).write_text(json.dumps(report), encoding="utf-8")
"""
    markers = [tmp_path / f"fetch-{index}.marker" for index in range(4)]
    reports = start_workers(
        script,
        [
            (workspace.path, prepared["executionId"], marker, result)
            for marker, result in zip(markers, results)
        ],
        gate,
    )
    assert sum(marker.exists() for marker in markers) == 1
    assert sum(report["outcome"] == "completed" for report in reports) == 1
    assert {report["outcome"] for report in reports} <= {
        "completed",
        "busy",
        "already_done",
    }
    assert workspace.datasets.query(
        dataset["datasetId"], "SELECT count(*) FROM dataset"
    )["rows"] == [[1]]
    assert workspace.validate()["valid"] is True


def test_simultaneous_scheduler_processes_have_one_owner(workspace, tmp_path):
    gate = tmp_path / "scheduler.gate"
    results = [tmp_path / f"scheduler-{index}.json" for index in range(4)]
    script = r"""
import json, sys, threading, time
from pathlib import Path
from pulsecrawl import Workspace
from pulsecrawl.errors import WorkspaceBusyError

workspace_path, result_path, gate_path = sys.argv[1:]
while not Path(gate_path).exists():
    time.sleep(0.005)
stop = threading.Event()
threading.Timer(0.75, stop.set).start()
try:
    with Workspace(workspace_path) as workspace:
        workspace.schedules.serve(poll_seconds=0.05, shutdown_event=stop)
    report = {"outcome": "owner"}
except WorkspaceBusyError as exc:
    stop.set()
    report = {"outcome": "busy", "message": str(exc)}
Path(result_path).write_text(json.dumps(report), encoding="utf-8")
"""
    reports = start_workers(
        script,
        [(workspace.path, result) for result in results],
        gate,
    )
    assert [report["outcome"] for report in reports].count("owner") == 1
    assert [report["outcome"] for report in reports].count("busy") == 3
    assert workspace.schedules.status()["ownerToken"] is None


def test_execution_and_maintenance_cannot_overlap(workspace, tmp_path):
    _, job = add_job(workspace)
    prepared = workspace.jobs.prepare(job["jobId"])
    gate = tmp_path / "maintenance-execution.gate"
    execution_result = tmp_path / "execution.json"
    maintenance_result = tmp_path / "maintenance.json"
    script = r"""
import asyncio, json, sys, time
from datetime import datetime, timezone
from pathlib import Path
from pulsecrawl import Workspace
from pulsecrawl.errors import WorkspaceBusyError
from pulsecrawl.core.model import FetchResult

role, workspace_path, execution_id, result_path, gate_path = sys.argv[1:]
while not Path(gate_path).exists():
    time.sleep(0.005)

class SlowFetcher:
    async def fetch(self, url, *, user_agent):
        await asyncio.sleep(0.75)
        return FetchResult(
            url=url, final_url=url, status=200, headers={},
            body=f'<h1>{url}</h1><link rel="canonical" href="{url}">',
            error=None, fetched_at=datetime.now(timezone.utc),
        )

try:
    with Workspace(workspace_path) as workspace:
        if role == "execution":
            started = time.time()
            workspace.executions.resume(execution_id, fetcher=SlowFetcher())
            ended = time.time()
        else:
            with workspace.maintenance.lock(timeout_s=3):
                started = time.time()
                time.sleep(0.75)
                ended = time.time()
    report = {"outcome": "acquired", "started": started, "ended": ended}
except WorkspaceBusyError as exc:
    report = {"outcome": "busy", "message": str(exc)}
Path(result_path).write_text(json.dumps(report), encoding="utf-8")
"""
    reports = start_workers(
        script,
        [
            ("execution", workspace.path, prepared["executionId"], execution_result),
            ("maintenance", workspace.path, prepared["executionId"], maintenance_result),
        ],
        gate,
    )
    acquired = [report for report in reports if report["outcome"] == "acquired"]
    assert len(acquired) == 1
    assert sum(report["outcome"] == "busy" for report in reports) == 1


def test_crash_before_workspace_metadata_rename_is_recoverable(tmp_path):
    root = tmp_path / "legacy"
    root.mkdir()
    for directory in (
        "fields",
        "schemas",
        "templates/system",
        "templates/custom",
        "template-drafts",
        "jobs",
        "schedules",
        "executions",
        "datasets",
        "state",
        "cache",
        ".maintenance",
    ):
        (root / directory).mkdir(parents=True)
    original = {
        "workspaceVersion": 1,
        "name": "legacy",
        "orgId": "local",
        "createdAt": "2026-01-01T00:00:00+00:00",
    }
    config = root / "pulsecrawl.json"
    config.write_text(json.dumps(original), encoding="utf-8")
    crashed = run_script(
        r"""
import os, sys
from pathlib import Path
import pulsecrawl.local_dataset as local_dataset
from pulsecrawl import Workspace

target = Path(sys.argv[2]).resolve()
original_replace = local_dataset.os.replace
def crash_before_replace(source, destination):
    if Path(destination).resolve() == target:
        os._exit(70)
    return original_replace(source, destination)
local_dataset.os.replace = crash_before_replace
Workspace(sys.argv[1])
""",
        root,
        config,
    )
    assert crashed.returncode == 70
    assert json.loads(config.read_text(encoding="utf-8")) == original
    with Workspace(root) as recovered:
        assert recovered.config["workspaceVersion"] == 2
        assert recovered.health(readiness=True)["ready"] is True


@pytest.mark.parametrize("boundary", ["manifest_pointer", "terminal_commit"])
def test_execution_recovers_from_hard_crash_at_commit_boundaries(
    workspace, boundary
):
    dataset, job = add_job(workspace)
    prepared = workspace.jobs.prepare(job["jobId"])
    script = r"""
import os, sys
from datetime import datetime, timezone
from pathlib import Path
from pulsecrawl import Workspace
from pulsecrawl.core.model import FetchResult

workspace_path, execution_id, boundary = sys.argv[1:]
if boundary == "manifest_pointer":
    import pulsecrawl.local_dataset as local_dataset
    original_replace = local_dataset.os.replace
    def crash_at_pointer(source, destination):
        if Path(destination).name == "current.json":
            os._exit(71)
        return original_replace(source, destination)
    local_dataset.os.replace = crash_at_pointer
else:
    from pulsecrawl.workspace_runtime import WorkspaceExecutions
    original_finish = WorkspaceExecutions._finish
    def crash_at_terminal_commit(self, target_execution_id, **kwargs):
        if kwargs.get("status") == "succeeded":
            os._exit(72)
        return original_finish(self, target_execution_id, **kwargs)
    WorkspaceExecutions._finish = crash_at_terminal_commit

class Fetcher:
    async def fetch(self, url, *, user_agent):
        return FetchResult(
            url=url, final_url=url, status=200, headers={},
            body=f'<h1>{url}</h1><link rel="canonical" href="{url}">',
            error=None, fetched_at=datetime.now(timezone.utc),
        )

with Workspace(workspace_path) as workspace:
    workspace.executions.resume(execution_id, fetcher=Fetcher())
"""
    crashed = run_script(script, workspace.path, prepared["executionId"], boundary)
    assert crashed.returncode == (71 if boundary == "manifest_pointer" else 72)
    workspace.state.execute(
        "UPDATE execution_leases SET lease_until=0 WHERE execution_id=?",
        (prepared["executionId"],),
    )
    recovered = workspace.executions.resume(prepared["executionId"], fetcher=Fetcher())
    assert recovered["status"] == "succeeded"
    assert workspace.datasets.query(
        dataset["datasetId"], "SELECT count(*) FROM dataset"
    )["rows"] == [[1]]
    assert workspace.maintenance.doctor()["valid"] is True


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT * FROM read_json_auto('https://example.com/private.json')",
        "SELECT * FROM read_blob('/etc/passwd')",
        "SELECT * FROM read_text('/etc/passwd')",
        "SELECT * FROM glob('/etc/*')",
        "SELECT * FROM parquet_metadata('/etc/passwd')",
        "SELECT * FROM sqlite_scan('/etc/passwd', 'secrets')",
        "SELECT load_extension('httpfs')",
    ],
)
def test_duckdb_external_access_attack_corpus_is_blocked(workspace, statement):
    dataset, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    with pytest.raises(Exception):
        workspace.datasets.query(dataset["datasetId"], statement)


@pytest.mark.parametrize(
    "statement",
    [
        "ATTACH '/tmp/escape.db' AS escape",
        "COPY dataset TO '/tmp/escape.csv'",
        "CREATE TABLE escape AS SELECT * FROM dataset",
        "EXPORT DATABASE '/tmp/escape'",
        "INSTALL httpfs",
        "LOAD httpfs",
        "PRAGMA database_list",
        "SELECT 1; COPY dataset TO '/tmp/escape.csv'",
    ],
)
def test_duckdb_side_effect_statements_are_rejected_before_execution(
    workspace, statement
):
    dataset, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    with pytest.raises(ValueError):
        workspace.datasets.query(dataset["datasetId"], statement)


def test_manifest_cannot_expand_duckdb_allowed_paths(workspace, tmp_path):
    dataset, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    root = workspace.path / "datasets" / dataset["datasetId"]
    current = json.loads((root / "manifests" / "current.json").read_text())
    snapshot_path = root / current["manifest"]
    snapshot = json.loads(snapshot_path.read_text())
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"not authorized")
    snapshot["files"][0]["path"] = os.path.relpath(outside, root)
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(DatasetCorruptionError, match="traversal|outside"):
        workspace.datasets.query(dataset["datasetId"], "SELECT * FROM dataset")
    assert workspace.validate()["valid"] is False


def test_manifest_snapshot_pointer_cannot_escape_dataset(workspace, tmp_path):
    dataset, _ = add_job(workspace)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"datasetId": dataset["datasetId"], "version": 0}))
    root = workspace.path / "datasets" / dataset["datasetId"]
    pointer = root / "manifests" / "current.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(
        json.dumps({
            "datasetId": dataset["datasetId"],
            "version": 0,
            "snapshot": os.path.relpath(outside, root),
        }),
        encoding="utf-8",
    )
    with pytest.raises(DatasetCorruptionError, match="traversal|outside"):
        workspace.datasets.files(dataset["datasetId"])


def test_path_and_sql_boundary_fuzz_never_authorizes_escape(tmp_path):
    generator = random.Random(20261001)
    root = tmp_path / "dataset"
    root.mkdir()
    alphabet = "abcXYZ0123._-/\\\x00; '()"
    for _ in range(5_000):
        candidate = "".join(
            generator.choice(alphabet) for _ in range(generator.randrange(0, 96))
        )
        try:
            path = _contained_path(root, candidate, kind="fuzz")
        except (DatasetCorruptionError, OSError, ValueError):
            pass
        else:
            path.relative_to(root.resolve())
        try:
            statement = validate_select_only(candidate)
        except (TypeError, ValueError):
            pass
        else:
            assert statement.split(None, 1)[0].upper() in ("SELECT", "WITH")
            assert ";" not in statement


def test_installed_cli_black_box_workspace_lifecycle(tmp_path):
    root = tmp_path / "cli-workspace"
    backup = tmp_path / "cli-backup"
    restored = tmp_path / "cli-restored"

    def cli(*arguments: object, expected: int = 0):
        result = subprocess.run(
            [sys.executable, "-m", "pulsecrawl.cli", *(str(arg) for arg in arguments)],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == expected, (result.stdout, result.stderr)
        stream = result.stdout if expected == 0 else result.stderr
        return json.loads(stream)

    initialized = cli("init", root, "--name", "CLI production validation")
    assert initialized["valid"] is True
    dataset = cli(
        "--workspace",
        root,
        "dataset",
        "create",
        "cli-data",
        "--fields",
        json.dumps(FIELDS),
    )
    assert dataset["datasetId"].startswith("ds_")
    assert cli("--workspace", root, "health", "--readiness")["ready"] is True
    assert cli("--workspace", root, "backup", "create", backup)["files"] > 0
    assert cli("backup", "verify", backup)["valid"] is True
    assert cli("backup", "restore", backup, restored)["restoredTo"] == str(restored)
    assert cli("--workspace", restored, "validate")["valid"] is True
    error = cli(
        "--workspace",
        root,
        "execution",
        "show",
        "missing",
        expected=3,
    )
    assert error["error"]["code"] == "not_found"
    assert set(error["error"]) == {"code", "message", "type"}
