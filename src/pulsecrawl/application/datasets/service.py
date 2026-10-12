"""Dataset definition and access use cases."""

from __future__ import annotations
from typing import Any, Mapping, Sequence
from pulsecrawl.application.ports.workspace import (
    DefinitionRepository,
    DefinitionSnapshots,
)


class DatasetService:
    def __init__(
        self,
        *,
        repository: DefinitionRepository,
        fields,
        schemas,
        readers,
        snapshots: DefinitionSnapshots,
        prune,
        now,
        id_factory,
    ):
        self._repository, self._fields, self._schemas = repository, fields, schemas
        self._readers, self._snapshots, self._prune = readers, snapshots, prune
        self._now, self._id = now, id_factory

    def create(
        self,
        name: str,
        *,
        fields: Sequence[Mapping[str, str]] | None = None,
        schema_id: str | None = None,
        mode: str = "append_all",
        identity_field: str = "_source_url",
    ) -> dict[str, Any]:
        if not name.strip() or len(name) > 256:
            raise ValueError("dataset name must contain between 1 and 256 characters")
        if mode not in ("append_all", "new_urls_only"):
            raise ValueError("mode must be append_all or new_urls_only")
        if fields is None:
            if schema_id is None:
                raise ValueError("pass fields or schema_id")
            schema = self._schemas.get(schema_id)
            normalized_fields = [dict(field) for field in schema["fields"]]
        else:
            normalized_fields = [dict(field) for field in fields]
            if not normalized_fields or len(normalized_fields) > 1_000:
                raise ValueError("a dataset needs between 1 and 1000 fields")
            required = {"fieldId", "name", "type"}
            if any(not required.issubset(field) for field in normalized_fields):
                raise ValueError("each dataset field needs fieldId, name, and type")
            if any(
                field["type"] not in ("string", "number", "boolean", "datetime", "url")
                for field in normalized_fields
            ):
                raise ValueError("unsupported field type")
            identifiers = [str(field["fieldId"]) for field in normalized_fields]
            names = [str(field["name"]).lower() for field in normalized_fields]
            if len(set(identifiers)) != len(identifiers) or len(set(names)) != len(
                names
            ):
                raise ValueError("dataset field ids and names must be unique")
            for field in normalized_fields:
                self._fields.save(
                    {
                        **field,
                        "description": field.get("description", ""),
                        "origin": field.get("origin", "custom"),
                    }
                )
            schema_identifier = schema_id or self._id("schema")
            existing_schema = next(
                (
                    item
                    for item in self._schemas.list()
                    if item["schemaId"] == schema_identifier
                ),
                None,
            )
            if existing_schema is None:
                self._schemas.create(
                    f"{name} schema",
                    [str(field["fieldId"]) for field in normalized_fields],
                    schema_id=schema_identifier,
                )
            elif [
                {key: field.get(key) for key in ("fieldId", "name", "type")}
                for field in existing_schema["fields"]
            ] != [
                {key: field.get(key) for key in ("fieldId", "name", "type")}
                for field in normalized_fields
            ]:
                raise ValueError("schema_id exists with different fields")
            schema_id = schema_identifier
        identity_column = identity_field
        if identity_field != "_source_url":
            found = next(
                (
                    field
                    for field in normalized_fields
                    if field.get("fieldId") == identity_field
                    or field.get("name") == identity_field
                ),
                None,
            )
            if found is None or found.get("type") != "url":
                raise ValueError("custom identity field must reference a url field")
            identity_column = str(found["name"])
        definition = {
            "datasetId": self._id("ds"),
            "name": name,
            "schemaId": schema_id,
            "fields": normalized_fields,
            "mode": mode,
            "identityField": identity_field,
            "identityColumn": identity_column,
            "createdAt": self._now(),
        }
        self._repository.add(definition)
        self._snapshots.write("datasets", definition["datasetId"], definition)
        return definition

    def list(self):
        return self._repository.list()

    def get(self, dataset_id):
        return self._repository.get(dataset_id)

    def files(
        self, dataset_id: str, *, version: int | None = None
    ) -> list[dict[str, Any]]:
        return self._readers(self.get(dataset_id)).files(version=version)

    def query(
        self,
        dataset_id: str,
        sql: str,
        *,
        version: int | None = None,
        row_cap: int = 1_000,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        return self._readers(self.get(dataset_id)).query(
            sql, version=version, row_cap=row_cap, timeout_s=timeout_s
        )

    def urls(self, dataset_id: str, **filters: Any) -> dict[str, Any]:
        return self._readers(self.get(dataset_id)).urls(**filters)

    def compact(self, dataset_id: str, *, minimum_files: int = 2) -> int:
        return self._readers(self.get(dataset_id)).compact(minimum_files=minimum_files)

    def prune(
        self,
        dataset_id: str,
        *,
        keep_versions: int | None = None,
        keep_snapshots: int | None = None,
        older_than_days: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        return self._prune(
            dataset_id,
            keep_versions=keep_versions,
            keep_snapshots=keep_snapshots,
            older_than_days=older_than_days,
            dry_run=dry_run,
        )
