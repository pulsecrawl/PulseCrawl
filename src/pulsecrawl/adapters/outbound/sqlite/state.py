"""Durable, single-machine adapters for an open-source PulseCrawl workspace.

SQLite is authoritative for operational state.  Python dictionaries may cache
reads, but a process restart must never lose a pending URL, URL admission,
schedule, rate-limit clock, or dataset identity observation.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator, Sequence


SCHEMA_VERSION = 5


class _SynchronizedCursor(sqlite3.Cursor):
    """Serialize statement stepping as well as execution on a shared connection.

    SQLite releases the GIL while fetching rows. Protecting only execute() lets
    another worker use the same connection while a cursor is still stepping.
    Keep reads lazy, but use the connection's lock for every cursor operation.
    """

    def __init__(self, connection, lock):
        super().__init__(connection)
        self._lock = lock

    def execute(self, *args, **kwargs):
        with self._lock:
            return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return super().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return super().executescript(*args, **kwargs)

    def fetchone(self):
        with self._lock:
            return super().fetchone()

    def fetchmany(self, *args, **kwargs):
        with self._lock:
            return super().fetchmany(*args, **kwargs)

    def fetchall(self):
        with self._lock:
            return super().fetchall()

    def __next__(self):
        with self._lock:
            return super().__next__()

    def close(self):
        with self._lock:
            return super().close()


class SQLiteState:
    """One WAL-mode database shared by local workers on the same machine."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._database_existed = self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            self.path,
            isolation_level=None,
            check_same_thread=False,
            timeout=30,
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=30000")
        if self._database_existed:
            meta_exists = self._db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_meta'"
            ).fetchone()
            if meta_exists is not None:
                row = self._db.execute(
                    "SELECT value FROM workspace_meta WHERE key='schema_version'"
                ).fetchone()
                if row is not None and int(row[0]) < SCHEMA_VERSION:
                    current = int(row[0])
                    backup = self.path.with_name(
                        f"{self.path.name}.pre-migration-v{current}"
                        f"-to-v{SCHEMA_VERSION}.backup"
                    )
                    if not backup.exists():
                        self.backup_to(backup)
        try:
            self._migrate()
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield self._db
            except BaseException:
                self._db.rollback()
                raise
            else:
                self._db.commit()

    def execute(self, sql: str, values: Sequence[object] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._db.cursor(
                factory=lambda connection: _SynchronizedCursor(connection, self._lock)
            )
            return cursor.execute(sql, values)

    def backup_to(self, destination: str | Path) -> Path:
        """Create a transactionally consistent SQLite backup."""
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"refusing to overwrite SQLite backup: {target}")
        with self._lock, closing(sqlite3.connect(target)) as backup:
            self._db.backup(backup)
        return target

    def integrity_check(self) -> list[str]:
        with self._lock:
            return [str(row[0]) for row in self._db.execute("PRAGMA integrity_check")]

    @property
    def schema_version(self) -> int:
        row = self.execute(
            "SELECT value FROM workspace_meta WHERE key='schema_version'"
        ).fetchone()
        return int(row["value"])

    @staticmethod
    def _has_column(db: sqlite3.Connection, table: str, column: str) -> bool:
        return any(
            row[1] == column for row in db.execute(f"PRAGMA table_info({table})")
        )

    def _migrate(self) -> None:
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspace_meta (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS datasets (
                  dataset_id TEXT PRIMARY KEY,
                  name TEXT NOT NULL UNIQUE,
                  definition_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                  job_id TEXT PRIMARY KEY,
                  name TEXT NOT NULL UNIQUE,
                  definition_json TEXT NOT NULL,
                  max_urls_total INTEGER NOT NULL,
                  urls_used INTEGER NOT NULL DEFAULT 0,
                  urls_reserved INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS executions (
                  execution_id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL REFERENCES jobs(job_id),
                  dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
                  status TEXT NOT NULL,
                  trigger TEXT NOT NULL,
                  scheduled_for TEXT,
                  intent_json TEXT NOT NULL,
                  stats_json TEXT,
                  error TEXT,
                  reserved_urls INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS executions_job_created
                  ON executions(job_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS execution_leases (
                  execution_id TEXT PRIMARY KEY REFERENCES executions(execution_id) ON DELETE CASCADE,
                  owner_token TEXT NOT NULL,
                  lease_until REAL NOT NULL,
                  heartbeat_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS visited (
                  execution_id TEXT NOT NULL REFERENCES executions(execution_id) ON DELETE CASCADE,
                  url_hash TEXT NOT NULL,
                  url TEXT NOT NULL,
                  status TEXT NOT NULL,
                  depth INTEGER NOT NULL,
                  error TEXT,
                  updated_at REAL NOT NULL,
                  PRIMARY KEY(execution_id, url_hash)
                );
                CREATE TABLE IF NOT EXISTS pending_urls (
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                  execution_id TEXT NOT NULL REFERENCES executions(execution_id) ON DELETE CASCADE,
                  url_hash TEXT NOT NULL,
                  url TEXT NOT NULL,
                  depth INTEGER NOT NULL,
                  not_before REAL NOT NULL,
                  rate_scheduled INTEGER NOT NULL,
                  rate_slot_expires_at REAL NOT NULL,
                  rate_interval_s REAL NOT NULL,
                  state TEXT NOT NULL DEFAULT 'pending',
                  lease_until REAL,
                  UNIQUE(execution_id, url_hash)
                );
                CREATE INDEX IF NOT EXISTS pending_urls_ready
                  ON pending_urls(execution_id, state, not_before, sequence);
                CREATE TABLE IF NOT EXISTS robots_cache (
                  origin TEXT PRIMARY KEY,
                  text TEXT NOT NULL,
                  fetched_at REAL NOT NULL,
                  fetch_failed INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gate_clocks (
                  lane TEXT NOT NULL,
                  org_id TEXT NOT NULL,
                  origin TEXT NOT NULL,
                  next_at REAL NOT NULL,
                  PRIMARY KEY(lane, org_id, origin)
                );
                CREATE TABLE IF NOT EXISTS url_ledger (
                  dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
                  identity TEXT NOT NULL,
                  source_url TEXT NOT NULL,
                  first_seen_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  first_execution_id TEXT NOT NULL,
                  last_execution_id TEXT NOT NULL,
                  seen_count INTEGER NOT NULL,
                  execution_count INTEGER NOT NULL,
                  PRIMARY KEY(dataset_id, identity)
                );
                CREATE INDEX IF NOT EXISTS url_ledger_last_seen
                  ON url_ledger(dataset_id, last_seen_at DESC, identity);
                CREATE TABLE IF NOT EXISTS url_observations (
                  dataset_id TEXT NOT NULL,
                  identity TEXT NOT NULL,
                  execution_id TEXT NOT NULL,
                  PRIMARY KEY(dataset_id, identity, execution_id),
                  FOREIGN KEY(dataset_id, identity)
                    REFERENCES url_ledger(dataset_id, identity) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS url_observation_rows (
                  dataset_id TEXT NOT NULL,
                  identity TEXT NOT NULL,
                  execution_id TEXT NOT NULL,
                  row_key TEXT NOT NULL,
                  PRIMARY KEY(dataset_id, identity, execution_id, row_key),
                  FOREIGN KEY(dataset_id, identity)
                    REFERENCES url_ledger(dataset_id, identity) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS staged_records (
                  execution_id TEXT NOT NULL REFERENCES executions(execution_id) ON DELETE CASCADE,
                  row_key TEXT NOT NULL,
                  row_json TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  PRIMARY KEY(execution_id, row_key)
                );
                CREATE TABLE IF NOT EXISTS schedules (
                  job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
                  cron TEXT NOT NULL,
                  timezone TEXT NOT NULL,
                  status TEXT NOT NULL,
                  next_run_at TEXT NOT NULL,
                  last_run_at TEXT,
                  claimed_at TEXT
                );
                """
            )
            row = db.execute(
                "SELECT value FROM workspace_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO workspace_meta(key,value) VALUES('schema_version',?)",
                    ("1",),
                )
                current = 1
            else:
                current = int(row["value"])

        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"workspace schema {current} is newer than supported schema "
                f"{SCHEMA_VERSION}"
            )
        while current < SCHEMA_VERSION:
            next_version = current + 1
            migration = getattr(self, f"_migrate_v{current}_to_v{next_version}")
            with self.transaction() as db:
                migration(db)
                db.execute(
                    "UPDATE workspace_meta SET value=? WHERE key='schema_version'",
                    (str(next_version),),
                )
                db.execute(f"PRAGMA user_version={next_version}")
            current = next_version

    def _migrate_v1_to_v2(self, db: sqlite3.Connection) -> None:
        if not self._has_column(db, "executions", "cancellation_requested_at"):
            db.execute(
                "ALTER TABLE executions ADD COLUMN cancellation_requested_at TEXT"
            )
        if not self._has_column(db, "executions", "cancellation_mode"):
            db.execute("ALTER TABLE executions ADD COLUMN cancellation_mode TEXT")
        if not self._has_column(db, "schedules", "claim_token"):
            db.execute("ALTER TABLE schedules ADD COLUMN claim_token TEXT")
        if not self._has_column(db, "schedules", "last_error"):
            db.execute("ALTER TABLE schedules ADD COLUMN last_error TEXT")
        if not self._has_column(db, "schedules", "failure_count"):
            db.execute(
                "ALTER TABLE schedules ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0"
            )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS maintenance_leases (
              name TEXT PRIMARY KEY,
              owner_token TEXT NOT NULL,
              lease_until REAL NOT NULL,
              acquired_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduler_state (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1),
              owner_token TEXT,
              heartbeat_at TEXT,
              stopping INTEGER NOT NULL DEFAULT 0,
              last_error TEXT
            )
            """
        )
        db.execute("INSERT OR IGNORE INTO scheduler_state(singleton) VALUES(1)")

    def _migrate_v2_to_v3(self, db: sqlite3.Connection) -> None:
        if not self._has_column(db, "pending_urls", "retry_count"):
            db.execute(
                "ALTER TABLE pending_urls ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0"
            )

    def _migrate_v3_to_v4(self, db: sqlite3.Connection) -> None:
        if not self._has_column(db, "scheduler_state", "lease_until"):
            db.execute("ALTER TABLE scheduler_state ADD COLUMN lease_until REAL")

    def _migrate_v4_to_v5(self, db: sqlite3.Connection) -> None:
        """Rename the legacy URL queue without losing work or FIFO sequence IDs.

        The base schema creates an empty new-name table before migrations run.
        Only that empty placeholder may be replaced; conflicting populated
        tables abort the migration and leave the legacy queue intact.
        """
        legacy = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='frontier'"
        ).fetchone()
        if legacy is not None:
            if db.execute("SELECT 1 FROM pending_urls LIMIT 1").fetchone():
                raise RuntimeError("cannot migrate conflicting pending URL queues")
            db.execute("DROP TABLE pending_urls")
            db.execute("ALTER TABLE frontier RENAME TO pending_urls")
            db.execute("DROP INDEX IF EXISTS frontier_ready")
        if not self._has_column(db, "pending_urls", "retry_count"):
            db.execute(
                "ALTER TABLE pending_urls ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0"
            )
        db.execute(
            "CREATE INDEX IF NOT EXISTS pending_urls_ready "
            "ON pending_urls(execution_id, state, not_before, sequence)"
        )
