import asyncio
import errno
import json
import logging
import os
import random
import subprocess
import sys
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone

import pytest
from pulsecrawl.core.model import FetchResult

from pulsecrawl import Workspace
from pulsecrawl.cli import _json_argument, main
from pulsecrawl.errors import (
    DatasetCorruptionError,
    InsufficientStorageError,
    WorkspaceBusyError,
    WorkspaceReadOnlyError,
)
from pulsecrawl.local_dataset import _atomic_json, normalize_url_identity
from pulsecrawl.local_scheduler import run_due
from pulsecrawl.observability import event as log_event
from pulsecrawl.sqlite_state import SCHEMA_VERSION, SQLiteState
from pulsecrawl.workspace_maintenance import WorkspaceMaintenance


FIELDS = [
    {"fieldId": "fld_title", "name": "title", "type": "string"},
    {"fieldId": "fld_url", "name": "canonical", "type": "url"},
]


class Fetcher:
    def __init__(self, *, failing_host=None):
        self.failing_host = failing_host

    async def fetch(self, url, *, user_agent):
        if self.failing_host and self.failing_host in url:
            raise RuntimeError("deliberate schedule failure")
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            headers={},
            body=(
                f'<h1>{url}</h1><link rel="canonical" href="{url}">'
            ),
            error=None,
            fetched_at=datetime.now(timezone.utc),
        )


class PausingFetcher(Fetcher):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch(self, url, *, user_agent):
        self.started.set()
        await self.release.wait()
        return await super().fetch(url, user_agent=user_agent)


def add_job(workspace, name="one", host="one.example"):
    dataset = workspace.datasets.create(f"{name}-data", fields=FIELDS)
    job = workspace.jobs.create(
        name,
        seeds=[f"https://{host}/"],
        dataset_id=dataset["datasetId"],
        templates=[{
            "engine": "css",
            "mappings": {"fld_title": "h1", "fld_url": "link@href"},
        }],
        scope={"maxUrlsPerExecution": 10, "maxUrlsTotal": 100},
        politeness={"respectRobotsTxt": False, "requestsPerSecond": 1000},
    )
    return dataset, job


@pytest.fixture
def workspace(tmp_path):
    value = Workspace.init(tmp_path / "workspace", name="hardening")
    yield value
    value.close()


def test_workspace_metadata_migrates_with_backup(tmp_path):
    root = tmp_path / "legacy"
    root.mkdir()
    legacy = {
        "workspaceVersion": 1,
        "name": "legacy",
        "orgId": "local",
        "createdAt": "2026-01-01T00:00:00+00:00",
    }
    (root / "pulsecrawl.json").write_text(json.dumps(legacy), encoding="utf-8")

    with Workspace(root) as migrated:
        assert migrated.config["workspaceVersion"] == 2
        assert migrated.config["workspaceId"].startswith("ws_")

    backup = root / "pulsecrawl.json.pre-migration-v1-to-v2.backup"
    assert json.loads(backup.read_text(encoding="utf-8")) == legacy


def test_sqlite_migrates_sequentially_and_keeps_pre_migration_backup(tmp_path):
    path = tmp_path / "state.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE workspace_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        db.execute("INSERT INTO workspace_meta VALUES('schema_version','1')")

    state = SQLiteState(path)
    try:
        assert state.schema_version == SCHEMA_VERSION
        assert state._has_column(state._db, "executions", "cancellation_mode")
        assert state._has_column(state._db, "frontier", "retry_count")
    finally:
        state.close()
    assert path.with_name(
        f"state.sqlite.pre-migration-v1-to-v{SCHEMA_VERSION}.backup"
    ).is_file()


