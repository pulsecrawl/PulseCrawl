"""Catalog use cases receive repositories, not an entire workspace."""

from __future__ import annotations
from typing import Any, Mapping, Sequence
from pulsecrawl.application.ports.workspace import CatalogRepository
from pulsecrawl.domain.workspace.definitions import _safe_identifier, _templates


class CatalogService:
    def __init__(
        self,
        repository: CatalogRepository,
        *,
        fields=None,
        schemas=None,
        now,
        id_factory,
    ):
        self._repository, self._fields, self._schemas = repository, fields, schemas
        self._now, self._id = now, id_factory

    def get(self, identifier):
        return self._repository.get(identifier)

    def list(self):
        return self._repository.list()

    def save(self, value):
        return self._repository.save(value)

    _save = save


class FieldService(CatalogService):
    directory = "fields"
    id_key = "fieldId"

    def create(
        self,
        name: str,
        field_type: str,
        *,
        field_id: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        if not name.strip() or len(name) > 256:
            raise ValueError("field name must contain between 1 and 256 characters")
        if len(description) > 4_096:
            raise ValueError("field description must not exceed 4096 characters")
        if field_id is not None and (not field_id or len(field_id) > 256):
            raise ValueError("field_id must contain between 1 and 256 characters")
        if field_id is not None:
            _safe_identifier(field_id, "field_id")
        if field_type not in ("string", "number", "boolean", "datetime", "url"):
            raise ValueError("unsupported field type")
        return self.save(
            {
                "fieldId": field_id or self._id("fld"),
                "name": name,
                "type": field_type,
                "description": description,
                "origin": "custom",
            }
        )


class SchemaService(CatalogService):
    directory = "schemas"
    id_key = "schemaId"

    def create(
        self,
        name: str,
        field_ids: Sequence[str],
        *,
        schema_id: str | None = None,
    ) -> dict[str, Any]:
        if not name.strip() or len(name) > 256:
            raise ValueError("schema name must contain between 1 and 256 characters")
        if not field_ids or len(field_ids) > 1_000:
            raise ValueError("a schema needs between 1 and 1000 fields")
        if len(set(field_ids)) != len(field_ids):
            raise ValueError("schema field ids must be unique")
        if schema_id is not None:
            _safe_identifier(schema_id, "schema_id")
        fields = [self._fields.get(field_id) for field_id in field_ids]
        return self.save(
            {
                "schemaId": schema_id or self._id("schema"),
                "name": name,
                "fieldIds": list(field_ids),
                "fields": fields,
                "origin": "custom",
            }
        )


class TemplateService(CatalogService):
    directory = "templates"
    id_key = "templateId"

    def create(
        self,
        name: str,
        *,
        output_schema_id: str,
        engine: str,
        mappings: Mapping[str, Any],
        template_id: str | None = None,
        origin: str = "custom",
    ) -> dict[str, Any]:
        if not name.strip() or len(name) > 256:
            raise ValueError("template name must contain between 1 and 256 characters")
        self._schemas.get(output_schema_id)
        if engine not in ("css", "jsonld", "meta"):
            raise ValueError("unsupported template engine")
        identifier = template_id or self._id("tmpl")
        _safe_identifier(identifier, "template_id")
        normalized = _templates(
            [
                {
                    "templateId": identifier,
                    "engine": engine,
                    "mappings": mappings,
                    "origin": "system" if origin == "system" else "org",
                }
            ]
        )[0]
        value = {
            "templateId": identifier,
            "name": name,
            "outputSchemaId": output_schema_id,
            "engine": engine,
            "mappings": normalized["mappings"],
            "origin": "system" if origin == "system" else "org",
            "createdAt": self._now(),
        }
        try:
            existing = self.get(str(value["templateId"]))
        except KeyError:
            return self.save(value)
        comparable = (
            "templateId",
            "name",
            "outputSchemaId",
            "engine",
            "mappings",
            "origin",
        )
        if all(existing.get(key) == value.get(key) for key in comparable):
            return existing
        raise ValueError(
            f"{value['templateId']} already exists with different contents"
        )
