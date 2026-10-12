"""Regression tests for the exact-record production soak validator."""
import importlib.util
from pathlib import Path

from pulsecrawl import Workspace


_TOOL_PATH = Path(__file__).parents[1] / "tools" / "soak_workspace.py"
_SPEC = importlib.util.spec_from_file_location("pulsecrawl_soak_workspace", _TOOL_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_TOOL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_TOOL)
_validate_records = _TOOL._validate_records
run = _TOOL.run


def test_soak_validates_all_records_before_after_compaction_and_restore(tmp_path):
    report = run(
        tmp_path / "complete",
        pages=12,
        executions=3,
        payload_bytes=128,
        verify_backup=True,
    )
    assert report["rows"] == report["expectedRows"] == 36
    assert report["beforeCompaction"]["complete"] is True
    assert report["afterCompaction"]["complete"] is True
    assert report["backupRestore"]["complete"] is True
    assert report["beforeCompaction"]["actualSha256"] == (
        report["afterCompaction"]["actualSha256"]
    )
    assert report["afterCompaction"]["actualSha256"] == (
        report["backupRestore"]["recordValidation"]["actualSha256"]
    )


def test_record_validator_detects_missing_and_unexpected_expectations(tmp_path):
    root = tmp_path / "missing"
    report = run(root, pages=8, executions=2)
    with Workspace(root) as workspace:
        dataset_id = workspace.datasets.list()[0]["datasetId"]
        execution_ids = [item["executionId"] for item in workspace.executions.list()]
        expected = [f"https://host-{index}.example/" for index in range(8)]
        validation = _validate_records(
            workspace,
            dataset_id,
            execution_ids,
            expected + ["https://missing.example/"],
            payload_bytes=0,
        )
    assert report["afterCompaction"]["complete"] is True
    assert validation["complete"] is False
    assert validation["missingRows"] == len(execution_ids)
    assert validation["digestMatches"] is False
    assert validation["ledgerComplete"] is False


def test_record_validator_detects_payload_corruption_or_mismatch(tmp_path):
    root = tmp_path / "payload"
    report = run(root, pages=10, executions=2, payload_bytes=256)
    with Workspace(root) as workspace:
        dataset_id = workspace.datasets.list()[0]["datasetId"]
        execution_ids = [item["executionId"] for item in workspace.executions.list()]
        expected = [f"https://host-{index}.example/" for index in range(10)]
        validation = _validate_records(
            workspace,
            dataset_id,
            execution_ids,
            expected,
            payload_bytes=255,
        )
    assert report["afterCompaction"]["complete"] is True
    assert validation["complete"] is False
    assert validation["fieldMismatches"] == 20
    assert validation["digestMatches"] is False
