import json
import sqlite3
from datetime import datetime
from typing import Optional

from app.db import get_connection
from app.domain.models import InputSlot, ModuleDefinition, OutputSlot, ParameterDefinition, ParameterOption


class ModuleRepository:
    def __init__(self, database):
        self.database = database

    def create(self, module: ModuleDefinition) -> ModuleDefinition:
        with get_connection(self.database) as connection:
            connection.execute(
                """
                INSERT INTO modules (
                    module_id, module_key, name, description, version, status,
                    input_slots_json, output_slots_json, parameter_schema_json,
                    runtime_spec_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._params(module, include_created=True),
            )
        return module

    def get(self, module_id: str) -> Optional[ModuleDefinition]:
        with get_connection(self.database) as connection:
            row = connection.execute(
                "SELECT * FROM modules WHERE module_id = ?", (module_id,)
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def get_by_key(self, module_key: str) -> Optional[ModuleDefinition]:
        with get_connection(self.database) as connection:
            row = connection.execute(
                "SELECT * FROM modules WHERE module_key = ?", (module_key,)
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def list(self, status: Optional[str] = None, module_key: Optional[str] = None) -> list[ModuleDefinition]:
        query = "SELECT * FROM modules"
        conditions = []
        values = []
        if status is not None:
            conditions.append("status = ?")
            values.append(status)
        if module_key is not None:
            conditions.append("module_key = ?")
            values.append(module_key)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        with get_connection(self.database) as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._from_row(row) for row in rows]

    def update(self, module: ModuleDefinition) -> ModuleDefinition:
        with get_connection(self.database) as connection:
            cursor = connection.execute(
                """
                UPDATE modules SET
                    module_key = ?, name = ?, description = ?, version = ?, status = ?,
                    input_slots_json = ?, output_slots_json = ?, parameter_schema_json = ?,
                    runtime_spec_json = ?, updated_at = ?
                WHERE module_id = ?
                """,
                self._params(module, include_id=False, include_created=False) + [module.module_id],
            )
            if cursor.rowcount == 0:
                return self.create(module)
        return module

    @staticmethod
    def _params(module: ModuleDefinition, include_id: bool = True, include_created: bool = True):
        values = [
            module.module_key,
            module.name,
            module.description,
            module.version,
            module.status,
            json.dumps([slot.model_dump(mode="json") for slot in module.input_slots]),
            json.dumps([slot.model_dump(mode="json") for slot in module.output_slots]),
            json.dumps([item.model_dump(mode="json") for item in module.parameter_schema]),
            json.dumps(module.runtime_spec.model_dump(mode="json")) if module.runtime_spec else None,
            module.updated_at.isoformat(),
        ]
        if include_created:
            values.insert(-1, module.created_at.isoformat())
        if include_id:
            return [module.module_id] + values
        return values

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ModuleDefinition:
        runtime_spec = None
        try:
            runtime_spec_raw = row["runtime_spec_json"]
            if runtime_spec_raw:
                from app.domain.models import RuntimeSpec
                runtime_spec = RuntimeSpec.model_validate(json.loads(runtime_spec_raw))
        except (KeyError, IndexError, Exception):
            pass
        return ModuleDefinition(
            module_id=row["module_id"],
            module_key=row["module_key"],
            name=row["name"],
            description=row["description"],
            version=row["version"],
            status=row["status"],
            input_slots=[InputSlot.model_validate(value) for value in json.loads(row["input_slots_json"])],
            output_slots=[OutputSlot.model_validate(value) for value in json.loads(row["output_slots_json"])],
            parameter_schema=[ParameterDefinition.model_validate(value) for value in json.loads(row["parameter_schema_json"])],
            runtime_spec=runtime_spec,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
