"""Cross-component failure, concurrency, corruption, and recovery scenarios."""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
import threading
from datetime import datetime, timezone

import pytest
from pulsecrawl.core.model import FetchResult

from pulsecrawl import Workspace
from pulsecrawl.cli import main
from pulsecrawl.errors import (
    DatasetCorruptionError,
    QueryTimeoutError,
    WorkspaceBusyError,
    WorkspaceError,
)
from pulsecrawl.local_dataset import LocalManifestStore
from pulsecrawl.local_dataset import LocalDatasetWriter
from pulsecrawl.local_scheduler import run_due
from pulsecrawl.workspace_maintenance import WorkspaceMaintenance


FIELDS = [
    {"fieldId": "fld_title", "name": "title", "type": "string"},
    {"fieldId": "fld_url", "name": "canonical", "type": "url"},
]


class Fetcher:
    def __init__(self, title="record"):
        self.title = title

    async def fetch(self, url, *, user_agent):
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            headers={"content-type": "text/html"},
            body=(
                f"<h1>{self.title}</h1>"
                f'<link rel="canonical" href="{url}">'
            ),
            error=None,
            fetched_at=datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc),
        )


class PausingFetcher(Fetcher):
    def __init__(self):
        super().__init__("graceful partial")
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch(self, url, *, user_agent):
        self.started.set()
        await self.release.wait()
        return await super().fetch(url, user_agent=user_agent)


@pytest.fixture
def workspace(tmp_path):
    value = Workspace.init(tmp_path / "workspace", name="failure-scenarios")
    yield value
    value.close()


def add_job(workspace, *, per_execution=3, total=10, store_raw_pages=False):
    dataset = workspace.datasets.create("data", fields=FIELDS)
    job = workspace.jobs.create(
        "job",
        seeds=["https://case.example/"],
        dataset_id=dataset["datasetId"],
        templates=[{
            "engine": "css",
            "mappings": {
                "fld_title": "h1",
                "fld_url": "link[rel=canonical]@href",
            },
        }],
        scope={
            "maxDepth": 1,
            "maxUrlsPerExecution": per_execution,
            "maxUrlsTotal": total,
        },
        politeness={"respectRobotsTxt": False, "requestsPerSecond": 1000},
        store_raw_pages=store_raw_pages,
    )
    return dataset, job


def test_concurrent_lifetime_budget_reservations_never_oversubscribe(workspace):
    _, job = add_job(workspace, per_execution=3, total=10)
    contenders = 12
    barrier = threading.Barrier(contenders)
    results: list[tuple[str, int | str]] = []
    result_lock = threading.Lock()

    def prepare(index):
        with Workspace(workspace.path) as contender:
            barrier.wait(timeout=10)
            try:
                execution = contender.jobs.prepare(
                    job["jobId"], execution_id=f"exec_budget_{index:02d}"
                )
                result = ("reserved", execution["reservedUrls"])
            except WorkspaceError as exc:
                result = ("rejected", str(exc))
        with result_lock:
            results.append(result)

    threads = [threading.Thread(target=prepare, args=(index,)) for index in range(contenders)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads)
    reservations = [int(value) for status, value in results if status == "reserved"]
    assert sorted(reservations) == [1, 3, 3, 3]
    assert len(results) == contenders
    budget = workspace.state.execute(
        "SELECT urls_used,urls_reserved FROM jobs WHERE job_id=?", (job["jobId"],)
    ).fetchone()
    assert tuple(budget) == (0, 10)
    assert workspace.state.execute(
        "SELECT sum(reserved_urls) FROM executions WHERE job_id=?", (job["jobId"],)
    ).fetchone()[0] == 10

    for execution in workspace.executions.list(job["jobId"]):
        workspace.executions.cancel(execution["executionId"], force=True)
    budget = workspace.state.execute(
        "SELECT urls_used,urls_reserved FROM jobs WHERE job_id=?", (job["jobId"],)
    ).fetchone()
    assert tuple(budget) == (0, 0)