def test_failed_sqlite_migration_rolls_back_schema_and_version(tmp_path):
    path = tmp_path / "rollback.sqlite"
    state = SQLiteState(path)
    state.execute("UPDATE workspace_meta SET value='3' WHERE key='schema_version'")
    state.execute("ALTER TABLE scheduler_state DROP COLUMN lease_until")
    state.close()

    class BrokenMigrationState(SQLiteState):
        def _migrate_v3_to_v4(self, db):
            db.execute("ALTER TABLE scheduler_state ADD COLUMN rollback_probe TEXT")
            raise RuntimeError("migration failpoint")

    with pytest.raises(RuntimeError, match="failpoint"):
        BrokenMigrationState(path)
    with closing(sqlite3.connect(path)) as db:
        version = db.execute(
            "SELECT value FROM workspace_meta WHERE key='schema_version'"
        ).fetchone()[0]
        columns = {row[1] for row in db.execute("PRAGMA table_info(scheduler_state)")}
    assert version == "3"
    assert "rollback_probe" not in columns


def test_backup_verify_restore_round_trip_and_tamper_detection(workspace, tmp_path):
    dataset, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    backup = tmp_path / "backup"
    report = workspace.maintenance.backup(backup)
    assert report["files"] > 0
    assert WorkspaceMaintenance.verify_backup(backup)["valid"] is True

    restored_path = tmp_path / "restored"
    restored = WorkspaceMaintenance.restore(backup, restored_path)
    assert restored["restoredTo"] == str(restored_path)
    with Workspace(restored_path) as reopened:
        assert reopened.datasets.query(
            dataset["datasetId"], "SELECT count(*) FROM dataset"
        )["rows"] == [[1]]

    config = backup / "pulsecrawl.json"
    config.write_text(config.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(DatasetCorruptionError, match="checksum mismatch"):
        WorkspaceMaintenance.verify_backup(backup)


def test_backup_refuses_unsafe_or_overwriting_targets(workspace, tmp_path):
    with pytest.raises(ValueError, match="outside"):
        workspace.maintenance.backup(workspace.path / "nested-backup")
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="overwrite"):
        workspace.maintenance.backup(existing)
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    with pytest.raises(DatasetCorruptionError, match="missing"):
        WorkspaceMaintenance.verify_backup(incomplete)


def test_maintenance_lock_blocks_new_execution(workspace):
    _, job = add_job(workspace)
    prepared = workspace.jobs.prepare(job["jobId"])
    with workspace.maintenance.lock(timeout_s=3):
        with pytest.raises(WorkspaceBusyError, match="maintenance"):
            workspace.executions.resume(prepared["executionId"], fetcher=Fetcher())


def test_hard_process_crash_leaves_execution_recoverable(workspace):
    _, job = add_job(workspace)
    prepared = workspace.jobs.prepare(job["jobId"])
    script = """
import asyncio, os, sys
from pulsecrawl import Workspace

class CrashFetcher:
    def __init__(self, workspace, execution_id):
        self.workspace = workspace
        self.execution_id = execution_id
    async def fetch(self, url, *, user_agent):
        self.workspace.state.execute(
            'UPDATE execution_leases SET lease_until=0 WHERE execution_id=?',
            (self.execution_id,),
        )
        os._exit(17)

workspace = Workspace(sys.argv[1])
execution_id = sys.argv[2]
asyncio.run(workspace.executions._execute(
    execution_id, fetcher=CrashFetcher(workspace, execution_id)
))
"""
    crashed = subprocess.run(
        [sys.executable, "-c", script, str(workspace.path), prepared["executionId"]],
        check=False,
        capture_output=True,
        text=True,
    )
    assert crashed.returncode == 17
    assert prepared["executionId"] in workspace.executions.recoverable()
    result = workspace.executions.resume(prepared["executionId"], fetcher=Fetcher())
    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_explicit_running_cancellation_settles_and_force_discards(workspace):
    _, job = add_job(workspace)
    prepared = workspace.jobs.prepare(job["jobId"])
    fetcher = PausingFetcher()
    task = asyncio.create_task(
        workspace.executions._execute(prepared["executionId"], fetcher=fetcher)
    )
    await fetcher.started.wait()
    requested = workspace.executions.cancel(prepared["executionId"], force=True)
    assert requested["status"] == "cancelling"
    fetcher.release.set()
    result = await task
    assert result["status"] == "cancelled"
    assert result["cancellationMode"] == "force"
    assert workspace.state.execute(
        "SELECT count(*) FROM staged_records WHERE execution_id=?",
        (prepared["executionId"],),
    ).fetchone()[0] == 0
    assert workspace.state.execute(
        "SELECT count(*) FROM frontier WHERE execution_id=?",
        (prepared["executionId"],),
    ).fetchone()[0] == 0
    assert workspace.state.execute(
        "SELECT count(*) FROM visited WHERE execution_id=? AND status='queued'",
        (prepared["executionId"],),
    ).fetchone()[0] == 0


