"""Version manifests, legacy workspace reads, and mixed-layout retention."""
import json
from pathlib import Path

import pytest

from pulsecrawl.cli import main
from pulsecrawl.errors import DatasetCorruptionError
from pulsecrawl.local_dataset import LocalDatasetReader
from test_workspace_runtime import FakeFetcher, make_dataset, make_job, workspace  # noqa: F401


def _run(workspace, job, title="one"):
    return workspace.jobs.run(
        job["jobId"],
        fetcher=FakeFetcher({"https://a.example/": f"<h1>{title}</h1>"}),
    )


def _legacy_pointer(root):
    """Represent a pre-rename workspace without changing its dataset data."""
    pointer_path = root / "manifests" / "current.json"
    pointer = json.loads(pointer_path.read_text())
    original = root / pointer.pop("manifest")
    legacy = root / "manifests" / "snapshots" / original.name
    legacy.parent.mkdir(parents=True, exist_ok=True)
    original.rename(legacy)
    pointer["snapshot"] = legacy.relative_to(root).as_posix()
    pointer_path.write_text(json.dumps(pointer))
    return legacy


def test_new_publication_uses_versions_directory_and_manifest_pointer(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    _run(workspace, job)
    root = workspace.path / "datasets" / dataset["datasetId"]
    pointer = json.loads((root / "manifests" / "current.json").read_text())
    assert "snapshot" not in pointer
    assert Path(pointer["manifest"]).parent.as_posix() == "manifests/versions"
    assert not (root / "manifests" / "snapshots").exists()
    assert workspace.datasets.query(dataset["datasetId"], "SELECT count(*) FROM dataset")["rows"] == [[1]]


def test_legacy_workspace_can_publish_new_versions_and_read_history(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    _run(workspace, job)
    root = workspace.path / "datasets" / dataset["datasetId"]
    legacy = _legacy_pointer(root)
    assert workspace.datasets.query(dataset["datasetId"], "SELECT count(*) FROM dataset")["rows"] == [[1]]
    _run(workspace, job, "two")
    assert legacy.exists()
    pointer = json.loads((root / "manifests" / "current.json").read_text())
    assert pointer["version"] == 2
    assert pointer["manifest"].startswith("manifests/versions/")
    assert "snapshot" not in pointer
    assert workspace.datasets.query(dataset["datasetId"], "SELECT count(*) FROM dataset", version=1)["rows"] == [[1]]
    assert workspace.datasets.query(dataset["datasetId"], "SELECT count(*) FROM dataset", version=2)["rows"] == [[2]]
    assert workspace.maintenance.doctor(repair_safe=True)["valid"]
    assert workspace.validate()["valid"]


def test_compaction_retention_and_repair_preserve_mixed_layout_history(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    _run(workspace, job)
    root = workspace.path / "datasets" / dataset["datasetId"]
    legacy = _legacy_pointer(root)
    _run(workspace, job, "two")
    files_before = workspace.datasets.files(dataset["datasetId"])
    # Keep both executions in one physical partition even across an hour boundary.
    manifests = LocalDatasetReader(workspace.state, workspace.path, dataset).manifests
    current = manifests.current()
    for item in current["files"]:
        item["ingestDate"] = files_before[0]["ingestDate"]
        item["ingestHour"] = files_before[0]["ingestHour"]
    manifests.publish(current["files"], change_id="test-partition")
    assert workspace.datasets.compact(dataset["datasetId"]) == 1
    assert workspace.maintenance.doctor(repair_safe=True)["valid"]
    assert all((root / item["path"]).exists() for item in files_before)
    assert workspace.datasets.query(dataset["datasetId"], "SELECT count(*) FROM dataset", version=1)["rows"] == [[1]]
    preview = workspace.datasets.prune(dataset["datasetId"], keep_versions=1)
    assert legacy.relative_to(root).as_posix() in preview["versionsDeleted"]
    assert legacy.exists()
    report = workspace.datasets.prune(dataset["datasetId"], keep_versions=1, dry_run=False)
    assert report["versionsDeleted"] == preview["versionsDeleted"]
    assert not legacy.exists()
    assert all(not (root / item["path"]).exists() for item in files_before)
    assert workspace.datasets.query(dataset["datasetId"], "SELECT count(*) FROM dataset")["rows"] == [[2]]
    assert workspace.maintenance.doctor()["valid"]


@pytest.mark.parametrize("key", ["manifest", "snapshot"])
@pytest.mark.parametrize("relative", ["../outside.json", "manifests/current.json", "manifests/versions/nested/bad.json"])
def test_version_pointer_rejects_unsafe_paths(workspace, key, relative):
    dataset = make_dataset(workspace)
    root = workspace.path / "datasets" / dataset["datasetId"]
    pointer = root / "manifests" / "current.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"datasetId": dataset["datasetId"], "version": 1, key: relative}))
    with pytest.raises(DatasetCorruptionError):
        workspace.datasets.files(dataset["datasetId"])


def test_conflicting_pointer_names_fail_closed(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    _run(workspace, job)
    root = workspace.path / "datasets" / dataset["datasetId"]
    pointer_path = root / "manifests" / "current.json"
    pointer = json.loads(pointer_path.read_text())
    pointer["snapshot"] = "manifests/snapshots/other.json"
    pointer_path.write_text(json.dumps(pointer))
    with pytest.raises(DatasetCorruptionError, match="conflicting"):
        workspace.datasets.files(dataset["datasetId"])


def test_duplicate_version_across_layouts_is_rejected(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    _run(workspace, job)
    root = workspace.path / "datasets" / dataset["datasetId"]
    [version] = (root / "manifests" / "versions").glob("*.json")
    duplicate = root / "manifests" / "snapshots" / version.name
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(version.read_bytes())
    with pytest.raises(KeyError, match="ambiguous"):
        workspace.datasets.files(dataset["datasetId"], version=1)


@pytest.mark.parametrize("flag", ["--keep-versions", "--keep-snapshots"])
def test_version_retention_cli_and_legacy_alias(workspace, capsys, flag):
    dataset = make_dataset(workspace)
    assert main(["-w", str(workspace.path), "dataset", "prune", dataset["datasetId"], flag, "1"]) == 0
    assert json.loads(capsys.readouterr().out)["versionsDeleted"] == []


def test_version_retention_rejects_invalid_or_conflicting_counts(workspace):
    dataset = make_dataset(workspace)
    with pytest.raises(ValueError, match="at least 1"):
        workspace.datasets.prune(dataset["datasetId"], keep_versions=0)
    with pytest.raises(ValueError, match="disagree"):
        workspace.datasets.prune(dataset["datasetId"], keep_versions=1, keep_snapshots=2)