def test_budget_settlement_uses_actual_attempts_and_releases_unused_reservation(workspace):
    _, job = add_job(workspace, per_execution=6, total=10)
    first = workspace.jobs.prepare(job["jobId"], execution_id="exec_first")
    second = workspace.jobs.prepare(job["jobId"], execution_id="exec_second")
    assert (first["reservedUrls"], second["reservedUrls"]) == (6, 4)

    completed = workspace.executions.resume(first["executionId"], fetcher=Fetcher())
    assert completed["stats"]["urls_attempted"] == 1
    budget = workspace.state.execute(
        "SELECT urls_used,urls_reserved FROM jobs WHERE job_id=?", (job["jobId"],)
    ).fetchone()
    assert tuple(budget) == (1, 4)
    third = workspace.jobs.prepare(job["jobId"], execution_id="exec_third")
    assert third["reservedUrls"] == 5
    with pytest.raises(WorkspaceError, match="maxUrlsTotal"):
        workspace.jobs.prepare(job["jobId"], execution_id="exec_rejected")


def test_live_execution_blocks_every_mutating_maintenance_path(workspace, tmp_path):
    dataset, job = add_job(workspace)
    prepared = workspace.jobs.prepare(job["jobId"])
    workspace.state.execute(
        "INSERT INTO execution_leases VALUES(?,?,?,?)",
        (prepared["executionId"], "live", 99999999999.0, 1.0),
    )

    with pytest.raises(WorkspaceBusyError, match="currently writing"):
        workspace.maintenance.backup(tmp_path / "blocked-backup")
    with pytest.raises(WorkspaceBusyError, match="currently writing"):
        workspace.datasets.prune(dataset["datasetId"], keep_snapshots=1, dry_run=False)
    assert not (tmp_path / "blocked-backup").exists()


def test_compaction_cas_preserves_delta_published_during_compaction(
    workspace, monkeypatch
):
    dataset, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher("first"))
    workspace.jobs.run(job["jobId"], fetcher=Fetcher("second"))
    original = LocalManifestStore.replace_files
    interleaved = False

    def publish_between_read_and_swap(store, remove, replacements, *, change_id):
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            workspace.jobs.run(job["jobId"], fetcher=Fetcher("interleaved"))
        return original(store, remove, replacements, change_id=change_id)

    monkeypatch.setattr(LocalManifestStore, "replace_files", publish_between_read_and_swap)
    assert workspace.datasets.compact(dataset["datasetId"]) == 1
    files = workspace.datasets.files(dataset["datasetId"])
    assert sorted(item["kind"] for item in files) == ["compact", "delta"]
    assert workspace.datasets.query(
        dataset["datasetId"], "SELECT title FROM dataset ORDER BY title"
    )["rows"] == [["first"], ["interleaved"], ["second"]]
    assert workspace.validate()["valid"] is True


@pytest.mark.parametrize("crash_point", ["before_execute", "after_execute"])
def test_scheduler_occurrence_is_exactly_once_across_process_loss(
    workspace, crash_point
):
    dataset, job = add_job(workspace)
    now = datetime.now(timezone.utc)
    workspace.schedules.set(job["jobId"], f"{now.minute} * * * *")
    scheduled_for = now.replace(second=0, microsecond=0).isoformat()
    workspace.state.execute(
        "UPDATE schedules SET next_run_at=? WHERE job_id=?",
        (scheduled_for, job["jobId"]),
    )
    original_run = workspace.jobs.run

    def crash(job_id, **kwargs):
        if crash_point == "before_execute":
            workspace.jobs.prepare(
                job_id,
                trigger=kwargs["trigger"],
                scheduled_for=kwargs["scheduled_for"],
                execution_id=kwargs["execution_id"],
            )
        else:
            original_run(job_id, **kwargs)
        raise SystemExit("simulated scheduler process loss")

    workspace.jobs.run = crash
    with pytest.raises(SystemExit, match="simulated"):
        run_due(workspace, fetcher=Fetcher())
    workspace.jobs.run = original_run

    assert workspace.state.execute(
        "SELECT claimed_at FROM schedules WHERE job_id=?", (job["jobId"],)
    ).fetchone()[0] is None
    [recovered] = run_due(workspace, fetcher=Fetcher())
    assert recovered["status"] == "succeeded"
    assert recovered["scheduledFor"] == scheduled_for
    assert workspace.state.execute(
        "SELECT count(*) FROM executions WHERE job_id=?", (job["jobId"],)
    ).fetchone()[0] == 1
    assert workspace.datasets.query(
        dataset["datasetId"], "SELECT count(*) FROM dataset"
    )["rows"] == [[1]]


