#!/usr/bin/env python3
"""Deterministic local-workspace load gate; performs no external network I/O."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from pulsecrawl import Workspace
from pulsecrawl.core.model import FetchResult
from pulsecrawl.workspace_maintenance import WorkspaceMaintenance


def _payload(url: str, payload_bytes: int) -> str:
    return f"{url}|" + ("x" * payload_bytes)


class GeneratedFetcher:
    def __init__(self, payload_bytes: int = 0) -> None:
        self.payload_bytes = payload_bytes

    async def fetch(self, url: str, *, user_agent: str) -> FetchResult:
        payload = _payload(url, self.payload_bytes)
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            headers={"Content-Type": "text/html"},
            body=f'<h1>{url}</h1><p class="payload">{payload}</p>',
            error=None,
            fetched_at=datetime.now(timezone.utc),
        )


def _peak_rss_mib() -> float | None:
    """Return peak resident memory, including PyArrow and DuckDB allocations."""
    try:
        import resource

        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return round(value / divisor, 2)
    except (ImportError, OSError, ValueError):  # pragma: no cover - OS fallback
        return None


def _record_line(values: list[object]) -> bytes:
    return (json.dumps(values, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _validate_records(
    workspace: Workspace,
    dataset_id: str,
    execution_ids: list[str],
    expected_urls: list[str],
    payload_bytes: int,
) -> dict[str, object]:
    """Prove exact record presence, uniqueness, values, and ledger coverage."""
    actual_digest = hashlib.sha256()
    expected_digest = hashlib.sha256()
    missing = 0
    unexpected = 0
    duplicates = 0
    field_mismatches = 0
    actual_rows = 0
    expected_set = set(expected_urls)
    for execution_id in execution_ids:
        result = workspace.datasets.query(
            dataset_id,
            "SELECT _execution_id,_source_url,title,payload FROM dataset "
            f"WHERE _execution_id='{execution_id}' ORDER BY _source_url",
            row_cap=max(len(expected_urls), 1),
            timeout_s=120,
        )
        rows = result["rows"]
        actual_rows += len(rows)
        seen: set[str] = set()
        for row in rows:
            source_url = str(row[1])
            values = [str(row[0]), source_url, str(row[2]), str(row[3])]
            actual_digest.update(_record_line(values))
            seen.add(source_url)
            if source_url not in expected_set:
                unexpected += 1
            if (
                values[0] != execution_id
                or values[2] != source_url
                or values[3] != _payload(source_url, payload_bytes)
            ):
                field_mismatches += 1
        missing += len(expected_set - seen)
        duplicates += max(len(rows) - len(seen), 0)
        for url in sorted(expected_urls):
            expected_digest.update(
                _record_line(
                    [execution_id, url, url, _payload(url, payload_bytes)]
                )
            )

    grouped = workspace.datasets.query(
        dataset_id,
        "SELECT _execution_id,count(*) AS rows,count(DISTINCT _source_url) "
        "AS distinct_urls FROM dataset GROUP BY _execution_id ORDER BY _execution_id",
        row_cap=max(len(execution_ids), 1),
        timeout_s=120,
    )
    groups = {str(row[0]): (int(row[1]), int(row[2])) for row in grouped["rows"]}
    groups_complete = groups == {
        execution_id: (len(expected_urls), len(expected_urls))
        for execution_id in execution_ids
    }

    ledger_rows: list[dict[str, object]] = []
    cursor = None
    while True:
        page = workspace.datasets.urls(dataset_id, cursor=cursor, limit=500)
        ledger_rows.extend(page["urls"])
        cursor = page["nextCursor"]
        if cursor is None:
            break
    ledger_by_url = {str(item["url"]): item for item in ledger_rows}
    ledger_complete = (
        set(ledger_by_url) == expected_set
        and len(ledger_rows) == len(expected_set)
        and all(
            int(item["executionCount"]) == len(execution_ids)
            and int(item["seenCount"]) == len(execution_ids)
            for item in ledger_rows
        )
    )

    expected_rows = len(expected_urls) * len(execution_ids)
    cap = min(max(expected_rows - 1, 1), 1_000)
    capped = workspace.datasets.query(
        dataset_id,
        "SELECT _execution_id,_source_url FROM dataset",
        row_cap=cap,
        timeout_s=120,
    )
    row_cap_enforced = len(capped["rows"]) == cap and (
        bool(capped["truncated"]) == (expected_rows > cap)
    )
    expected_hex = expected_digest.hexdigest()
    actual_hex = actual_digest.hexdigest()
    complete = (
        actual_rows == expected_rows
        and missing == 0
        and unexpected == 0
        and duplicates == 0
        and field_mismatches == 0
        and actual_hex == expected_hex
        and groups_complete
        and ledger_complete
        and row_cap_enforced
    )
    return {
        "complete": complete,
        "actualRows": actual_rows,
        "expectedRows": expected_rows,
        "missingRows": missing,
        "unexpectedRows": unexpected,
        "duplicateRows": duplicates,
        "fieldMismatches": field_mismatches,
        "actualSha256": actual_hex,
        "expectedSha256": expected_hex,
        "digestMatches": actual_hex == expected_hex,
        "executionGroupsComplete": groups_complete,
        "ledgerComplete": ledger_complete,
        "rowCapEnforced": row_cap_enforced,
    }


def run(
    root: Path,
    pages: int,
    executions: int = 1,
    *,
    payload_bytes: int = 0,
    verify_backup: bool = False,
) -> dict[str, object]:
    started = time.perf_counter()
    tracemalloc.start()
    with Workspace.init(root, name="soak") as workspace:
        dataset = workspace.datasets.create(
            "pages",
            fields=[
                {"fieldId": "fld_title", "name": "title", "type": "string"},
                {"fieldId": "fld_payload", "name": "payload", "type": "string"},
            ],
        )
        job = workspace.jobs.create(
            "soak",
            seeds=[f"https://host-{index}.example/" for index in range(pages)],
            dataset_id=dataset["datasetId"],
            templates=[{
                "engine": "css",
                "mappings": {"fld_title": "h1", "fld_payload": ".payload"},
            }],
            scope={
                "sameDomainOnly": False,
                "maxDepth": 0,
                "maxUrlsPerExecution": pages,
                "maxUrlsTotal": pages * executions,
            },
            politeness={"respectRobotsTxt": False, "requestsPerSecond": 1000},
        )
        dataset_id = dataset["datasetId"]
        job_id = job["jobId"]
    statuses = []
    execution_ids = []
    expected_urls = [f"https://host-{index}.example/" for index in range(pages)]
    # Reopen between every execution. This makes the load gate exercise the
    # same durable restart path used by the standalone scheduler.
    for _ in range(executions):
        with Workspace(root) as workspace:
            execution = workspace.jobs.run(
                job_id, fetcher=GeneratedFetcher(payload_bytes)
            )
            statuses.append(execution["status"])
            execution_ids.append(execution["executionId"])
    with Workspace(root) as workspace:
        before = _validate_records(
            workspace,
            dataset_id,
            execution_ids,
            expected_urls,
            payload_bytes,
        )
        compacted = workspace.datasets.compact(dataset_id, minimum_files=2)
        pruning = workspace.datasets.prune(
            dataset_id,
            keep_snapshots=2,
            dry_run=False,
        )
    with Workspace(root) as reopened:
        after = _validate_records(
            reopened,
            dataset_id,
            execution_ids,
            expected_urls,
            payload_bytes,
        )
        validation = reopened.validate()
    backup_report = None
    if verify_backup:
        backup = root.parent / f"{root.name}-backup"
        restored_root = root.parent / f"{root.name}-restored"
        with Workspace(root) as workspace:
            workspace.maintenance.backup(backup, include_raw_pages=False)
        WorkspaceMaintenance.restore(backup, restored_root)
        with Workspace(restored_root) as restored:
            restored_records = _validate_records(
                restored,
                dataset_id,
                execution_ids,
                expected_urls,
                payload_bytes,
            )
            restored_validation = restored.validate()
        backup_report = {
            "complete": bool(restored_records["complete"])
            and bool(restored_validation["valid"]),
            "recordValidation": restored_records,
            "workspaceValid": restored_validation["valid"],
        }
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "pages": pages,
        "executions": executions,
        "expectedRows": pages * executions,
        "rows": before["actualRows"],
        "reopenedRows": after["actualRows"],
        "allExecutionsSucceeded": all(
            status == "succeeded" for status in statuses
        ),
        "succeededExecutions": statuses.count("succeeded"),
        "payloadBytes": payload_bytes,
        "beforeCompaction": before,
        "afterCompaction": after,
        "backupRestore": backup_report,
        "partitionsCompacted": compacted,
        "snapshotsDeleted": len(pruning["snapshotsDeleted"]),
        "valid": validation["valid"],
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "pythonPeakMiB": round(peak / (1024 * 1024), 2),
        "processPeakRssMiB": _peak_rss_mib(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=1_000)
    parser.add_argument("--executions", type=int, default=1)
    parser.add_argument("--payload-bytes", type=int, default=0)
    parser.add_argument("--verify-backup", action="store_true")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--max-seconds", type=float, default=120.0)
    parser.add_argument("--max-python-peak-mib", type=float, default=512.0)
    parser.add_argument("--max-rss-mib", type=float, default=1024.0)
    args = parser.parse_args()
    if not 1 <= args.pages <= 10_000:
        parser.error("--pages must be between 1 and 10000")
    if not 1 <= args.executions <= 100:
        parser.error("--executions must be between 1 and 100")
    if not 0 <= args.payload_bytes <= 1024 * 1024:
        parser.error("--payload-bytes must be between 0 and 1048576")
    if args.workspace:
        args.workspace.mkdir(parents=True, exist_ok=False)
        report = run(
            args.workspace.resolve(),
            args.pages,
            args.executions,
            payload_bytes=args.payload_bytes,
            verify_backup=args.verify_backup,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="pulsecrawl-soak-") as temporary:
            report = run(
                Path(temporary) / "workspace",
                args.pages,
                args.executions,
                payload_bytes=args.payload_bytes,
                verify_backup=args.verify_backup,
            )
    print(json.dumps(report, sort_keys=True))
    return int(
        not report["allExecutionsSucceeded"]
        or not report["valid"]
        or report["rows"] != report["expectedRows"]
        or report["reopenedRows"] != report["expectedRows"]
        or not report["beforeCompaction"]["complete"]
        or not report["afterCompaction"]["complete"]
        or (
            report["backupRestore"] is not None
            and not report["backupRestore"]["complete"]
        )
        or report["elapsedSeconds"] > args.max_seconds
        or report["pythonPeakMiB"] > args.max_python_peak_mib
        or (
            report["processPeakRssMiB"] is not None
            and report["processPeakRssMiB"] > args.max_rss_mib
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
