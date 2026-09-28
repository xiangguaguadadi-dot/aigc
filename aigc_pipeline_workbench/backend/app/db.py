import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS services (
    service_id TEXT PRIMARY KEY,
    module_key TEXT NOT NULL,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    instance_label TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT,
    version TEXT,
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    gpu_json TEXT,
    registered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_checked_at TEXT,
    last_online_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    run_id TEXT,
    service_id TEXT NOT NULL,
    module_key TEXT NOT NULL,
    status TEXT NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    input_artifacts_json TEXT NOT NULL DEFAULT '[]',
    output_artifacts_json TEXT NOT NULL DEFAULT '[]',
    progress_json TEXT,
    error_json TEXT,
    rerun_of_job_id TEXT,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    last_synced_at TEXT,
    last_sync_error TEXT,
    consecutive_poll_failures INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS job_logs (
    log_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    service_id TEXT,
    seq INTEGER NOT NULL,
    source TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_logs_job_seq ON job_logs(job_id, seq);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_services_module_key ON services(module_key);

CREATE TABLE IF NOT EXISTS modules (
    module_id TEXT PRIMARY KEY,
    module_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    input_slots_json TEXT NOT NULL DEFAULT '[]',
    output_slots_json TEXT NOT NULL DEFAULT '[]',
    parameter_schema_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_modules_key ON modules(module_key);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT,
    job_id TEXT,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER,
    uri TEXT,
    storage_key TEXT,
    visibility TEXT NOT NULL,
    retention TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        connection = self.connect()
        try:
            connection.executescript(SCHEMA_SQL)
            service_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(services)")
            }
            if "instance_label" not in service_columns:
                connection.execute(
                    "ALTER TABLE services ADD COLUMN instance_label TEXT"
                )
            job_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(jobs)")
            }
            if "module_id" not in job_columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN module_id TEXT"
                )
            module_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(modules)")
            }
            if "runtime_spec_json" not in module_columns:
                connection.execute(
                    "ALTER TABLE modules ADD COLUMN runtime_spec_json TEXT"
                )
            connection.commit()
        finally:
            connection.close()


@contextmanager
def get_connection(database: Database):
    connection = database.connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