def test_queued_and_terminal_cancellation_are_idempotent_and_release_budget(workspace):
    _, job = add_job(workspace, per_execution=3, total=3)
    queued = workspace.jobs.prepare(job["jobId"])
    cancelled = workspace.executions.cancel(queued["executionId"], force=False)
    assert cancelled["status"] == "cancelled"
    assert workspace.executions.cancel(queued["executionId"], force=True) == cancelled
    assert workspace.state.execute(
        "SELECT urls_used,urls_reserved FROM jobs WHERE job_id=?", (job["jobId"],)
    ).fetchone()[:] == (0, 0)

    completed = workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    assert workspace.executions.cancel(completed["executionId"])["status"] == "succeeded"
    assert workspace.state.execute(
        "SELECT urls_used,urls_reserved FROM jobs WHERE job_id=?", (job["jobId"],)
    ).fetchone()[:] == (1, 0)


@pytest.mark.asyncio
async def test_graceful_running_cancellation_publishes_completed_page_without_orphans(
    workspace,
):
    dataset, job = add_job(workspace)
    prepared = workspace.jobs.prepare(job["jobId"])
    fetcher = PausingFetcher()
    task = asyncio.create_task(
        workspace.executions._execute(prepared["executionId"], fetcher=fetcher)
    )
    await fetcher.started.wait()
    requested = workspace.executions.cancel(prepared["executionId"], force=False)
    assert requested["status"] == "cancelling"
    fetcher.release.set()
    result = await task

    assert result["status"] == "cancelled"
    assert result["cancellationMode"] == "graceful"
    assert result["stats"]["materializedRows"] == 1
    assert workspace.datasets.query(
        dataset["datasetId"], "SELECT title FROM dataset"
    )["rows"] == [["graceful partial"]]
    assert workspace.state.execute(
        "SELECT count(*) FROM staged_records WHERE execution_id=?",
        (prepared["executionId"],),
    ).fetchone()[0] == 0


def test_cancellation_during_output_commit_is_not_overwritten_by_success(
    workspace, monkeypatch
):
    dataset, job = add_job(workspace)
    prepared = workspace.jobs.prepare(job["jobId"])
    original = LocalDatasetWriter.finalize

    def cancel_at_commit(writer, *, completed_at=None):
        workspace.executions.cancel(writer.execution_id, force=False)
        return original(writer, completed_at=completed_at)

    monkeypatch.setattr(LocalDatasetWriter, "finalize", cancel_at_commit)
    result = workspace.executions.resume(prepared["executionId"], fetcher=Fetcher())
    assert result["status"] == "cancelled"
    assert result["stats"]["materializedRows"] == 1
    assert "after output commit" in result["error"]
    assert workspace.datasets.query(
        dataset["datasetId"], "SELECT count(*) FROM dataset"
    )["rows"] == [[1]]


