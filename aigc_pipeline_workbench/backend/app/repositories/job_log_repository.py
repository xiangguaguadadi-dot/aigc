import json
from datetime import datetime
from typing import Optional

from app.db import get_connection
from app.domain.enums import LogLevel, LogSource
from app.domain.models import JobLog


class JobLogRepository:
    def __init__(self, database):
        self.database = database

    def create(self, log: JobLog) -> JobLog:
        with get_connection(self.database) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO job_logs (
                    log_id, job_id, service_id, seq, source, level, message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.log_id,
                    log.job_id,
                    log.service_id,
                    log.seq,
                    log.source.value,
                    log.level.value,
                    log.message,
                    log.created_at.isoformat(),
                ),
            )
        return log

    def list(self, job_id: str, after_seq: Optional[int] = None) -> list[JobLog]:
        query = "SELECT * FROM job_logs WHERE job_id = ?"
        params: list[object] = [job_id]
        if after_seq is not None:
            query += " AND seq > ?"
            params.append(after_seq)
        query += " ORDER BY seq"
        with get_connection(self.database) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._from_row(row) for row in rows]

    def max_seq(self, job_id: str) -> int:
        with get_connection(self.database) as connection:
            value = connection.execute(
                "SELECT MAX(seq) FROM job_logs WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
        return int(value) if value is not None else -1

    @staticmethod
    def _from_row(row) -> JobLog:
        return JobLog(
            log_id=row["log_id"],
            job_id=row["job_id"],
            service_id=row["service_id"],
            seq=row["seq"],
            source=LogSource(row["source"]),
            level=LogLevel(row["level"]),
            message=row["message"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
