"""Pure workspace synchronization planning from two supplied snapshots."""

from __future__ import annotations
from typing import Any, Mapping

BUNDLE_VERSION = 1


class WorkspaceSyncPlanner:
    @staticmethod
    def _one_by_name(items: list[dict], name: str, kind: str) -> dict | None:
        matches = [item for item in items if item.get("name") == name]
        if len(matches) > 1:
            raise ValueError(f"cloud has multiple {kind} resources named {name!r}")
        return matches[0] if matches else None

    @staticmethod
    def _items(bundle: Mapping[str, Any], kind: str, id_key: str) -> list[dict]:
        raw = bundle.get(kind, [])
        if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
            raise ValueError(f"workspace bundle {kind} must be a list of objects")
        identifiers = [str(item.get(id_key, "")) for item in raw]
        names = [str(item.get("name", "")) for item in raw]
        if any(not value for value in identifiers) or len(set(identifiers)) != len(
            identifiers
        ):
            raise ValueError(f"workspace bundle has missing or duplicate {kind} IDs")
        if any(not value for value in names) or len(set(names)) != len(names):
            raise ValueError(f"workspace bundle has missing or duplicate {kind} names")
        return raw

    @classmethod
    def _validate_bundle(cls, bundle: Mapping[str, Any]) -> dict[str, list[dict]]:
        if bundle.get("bundleVersion") != BUNDLE_VERSION:
            raise ValueError("unsupported workspace bundle version")
        result = {
            "fields": cls._items(bundle, "fields", "fieldId"),
            "schemas": cls._items(bundle, "schemas", "schemaId"),
            "templates": cls._items(bundle, "templates", "templateId"),
            "datasets": cls._items(bundle, "datasets", "datasetId"),
            "jobs": cls._items(bundle, "jobs", "jobId"),
        }
        field_ids = {str(item["fieldId"]) for item in result["fields"]}
        schema_ids = {str(item["schemaId"]) for item in result["schemas"]}
        template_ids = {str(item["templateId"]) for item in result["templates"]}
        dataset_ids = {str(item["datasetId"]) for item in result["datasets"]}
        job_ids = {str(item["jobId"]) for item in result["jobs"]}
        for schema in result["schemas"]:
            if not schema.get("fieldIds") or any(
                str(field_id) not in field_ids for field_id in schema["fieldIds"]
            ):
                raise ValueError(
                    f"schema {schema['name']!r} references an unknown field"
                )
        for template in result["templates"]:
            if str(template.get("outputSchemaId")) not in schema_ids:
                raise ValueError(
                    f"template {template['name']!r} references an unknown schema"
                )
            if any(
                str(field_id) not in field_ids
                for field_id in template.get("mappings", {})
            ):
                raise ValueError(f"template {template['name']!r} maps an unknown field")
        for dataset in result["datasets"]:
            if str(dataset.get("schemaId")) not in schema_ids:
                raise ValueError(
                    f"dataset {dataset['name']!r} references an unknown schema"
                )
        for job in result["jobs"]:
            if str(job.get("datasetId")) not in dataset_ids:
                raise ValueError(f"job {job['name']!r} references an unknown dataset")
            entries = job.get("templates") or []
            if not entries or any(
                str(entry.get("templateId")) not in template_ids for entry in entries
            ):
                raise ValueError(f"job {job['name']!r} references an unknown template")
        schedules = bundle.get("schedules", [])
        if not isinstance(schedules, list) or any(
            not isinstance(item, dict) for item in schedules
        ):
            raise ValueError("workspace bundle schedules must be a list of objects")
        scheduled_jobs: set[str] = set()
        for schedule in schedules:
            job_id = str(schedule.get("jobId", ""))
            if job_id not in job_ids:
                raise ValueError("schedule references an unknown job")
            if job_id in scheduled_jobs:
                raise ValueError("workspace bundle has duplicate schedules for a job")
            scheduled_jobs.add(job_id)
        return result

    @staticmethod
    def _remote_stack(job: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw = job.get("templateStack") or job.get("template_stack")
        if raw is None:
            identifiers = job.get("templateIds") or (
                [job["templateId"]] if job.get("templateId") else []
            )
            raw = [{"templateId": template_id} for template_id in identifiers]
        return [
            {
                "templateId": str(entry.get("templateId") or entry.get("template_id")),
                "scope": {
                    key: list(value)
                    for key, value in {
                        **(entry.get("scope") or {}),
                        "hosts": entry.get("hosts"),
                        "urlPatterns": entry.get("url_patterns"),
                    }.items()
                    if key in ("hosts", "urlPatterns") and value
                },
            }
            for entry in raw
        ]

    @staticmethod
    def _desired_stack(
        job: Mapping[str, Any], template_map: Mapping[str, str]
    ) -> list[dict[str, Any]]:
        return [
            {
                "templateId": template_map[str(entry["templateId"])],
                "scope": {
                    key: list(value)
                    for key, value in (entry.get("scope") or {}).items()
                    if key in ("hosts", "urlPatterns") and value
                },
            }
            for entry in job.get("templates", [])
        ]

    def plan(
        self, bundle: Mapping[str, Any], remote: Mapping[str, list[dict]]
    ) -> dict[str, Any]:
        items = self._validate_bundle(bundle)
        actions: list[dict[str, str]] = []
        conflicts: list[dict[str, str]] = []
        for kind in ("fields", "schemas", "templates", "datasets", "jobs"):
            singular = kind[:-1] if kind != "schemas" else "schema"
            for item in items[kind]:
                existing = self._one_by_name(remote[kind], str(item["name"]), singular)
                reason: str | None = None
                if (
                    kind == "fields"
                    and existing
                    and existing.get("type") != item.get("type")
                ):
                    reason = "field exists with a different type"
                actions.append(
                    {
                        "kind": singular,
                        "localId": str(
                            item.get(
                                {
                                    "fields": "fieldId",
                                    "schemas": "schemaId",
                                    "templates": "templateId",
                                    "datasets": "datasetId",
                                    "jobs": "jobId",
                                }[kind],
                                "",
                            )
                        ),
                        "name": str(item["name"]),
                        "action": "conflict"
                        if reason
                        else ("reuse" if existing else "create"),
                    }
                )
                if reason:
                    conflicts.append(
                        {"kind": singular, "name": str(item["name"]), "reason": reason}
                    )

        def conflict(kind: str, name: str, reason: str) -> None:
            if not any(
                item["kind"] == kind and item["name"] == name for item in conflicts
            ):
                conflicts.append({"kind": kind, "name": name, "reason": reason})
            for action in actions:
                if action["kind"] == kind and action["name"] == name:
                    action["action"] = "conflict"

        field_map: dict[str, str | None] = {}
        for field in items["fields"]:
            existing = self._one_by_name(remote["fields"], str(field["name"]), "field")
            field_map[str(field["fieldId"])] = (
                str(existing["fieldId"]) if existing else None
            )

        schema_map: dict[str, str | None] = {}
        for schema in items["schemas"]:
            existing = self._one_by_name(
                remote["schemas"], str(schema["name"]), "schema"
            )
            schema_map[str(schema["schemaId"])] = (
                str(existing["schemaId"]) if existing else None
            )
            if existing:
                mapped = [field_map[str(field_id)] for field_id in schema["fieldIds"]]
                if any(field_id is None for field_id in mapped):
                    conflict(
                        "schema",
                        str(schema["name"]),
                        "same-name schema depends on fields that must be created",
                    )
                elif list(existing.get("fieldIds", [])) != mapped:
                    conflict(
                        "schema",
                        str(schema["name"]),
                        "schema exists with different fields",
                    )

        template_map: dict[str, str | None] = {}
        for template in items["templates"]:
            local_id = str(template["templateId"])
            existing = next(
                (
                    entry
                    for entry in remote["templates"]
                    if entry.get("templateId") == local_id
                ),
                None,
            ) or self._one_by_name(
                remote["templates"], str(template["name"]), "template"
            )
            template_map[local_id] = str(existing["templateId"]) if existing else None
            if existing:
                schema_id = schema_map[str(template["outputSchemaId"])]
                mapped_fields = {
                    field_map[str(field_id)]: expression
                    for field_id, expression in template["mappings"].items()
                    if field_map[str(field_id)] is not None
                }
                if schema_id is None or len(mapped_fields) != len(template["mappings"]):
                    conflict(
                        "template",
                        str(template["name"]),
                        "same-name template depends on resources that must be created",
                    )
                elif (
                    existing.get("outputSchemaId") != schema_id
                    or existing.get("engine") != template.get("engine")
                    or existing.get("mappings") != mapped_fields
                ):
                    conflict(
                        "template",
                        str(template["name"]),
                        "template exists with different contents",
                    )

        dataset_map: dict[str, str | None] = {}
        for dataset in items["datasets"]:
            existing = self._one_by_name(
                remote["datasets"], str(dataset["name"]), "dataset"
            )
            dataset_map[str(dataset["datasetId"])] = (
                str(existing["datasetId"]) if existing else None
            )
            if existing:
                schema_id = schema_map[str(dataset["schemaId"])]
                identity = str(dataset.get("identityField", "_source_url"))
                identity = field_map.get(identity, identity)
                if schema_id is None or identity is None:
                    conflict(
                        "dataset",
                        str(dataset["name"]),
                        "same-name dataset depends on resources that must be created",
                    )
                elif (
                    existing.get("schemaId"),
                    existing.get("mode", "append_all"),
                    existing.get("identityField", "_source_url"),
                ) != (schema_id, dataset.get("mode", "append_all"), identity):
                    conflict(
                        "dataset",
                        str(dataset["name"]),
                        "dataset exists with a different policy",
                    )

        for job in items["jobs"]:
            existing = self._one_by_name(remote["jobs"], str(job["name"]), "job")
            if not existing:
                continue
            dataset_id = dataset_map[str(job["datasetId"])]
            mapped_templates = {
                local_id: remote_id
                for local_id, remote_id in template_map.items()
                if remote_id is not None
            }
            if dataset_id is None or any(
                str(entry["templateId"]) not in mapped_templates
                for entry in job.get("templates", [])
            ):
                conflict(
                    "job",
                    str(job["name"]),
                    "same-name job depends on resources that must be created",
                )
                continue
            expected_scope = dict(job.get("scope") or {})
            expected_scope.pop("maxPages", None)
            expected_politeness = dict(job.get("politeness") or {})
            expected_politeness.pop("organizationRequestsPerSecond", None)
            actual_scope = dict(existing.get("scope") or {})
            actual_scope.pop("maxPages", None)
            actual_politeness = dict(existing.get("politeness") or {})
            actual_politeness.pop("organizationRequestsPerSecond", None)
            if (
                list(existing.get("seeds", [])) != list(job["seeds"])
                or (existing.get("datasetId") or existing.get("dataset_id"))
                != dataset_id
                or self._remote_stack(existing)
                != self._desired_stack(job, mapped_templates)
                or actual_scope != expected_scope
                or actual_politeness != expected_politeness
            ):
                conflict("job", str(job["name"]), "job exists with different contents")
        return {
            "bundleVersion": BUNDLE_VERSION,
            "actions": actions,
            "conflicts": conflicts,
            "safeToApply": not conflicts,
        }