def test_readiness_detects_corrupt_parquet_bytes(workspace):
    dataset, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    item = workspace.datasets.files(dataset["datasetId"])[0]
    path = workspace.path / "datasets" / dataset["datasetId"] / item["path"]
    path.write_bytes(b"not parquet")

    validation = workspace.validate()
    assert validation["valid"] is False
    assert "size mismatch" in " ".join(validation["errors"])
    assert workspace.health(readiness=True)["ready"] is False


@pytest.mark.parametrize("mutation", ["duplicate_path", "row_count", "size", "format"])
def test_manifest_semantic_corruption_is_detected(workspace, mutation):
    dataset, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    root = workspace.path / "datasets" / dataset["datasetId"]
    pointer = json.loads((root / "manifests" / "current.json").read_text())
    snapshot_path = root / pointer["manifest"]
    snapshot = json.loads(snapshot_path.read_text())
    if mutation == "duplicate_path":
        snapshot["files"].append(dict(snapshot["files"][0]))
    elif mutation == "row_count":
        snapshot["files"][0]["rows"] += 1
    elif mutation == "size":
        snapshot["files"][0]["sizeBytes"] += 1
    else:
        snapshot["schemaVersion"] = 999
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    assert workspace.validate()["valid"] is False
    with pytest.raises(DatasetCorruptionError):
        workspace.datasets.query(dataset["datasetId"], "SELECT * FROM dataset")


def test_historic_snapshot_cannot_claim_another_dataset(workspace):
    dataset, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    root = workspace.path / "datasets" / dataset["datasetId"]
    snapshot_path = next((root / "manifests" / "versions").glob("*.json"))
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["datasetId"] = "ds_other"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(DatasetCorruptionError, match="another dataset"):
        workspace.datasets.files(dataset["datasetId"], version=1)


def test_workspace_fails_closed_when_sqlite_file_is_not_a_database(tmp_path):
    root = tmp_path / "sqlite-corrupt"
    created = Workspace.init(root)
    created.close()
    (root / "state" / "pulsecrawl.sqlite").write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        Workspace(root)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "malformed", "duplicate", "traversal", "bad_format"],
)
def test_backup_corruption_matrix_fails_closed(workspace, tmp_path, mutation):
    _, job = add_job(workspace)
    workspace.jobs.run(job["jobId"], fetcher=Fetcher())
    original = tmp_path / "backup"
    workspace.maintenance.backup(original)
    damaged = tmp_path / f"backup-{mutation}"
    shutil.copytree(original, damaged)
    checksum_path = damaged / "checksums.sha256"
    lines = checksum_path.read_text(encoding="utf-8").splitlines()

    if mutation == "missing":
        relative = lines[0].partition("  ")[2]
        (damaged / relative).unlink()
    elif mutation == "extra":
        (damaged / "unlisted.txt").write_text("extra", encoding="utf-8")
    elif mutation == "malformed":
        checksum_path.write_text("not-a-checksum-line\n", encoding="utf-8")
    elif mutation == "duplicate":
        checksum_path.write_text("\n".join(lines + [lines[0]]) + "\n", encoding="utf-8")
    elif mutation == "traversal":
        digest = hashlib.sha256(b"outside").hexdigest()
        checksum_path.write_text(
            "\n".join(lines + [f"{digest}  ../outside"]) + "\n",
            encoding="utf-8",
        )
    else:
        metadata = damaged / "backup.json"
        value = json.loads(metadata.read_text())
        value["formatVersion"] = 999
        metadata.write_text(json.dumps(value), encoding="utf-8")
        replacement = []
        for line in lines:
            _, separator, relative = line.partition("  ")
            if relative == "backup.json":
                replacement.append(
                    f"{hashlib.sha256(metadata.read_bytes()).hexdigest()}{separator}{relative}"
                )
            else:
                replacement.append(line)
        checksum_path.write_text("\n".join(replacement) + "\n", encoding="utf-8")

    with pytest.raises(DatasetCorruptionError):
        WorkspaceMaintenance.verify_backup(damaged)


