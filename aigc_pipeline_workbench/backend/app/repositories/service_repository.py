import json
import sqlite3
from datetime import datetime
from typing import Optional

from app.db import get_connection
from app.domain.enums import ServiceStatus
from app.domain.models import AlgorithmService, ServiceCapabilities


class ServiceRepository:
    def __init__(self, database):
        self.database = database

    def create(self, service: AlgorithmService) -> AlgorithmService:
        with get_connection(self.database) as connection:
            connection.execute(
                """
                INSERT INTO services (
                    service_id, module_key, name, base_url, instance_label,
                    enabled, status, version, capabilities_json, gpu_json,
                    registered_at, updated_at, last_checked_at, last_online_at,
                    last_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._params(service),
            )
        return service

    def get(self, service_id: str) -> Optional[AlgorithmService]:
        with get_connection(self.database) as connection:
            row = connection.execute(
                "SELECT * FROM services WHERE service_id = ?", (service_id,)
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def list(self) -> list[AlgorithmService]:
        with get_connection(self.database) as connection:
            rows = connection.execute("SELECT * FROM services ORDER BY registered_at").fetchall()
        return [self._from_row(row) for row in rows]

    def update(self, service: AlgorithmService) -> AlgorithmService:
        with get_connection(self.database) as connection:
            cursor = connection.execute(
                """
                UPDATE services SET
                    module_key = ?, name = ?, base_url = ?, instance_label = ?,
                    enabled = ?, status = ?, version = ?, capabilities_json = ?,
                    gpu_json = ?, registered_at = ?, updated_at = ?,
                    last_checked_at = ?, last_online_at = ?, last_error = ?
                WHERE service_id = ?
                """,
                self._params(service, include_id=False) + [service.service_id],
            )
            if cursor.rowcount == 0:
                return self.create(service)
        return service

    @staticmethod
    def _params(service: AlgorithmService, include_id: bool = True):
        values = [
            service.module_key,
            service.name,
            str(service.base_url),
            service.instance_label,
            int(service.enabled),
            service.status.value,
            service.version,
            service.capabilities.model_dump_json(),
            service.gpu.model_dump_json() if service.gpu else None,
            service.registered_at.isoformat(),
            service.updated_at.isoformat(),
            service.last_checked_at.isoformat() if service.last_checked_at else None,
            service.last_online_at.isoformat() if service.last_online_at else None,
            service.last_error,
        ]
        if include_id:
            return [service.service_id] + values
        return values

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AlgorithmService:
        capabilities = ServiceCapabilities.model_validate(json.loads(row["capabilities_json"]))
        gpu = json.loads(row["gpu_json"]) if row["gpu_json"] else None
        return AlgorithmService(
            service_id=row["service_id"],
            module_key=row["module_key"],
            name=row["name"],
            base_url=row["base_url"],
            instance_label=row["instance_label"],
            enabled=bool(row["enabled"]),
            status=ServiceStatus(row["status"] or ServiceStatus.UNKNOWN),
            version=row["version"] or "unknown",
            capabilities=capabilities,
            gpu=gpu,
            registered_at=datetime.fromisoformat(row["registered_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_checked_at=datetime.fromisoformat(row["last_checked_at"]) if row["last_checked_at"] else None,
            last_online_at=datetime.fromisoformat(row["last_online_at"]) if row["last_online_at"] else None,
            last_error=row["last_error"],
        )