def test_prune_dry_run_and_apply_preserve_current_files(workspace):
    dataset, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    root = workspace.path / "datasets" / dataset["datasetId"]
    orphan = root / "data" / "orphan.parquet"
    orphan.write_bytes(b"not referenced")

    preview = workspace.datasets.prune(
        dataset["datasetId"], keep_snapshots=1, dry_run=True
    )
    assert "data/orphan.parquet" in preview["filesDeleted"]
    assert orphan.exists()
    applied = workspace.datasets.prune(
        dataset["datasetId"], keep_snapshots=1, dry_run=False
    )
    assert applied["bytesReclaimed"] == len(b"not referenced")
    assert not orphan.exists()
    assert workspace.datasets.query(
        dataset["datasetId"], "SELECT count(*) FROM dataset"
    )["rows"] == [[1]]


def test_doctor_safe_repair_removes_only_abandoned_state(workspace):
    workspace.state.execute(
        "INSERT INTO maintenance_leases VALUES('old','owner',?,?)",
        (time.time() - 1, "2026-01-01T00:00:00+00:00"),
    )
    temporary = workspace.path / "jobs" / ".abandoned.tmp"
    temporary.write_text("partial", encoding="utf-8")
    report = workspace.maintenance.doctor()
    assert len(report["warnings"]) == 2
    repaired = workspace.maintenance.doctor(repair_safe=True)
    assert "expired maintenance leases" in repaired["repaired"]
    assert "abandoned temporary files" in repaired["repaired"]
    assert not temporary.exists()


def test_doctor_repairs_unreferenced_dataset_files(workspace):
    dataset, _ = add_job(workspace)
    orphan = (
        workspace.path
        / "datasets"
        / dataset["datasetId"]
        / "data"
        / "orphan.parquet"
    )
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"orphan")
    report = workspace.maintenance.doctor()
    assert "1 unreferenced dataset file(s)" in report["warnings"]
    repaired = workspace.maintenance.doctor(repair_safe=True)
    assert "unreferenced dataset files" in repaired["repaired"]
    assert not orphan.exists()


def test_readiness_detects_catalog_file_drift(workspace):
    dataset, _ = add_job(workspace)
    path = workspace.path / "datasets" / dataset["datasetId"] / "dataset.json"
    altered = json.loads(path.read_text(encoding="utf-8"))
    altered["name"] = "tampered"
    path.write_text(json.dumps(altered), encoding="utf-8")
    validation = workspace.validate()
    assert validation["valid"] is False
    assert "differs from SQLite" in " ".join(validation["errors"])
    health = workspace.health(readiness=True)
    assert health["healthy"] is False and health["ready"] is False


def test_validation_reports_catalog_read_failures(workspace, monkeypatch):
    def fail(label):
        def broken(*_args, **_kwargs):
            raise RuntimeError(label)

        return broken

    monkeypatch.setattr(workspace.authoring, "list_drafts", fail("draft failure"))
    monkeypatch.setattr(workspace.datasets, "list", fail("dataset failure"))
    monkeypatch.setattr(workspace.jobs, "list", fail("job failure"))
    monkeypatch.setattr(workspace.executions, "list", fail("execution failure"))
    result = workspace.validate()
    assert result["valid"] is False
    assert {item.split(":", 1)[0] for item in result["errors"]} == {
        "template drafts",
        "dataset catalog",
        "job catalog",
        "execution catalog",
    }


