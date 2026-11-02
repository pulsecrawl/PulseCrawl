"""Legacy names appear only here and in the upgrade that reads old databases."""

from contextlib import closing
import ast
from pathlib import Path
import sqlite3

import pytest

from pulsecrawl import Workspace
from pulsecrawl.adapters.outbound.sqlite.crawling import SQLitePendingUrls
from pulsecrawl.adapters.outbound.sqlite.state import SCHEMA_VERSION, SQLiteState
from pulsecrawl.domain.crawling.model import PendingUrl


def legacy_database(root, version=4):
    """Build the pre-rename storage layout, including deleted FIFO sequence IDs."""
    with Workspace.init(root) as workspace:
        dataset = workspace.datasets.create(
            "data", fields=[{"fieldId": "title", "name": "title", "type": "string"}]
        )
        job = workspace.jobs.create(
            "crawl",
            seeds=["https://example.com/"],
            dataset_id=dataset["datasetId"],
            templates=[{"engine": "css", "mappings": {"title": "h1"}}],
        )
        execution_id = workspace.jobs.prepare(job["jobId"])["executionId"]
        path = workspace.state.path
        with workspace.state.transaction() as db:
            for sequence, status, retry in ((7, "pending", 3), (9, "leased", 5)):
                db.execute(
                    "INSERT INTO pending_urls(sequence,execution_id,url_hash,url,depth,"
                    "not_before,rate_scheduled,rate_slot_expires_at,rate_interval_s,"
                    "state,lease_until,retry_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sequence, execution_id, f"hash-{sequence}",
                     f"https://example.com/{sequence}", 2, 100.0, 1, 120.0, 0.5,
                     status, 150.0 if status == "leased" else None, retry),
                )
            # AUTOINCREMENT must not reuse an ID removed before the upgrade.
            db.execute("UPDATE sqlite_sequence SET seq=40 WHERE name='pending_urls'")
            db.execute("DROP INDEX pending_urls_ready")
            if version < 3:
                db.execute("ALTER TABLE pending_urls DROP COLUMN retry_count")
            db.execute("ALTER TABLE pending_urls RENAME TO frontier")
            db.execute(
                "CREATE INDEX frontier_ready "
                "ON frontier(execution_id,state,not_before,sequence)"
            )
            db.execute(
                "UPDATE workspace_meta SET value=? WHERE key='schema_version'",
                (str(version),),
            )
            db.execute(f"PRAGMA user_version={version}")
            before = [dict(row) for row in db.execute("SELECT * FROM frontier")]
    return path, execution_id, before


@pytest.mark.parametrize("version", [1, 2, 3, 4])
async def test_upgrade_preserves_pending_urls_and_backup(tmp_path, version):
    root = tmp_path / "legacy"
    path, execution_id, before = legacy_database(root, version)
    with Workspace(root) as workspace:
        assert workspace.state.schema_version == SCHEMA_VERSION == 6
        assert workspace.state.execute("PRAGMA user_version").fetchone()[0] == 6
        after = [dict(row) for row in workspace.state.execute("SELECT * FROM pending_urls")]
        assert after == [dict(row, retry_count=row.get("retry_count", 0)) for row in before]
        names = {row[0] for row in workspace.state.execute("SELECT name FROM sqlite_master")}
        assert "pending_urls" in names and "pending_urls_ready" in names
        assert "frontier" not in names and "frontier_ready" not in names
        assert workspace.state.integrity_check() == ["ok"]
        assert workspace.state.execute("PRAGMA foreign_key_check").fetchall() == []

        queue = SQLitePendingUrls(workspace.state, execution_id)
        assert queue.pending_count() == 2
        assert await queue.pop_ready(99.0) is None
        assert (await queue.pop_ready(100.0)).url == "https://example.com/7"
        assert (await queue.pop_ready(150.0)).url == "https://example.com/9"
        await queue.push([PendingUrl("https://example.com/new", 0)])
        assert workspace.state.execute("SELECT max(sequence) FROM pending_urls").fetchone()[0] == 41

    backup = path.with_name(f"{path.name}.pre-migration-v{version}-to-v6.backup")
    with closing(sqlite3.connect(backup)) as db:
        db.row_factory = sqlite3.Row
        assert [dict(row) for row in db.execute("SELECT * FROM frontier")] == before
        assert db.execute("SELECT value FROM workspace_meta WHERE key='schema_version'").fetchone()[0] == str(version)

    # Reopening the upgraded workspace neither reruns nor duplicates the work.
    with Workspace(root) as reopened:
        assert SQLitePendingUrls(reopened.state, execution_id).pending_count() == 3


def test_conflicting_populated_queues_fail_without_data_loss(tmp_path):
    path, _, before = legacy_database(tmp_path / "conflict")
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE pending_urls AS SELECT * FROM frontier")
    with pytest.raises(RuntimeError, match="conflicting pending URL queues"):
        SQLiteState(path)
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        for table in ("frontier", "pending_urls"):
            assert [dict(row) for row in db.execute(f"SELECT * FROM {table}")] == before
        assert db.execute("SELECT value FROM workspace_meta WHERE key='schema_version'").fetchone()[0] == "4"


def test_failed_rename_rolls_back_old_queue_and_version(tmp_path):
    path, _, before = legacy_database(tmp_path / "rollback")

    class BrokenMigration(SQLiteState):
        def _migrate_v4_to_v5(self, db):
            super()._migrate_v4_to_v5(db)
            raise RuntimeError("rename failpoint")

    with pytest.raises(RuntimeError, match="rename failpoint"):
        BrokenMigration(path)
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        assert [dict(row) for row in db.execute("SELECT * FROM frontier")] == before
        assert db.execute("SELECT count(*) FROM pending_urls").fetchone()[0] == 0
        assert db.execute("SELECT value FROM workspace_meta WHERE key='schema_version'").fetchone()[0] == "4"
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4

    state = SQLiteState(path)
    try:
        assert state.schema_version == 6
        assert [dict(row) for row in state.execute("SELECT * FROM pending_urls")] == before
    finally:
        state.close()


def test_old_terminology_is_confined_to_database_upgrade_boundary():
    root = Path(__file__).resolve().parents[1]
    exceptions = {
        Path("src/pulsecrawl/adapters/outbound/sqlite/state.py"),
        Path("tests/test_pending_urls_migration.py"),
    }
    old_name = "front" + "ier"
    for directory in ("src", "tests", "examples", "docs", "scripts"):
        for path in (root / directory).rglob("*"):
            if path.suffix not in {".py", ".md"} or "__pycache__" in path.parts:
                continue
            if path.relative_to(root) in exceptions:
                continue
            assert old_name not in path.read_text(encoding="utf-8").casefold(), path
    for path in root.glob("*.md"):
        assert old_name not in path.read_text(encoding="utf-8").casefold(), path

    state_path = root / "src/pulsecrawl/adapters/outbound/sqlite/state.py"
    source = state_path.read_text(encoding="utf-8")
    migration = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_migrate_v4_to_v5"
    )
    outside_upgrade = source.replace(ast.get_source_segment(source, migration), "")
    assert old_name not in outside_upgrade.casefold()