def test_query_cte_row_cap_and_conservative_statement_boundaries(workspace):
    dataset, job = add_job(workspace)
    for title in ("a", "b", "c"):
        workspace.jobs.run(job["jobId"], fetcher=Fetcher(title))
    result = workspace.datasets.query(
        dataset["datasetId"],
        "WITH ordered AS (SELECT title FROM dataset ORDER BY title) SELECT * FROM ordered",
        row_cap=2,
    )
    assert result == {"columns": ["title"], "rows": [["a"], ["b"]], "truncated": True}

    for statement in (
        "VACUUM",
        "CALL checkpoint()",
        "SET memory_limit='10GB'",
        "SELECT 1; -- hidden second statement",
        "/* comment */ COPY dataset TO '/tmp/leak.csv'",
    ):
        with pytest.raises(ValueError):
            workspace.datasets.query(dataset["datasetId"], statement)


def test_raw_page_snapshot_redacts_credentials_and_preserves_truncation(workspace):
    _, job = add_job(workspace, store_raw_pages=True)

    class SensitiveFetcher:
        async def fetch(self, url, *, user_agent):
            return FetchResult(
                url=url,
                final_url=url,
                status=200,
                headers={
                    "Authorization": "Bearer secret",
                    "Proxy-Authorization": "Basic secret",
                    "Cookie": "session=secret",
                    "Set-Cookie": "session=secret",
                    "X-Safe": "visible",
                },
                body="<h1>partial",
                error=None,
                fetched_at=datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc),
                body_truncated=True,
                body_bytes=11,
            )

    execution = workspace.jobs.run(job["jobId"], fetcher=SensitiveFetcher())
    [snapshot_path] = (
        workspace.path / "executions" / execution["executionId"] / "pages"
    ).glob("*.json")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["headers"] == {"X-Safe": "visible"}
    assert snapshot["bodyTruncated"] is True
    assert snapshot["bodyBytes"] == 11


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_exit"),
    [
        (WorkspaceBusyError("busy"), "workspace_error", 5),
        (QueryTimeoutError("slow"), "timeout", 6),
        (ImportError("optional package"), "missing_dependency", 7),
        (RuntimeError("unexpected"), "internal_error", 1),
    ],
)
def test_cli_all_runtime_error_classes_have_stable_machine_contracts(
    monkeypatch, capsys, error, expected_code, expected_exit
):
    def fail(_path):
        raise error

    monkeypatch.setattr("pulsecrawl.cli._workspace", fail)
    assert main(["--workspace", "unused", "validate"]) == expected_exit
    envelope = json.loads(capsys.readouterr().err)
    assert envelope == {
        "error": {
            "code": expected_code,
            "message": str(error),
            "type": type(error).__name__,
        }
    }


def test_cli_job_run_execution_resume_and_scheduler_start_validation(
    workspace, capsys
):
    dataset = workspace.datasets.create("cli runtime", fields=FIELDS)
    job = workspace.jobs.create(
        "cli runtime",
        seeds=["http://127.0.0.1:9/blocked-without-network"],
        dataset_id=dataset["datasetId"],
        templates=[{"engine": "css", "mappings": {"fld_title": "h1"}}],
        scope={"maxUrlsPerExecution": 2, "maxUrlsTotal": 10},
        politeness={"respectRobotsTxt": False, "requestsPerSecond": 1000},
    )
    prefix = ["--workspace", str(workspace.path)]

    assert main(prefix + ["job", "run", job["jobId"]]) == 0
    ran = json.loads(capsys.readouterr().out)
    assert ran["status"] == "succeeded"
    assert ran["stats"]["pages_failed"] == 1

    prepared = workspace.jobs.prepare(job["jobId"])
    assert main(prefix + ["execution", "resume", prepared["executionId"]]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["status"] == "succeeded"

    assert main(prefix + ["schedule", "start", "--poll-seconds", "0"]) == 4
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "invalid_input"