def test_validation_reports_invalid_job_and_missing_mirror(workspace):
    _, job = add_job(workspace)
    altered = dict(job)
    altered["scope"] = {**altered["scope"], "maxDepth": 101}
    workspace.state.execute(
        "UPDATE jobs SET definition_json=? WHERE job_id=?",
        (json.dumps(altered), job["jobId"]),
    )
    (workspace.path / "jobs" / f"{job['jobId']}.json").unlink()
    result = workspace.validate()
    assert result["valid"] is False
    combined = " ".join(result["errors"])
    assert "max_depth" in combined
    assert "job" in combined and "file" in combined


@pytest.mark.parametrize("version", [None, 999])
def test_workspace_rejects_invalid_metadata_versions(tmp_path, version):
    root = tmp_path / f"invalid-{version}"
    root.mkdir()
    config = {"name": "invalid"}
    if version is not None:
        config["workspaceVersion"] = version
    (root / "pulsecrawl.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(RuntimeError, match="workspace"):
        Workspace(root)


def test_duckdb_query_sandbox_and_deadline(workspace):
    dataset, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    with pytest.raises(Exception, match="external|permission|allowed|disabled"):
        workspace.datasets.query(
            dataset["datasetId"], "SELECT * FROM read_csv_auto('/etc/passwd')"
        )
    with pytest.raises(Exception):
        workspace.datasets.query(
            dataset["datasetId"],
            "SELECT sum(i) FROM range(1000000000000) t(i)",
            timeout_s=0.001,
        )


def test_scheduler_failure_isolation_and_shutdown_state(workspace):
    _, failing = add_job(workspace, "a-failing", "bad.example")
    _, healthy = add_job(workspace, "b-healthy", "good.example")
    workspace.schedules.set(failing["jobId"], "0 * * * *")
    workspace.schedules.set(healthy["jobId"], "0 * * * *")
    workspace.state.execute(
        "UPDATE schedules SET next_run_at='2020-01-01T00:00:00+00:00'"
    )
    results = run_due(workspace, fetcher=Fetcher(failing_host="bad.example"))
    assert [item["jobId"] for item in results] == [healthy["jobId"]]
    schedules = {item["jobId"]: item for item in workspace.schedules.list()}
    assert schedules[failing["jobId"]]["failureCount"] == 1
    assert "deliberate schedule failure" in schedules[failing["jobId"]]["lastError"]

    stopping = threading.Event()
    stopping.set()
    workspace.schedules.serve(poll_seconds=0.01, shutdown_event=stopping)
    assert workspace.schedules.status()["stopping"] is True


def test_only_one_scheduler_process_can_own_workspace(workspace):
    stopping = threading.Event()
    failures = []

    def run_first():
        try:
            with Workspace(workspace.path) as other:
                other.schedules.serve(poll_seconds=0.05, shutdown_event=stopping)
        except BaseException as exc:  # capture assertions from the worker thread
            failures.append(exc)

    thread = threading.Thread(target=run_first)
    thread.start()
    deadline = time.time() + 5
    while not workspace.schedules.status()["ownerToken"] and time.time() < deadline:
        time.sleep(0.01)
    assert workspace.schedules.status()["ownerToken"]
    with Workspace(workspace.path) as contender:
        with pytest.raises(WorkspaceBusyError, match="scheduler"):
            contender.schedules.serve(
                poll_seconds=0.05, shutdown_event=threading.Event()
            )
    stopping.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert failures == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal lifecycle test")
def test_scheduler_process_exits_cleanly_on_sigterm(workspace):
    script = """
import sys
from pulsecrawl import Workspace
with Workspace(sys.argv[1]) as workspace:
    workspace.schedules.serve(poll_seconds=0.05)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(workspace.path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.time() + 5
    while not workspace.schedules.status()["ownerToken"] and time.time() < deadline:
        time.sleep(0.01)
    assert workspace.schedules.status()["ownerToken"]
    process.terminate()
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, (stdout, stderr)
    assert workspace.schedules.status()["stopping"] is True


def test_atomic_json_maps_out_of_space_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / "state.json"

    def no_space(_source, _destination):
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr("pulsecrawl.local_dataset.os.replace", no_space)
    with pytest.raises(InsufficientStorageError, match="insufficient space"):
        _atomic_json(target, {"safe": True})
    assert list(tmp_path.iterdir()) == []


def test_atomic_json_maps_read_only_filesystem(tmp_path, monkeypatch):
    def read_only(_source, _destination):
        raise OSError(errno.EROFS, "read only")

    monkeypatch.setattr("pulsecrawl.local_dataset.os.replace", read_only)
    with pytest.raises(WorkspaceReadOnlyError, match="not writable"):
        _atomic_json(tmp_path / "state.json", {"safe": True})


@pytest.mark.parametrize(
    "scope,politeness,match",
    [
        ({"maxDepth": 101}, None, "maxDepth"),
        ({"maxUrlsPerExecution": 1_000_001}, None, "maxUrlsPerExecution"),
        (None, {"requestsPerSecond": float("nan")}, "finite"),
        (None, {"requestsPerSecond": float("inf")}, "finite"),
        (None, {"userAgent": "x" * 513}, "userAgent"),
    ],
)
def test_workspace_rejects_unbounded_job_inputs(workspace, scope, politeness, match):
    dataset = workspace.datasets.create("bounded", fields=FIELDS)
    with pytest.raises(ValueError, match=match):
        workspace.jobs.create(
            "bad",
            seeds=["https://bounded.example/"],
            dataset_id=dataset["datasetId"],
            templates=[{"engine": "css", "mappings": {"fld_title": "h1"}}],
            scope=scope,
            politeness=politeness,
        )


def test_cli_returns_stable_json_errors(tmp_path, capsys):
    code = main(["--workspace", str(tmp_path / "missing"), "validate"])
    assert code == 3
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["code"] == "not_found"
    assert error["type"] == "FileNotFoundError"
    assert main(["not-a-command"]) == 2
    usage = json.loads(capsys.readouterr().err)["error"]
    assert usage["code"] == "usage"


def test_cli_can_create_complete_local_resource_graph(tmp_path, capsys):
    root = tmp_path / "cli-resources"
    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    prefix = ["--workspace", str(root)]
    assert main(prefix + ["field", "create", "title", "string", "--id", "fld_title"]) == 0
    capsys.readouterr()
    assert main(prefix + ["schema", "create", "article", "fld_title", "--id", "schema_article"]) == 0
    capsys.readouterr()
    assert main(prefix + [
        "template", "create", "article", "--schema-id", "schema_article",
        "--engine", "css", "--mappings", '{"fld_title":"h1"}',
        "--id", "tmpl_article",
    ]) == 0
    capsys.readouterr()
    assert main(prefix + [
        "dataset", "create", "articles", "--schema-id", "schema_article"
    ]) == 0
    dataset = json.loads(capsys.readouterr().out)
    assert main(prefix + [
        "job", "create", "news", "--dataset-id", dataset["datasetId"],
        "--seed", "https://example.com/", "--templates",
        '[{"templateId":"tmpl_article"}]', "--politeness",
        '{"respectRobotsTxt":false}',
    ]) == 0
    job = json.loads(capsys.readouterr().out)
    assert job["templates"][0]["templateId"] == "tmpl_article"
    show_commands = [
        (["field", "show", "fld_title"], "fieldId", "fld_title"),
        (["schema", "show", "schema_article"], "schemaId", "schema_article"),
        (["template", "show", "tmpl_article"], "templateId", "tmpl_article"),
        (["dataset", "show", dataset["datasetId"]], "datasetId", dataset["datasetId"]),
        (["job", "show", job["jobId"]], "jobId", job["jobId"]),
    ]
    for command, key, expected in show_commands:
        assert main(prefix + command) == 0
        assert json.loads(capsys.readouterr().out)[key] == expected


def test_cli_maintenance_status_and_read_commands(workspace, tmp_path, capsys):
    dataset, job = add_job(workspace)
    prepared = workspace.jobs.prepare(job["jobId"])
    prefix = ["--workspace", str(workspace.path)]
    commands = [
        ["health", "--readiness"],
        ["doctor"],
        ["field", "list"],
        ["schema", "list"],
        ["template", "list"],
        ["execution", "show", prepared["executionId"]],
        ["execution", "cancel", prepared["executionId"], "--force"],
        ["dataset", "prune", dataset["datasetId"], "--keep-snapshots", "1"],
        ["schedule", "set", job["jobId"], "0 * * * *"],
        ["schedule", "status"],
    ]
    for command in commands:
        assert main(prefix + command) == 0
        assert json.loads(capsys.readouterr().out)

    backup = tmp_path / "cli-backup"
    assert main(prefix + ["backup", "create", str(backup), "--exclude-raw-pages"]) == 0
    capsys.readouterr()
    assert main(["backup", "verify", str(backup)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    restored = tmp_path / "cli-restored"
    assert main(["backup", "restore", str(backup), str(restored)]) == 0
    assert json.loads(capsys.readouterr().out)["restoredTo"] == str(restored)


def test_cli_json_file_input_and_invalid_type(tmp_path, capsys):
    root = tmp_path / "json-cli"
    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    fields = tmp_path / "fields.json"
    fields.write_text(json.dumps(FIELDS), encoding="utf-8")
    prefix = ["--workspace", str(root)]
    assert main(prefix + [
        "dataset", "create", "from-file", "--fields", f"@{fields}"
    ]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "from-file"
    assert main(prefix + [
        "dataset", "create", "bad", "--fields", '{"not":"a list"}'
    ]) == 4
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "invalid_input"
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="1 MiB"):
        _json_argument(f"@{oversized}", expected=dict)
    with pytest.raises(ValueError, match="1 MiB"):
        _json_argument('"' + "x" * (1024 * 1024) + '"', expected=str)


def test_structured_logging_redacts_secrets_and_url_queries(caplog):
    logger = logging.getLogger("pulsecrawl.test")
    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(
            logger,
            "request_failed",
            url="https://user:pass@example.com/path?access_token=secret#fragment",
            authorization="Bearer secret",
            nested={"api_key": "secret", "safe": "visible"},
            values=[None, 3, object()],
            ipv6="https://[2001:db8::1]:8443/path?secret=yes",
            malformed="http://example.com:not-a-port/path",
            long_value="x" * 1001,
        )
    payload = json.loads(caplog.records[-1].message)
    assert payload["url"] == "https://example.com/path"
    assert payload["authorization"] == "[REDACTED]"
    assert payload["nested"] == {"api_key": "[REDACTED]", "safe": "visible"}
    assert payload["ipv6"] == "https://[2001:db8::1]:8443/path"
    assert payload["long_value"].endswith("...")


def test_url_identity_fuzz_is_total_and_idempotent():
    generator = random.Random(20261001)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789:/?#[]@!$&'()*+,;=% \x00"
    for _ in range(2_000):
        candidate = "".join(
            generator.choice(alphabet) for _ in range(generator.randrange(0, 256))
        )
        normalized = normalize_url_identity(candidate)
        assert normalized is None or normalize_url_identity(normalized) == normalized


def test_identifier_path_traversal_is_rejected(workspace):
    with pytest.raises(ValueError, match="safe characters"):
        workspace.fields.create("escape", "string", field_id="../../outside")
    assert not (workspace.path.parent / "outside.json").exists()
