"""Workspace synchronization use cases through a remote workspace gateway."""

from __future__ import annotations
from typing import Any, Mapping
from pulsecrawl.domain.synchronization.planner import WorkspaceSyncPlanner
from pulsecrawl.application.ports.cloud import HostedWorkspaceGateway


class WorkspaceSyncService:
    def __init__(self, gateway: HostedWorkspaceGateway):
        self._gateway, self._planner = gateway, WorkspaceSyncPlanner()

    def require_scopes(self, required):
        identity = self._gateway.identity()
        if identity is None:
            return
        missing = sorted(required - set(identity.get("scopes") or []))
        if missing:
            raise ValueError(
                "cloud API key is missing required scopes: " + ", ".join(missing)
            )

    def plan(self, bundle):
        self.require_scopes({"catalog:read", "datasets:read", "jobs:read"})
        self._planner._validate_bundle(bundle)
        return self._planner.plan(bundle, self._gateway.snapshot())

    def apply(self, bundle: Mapping[str, Any]) -> dict[str, Any]:
        plan = self.plan(bundle)
        if not plan["safeToApply"]:
            details = "; ".join(item["reason"] for item in plan["conflicts"])
            raise ValueError(f"workspace bundle has cloud conflicts: {details}")
        required = {"catalog:write", "datasets:write", "jobs:write"}
        if bundle.get("schedules"):
            required.add("schedules:write")
        self.require_scopes(required)

        field_map: dict[str, str] = {}
        remote_fields = self._gateway.list("fields", origin="all")
        for field in bundle.get("fields", []):
            existing = self._planner._one_by_name(
                remote_fields, str(field["name"]), "field"
            )
            if existing:
                if existing.get("type") != field.get("type"):
                    raise ValueError(
                        f"field {field['name']!r} exists with a different type"
                    )
                remote = existing
            else:
                remote = self._gateway.create(
                    "fields",
                    str(field["name"]),
                    str(field["type"]),
                    description=str(field.get("description", "")) or None,
                )
                remote_fields.append(remote)
            field_map[str(field["fieldId"])] = str(remote["fieldId"])

        schema_map: dict[str, str] = {}
        remote_schemas = self._gateway.list("schemas", origin="all")
        for schema in bundle.get("schemas", []):
            expected = [
                field_map.get(str(item), str(item)) for item in schema["fieldIds"]
            ]
            existing = self._planner._one_by_name(
                remote_schemas, str(schema["name"]), "schema"
            )
            if existing:
                if list(existing.get("fieldIds", [])) != expected:
                    raise ValueError(
                        f"schema {schema['name']!r} exists with different fields"
                    )
                remote = existing
            else:
                remote = self._gateway.create("schemas", str(schema["name"]), expected)
                remote_schemas.append(remote)
            schema_map[str(schema["schemaId"])] = str(remote["schemaId"])

        template_map: dict[str, str] = {}
        remote_templates = self._gateway.list("templates", origin="all")
        for template in bundle.get("templates", []):
            local_id = str(template["templateId"])
            # Stable system IDs are deliberately shared across local and cloud.
            by_id = next(
                (
                    item
                    for item in remote_templates
                    if item.get("templateId") == local_id
                ),
                None,
            )
            existing = by_id or self._planner._one_by_name(
                remote_templates, str(template["name"]), "template"
            )
            output_schema_id = schema_map.get(
                str(template["outputSchemaId"]), str(template["outputSchemaId"])
            )
            mappings = {
                field_map.get(str(field_id), str(field_id)): expression
                for field_id, expression in template["mappings"].items()
            }
            if existing:
                if (
                    existing.get("outputSchemaId") != output_schema_id
                    or existing.get("engine") != template.get("engine")
                    or existing.get("mappings") != mappings
                ):
                    raise ValueError(
                        f"template {template['name']!r} exists with different contents"
                    )
                remote = existing
            else:
                remote = self._gateway.create(
                    "templates",
                    str(template["name"]),
                    output_schema_id=output_schema_id,
                    engine=str(template["engine"]),
                    mappings=mappings,
                )
                remote_templates.append(remote)
            template_map[local_id] = str(remote["templateId"])

        dataset_map: dict[str, str] = {}
        remote_datasets = self._gateway.list(
            "datasets",
        )
        for dataset in bundle.get("datasets", []):
            schema_id = schema_map[str(dataset["schemaId"])]
            identity = str(dataset.get("identityField", "_source_url"))
            identity = field_map.get(identity, identity)
            existing = self._planner._one_by_name(
                remote_datasets, str(dataset["name"]), "dataset"
            )
            if existing:
                expected = (schema_id, dataset.get("mode", "append_all"), identity)
                actual = (
                    existing.get("schemaId"),
                    existing.get("mode", "append_all"),
                    existing.get("identityField", "_source_url"),
                )
                if actual != expected:
                    raise ValueError(
                        f"dataset {dataset['name']!r} exists with different policy"
                    )
                remote = existing
            else:
                remote = self._gateway.create(
                    "datasets",
                    str(dataset["name"]),
                    schema_id=schema_id,
                    mode=str(dataset.get("mode", "append_all")),
                    identity_field=identity,
                )
                remote_datasets.append(remote)
            dataset_map[str(dataset["datasetId"])] = str(remote["datasetId"])

        job_map: dict[str, str] = {}
        remote_jobs = self._gateway.list(
            "jobs",
        )
        for job in bundle.get("jobs", []):
            stack = []
            for template in job.get("templates", []):
                entry: dict[str, Any] = {
                    "template_id": template_map[str(template["templateId"])]
                }
                scope = template.get("scope") or {}
                if scope.get("hosts"):
                    entry["hosts"] = scope["hosts"]
                if scope.get("urlPatterns"):
                    entry["url_patterns"] = scope["urlPatterns"]
                stack.append(entry)
            if not stack:
                raise ValueError(f"job {job['name']!r} has no authored templates")
            dataset_id = dataset_map[str(job["datasetId"])]
            existing = self._planner._one_by_name(remote_jobs, str(job["name"]), "job")
            if existing:
                expected_stack = self._planner._desired_stack(job, template_map)
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
                    or self._planner._remote_stack(existing) != expected_stack
                    or actual_scope != expected_scope
                    or actual_politeness != expected_politeness
                ):
                    raise ValueError(
                        f"job {job['name']!r} exists with different contents"
                    )
                remote = existing
            else:
                politeness = dict(job.get("politeness") or {})
                politeness.pop("organizationRequestsPerSecond", None)
                remote = self._gateway.create(
                    "jobs",
                    str(job["name"]),
                    seeds=list(job["seeds"]),
                    template_stack=stack,
                    dataset_id=dataset_id,
                    scope=dict(job.get("scope") or {}),
                    politeness=politeness,
                )
                remote_jobs.append(remote)
            job_map[str(job["jobId"])] = str(remote["jobId"])

        for schedule in bundle.get("schedules", []):
            remote_job_id = job_map[str(schedule["jobId"])]
            applied = self._gateway.set_schedule(
                remote_job_id,
                str(schedule["cron"]),
                timezone=str(schedule.get("timezone", "UTC")),
            )
            if schedule.get("status") == "paused" and applied.get("status") != "paused":
                self._gateway.pause_schedule(remote_job_id)

        return {
            "fieldIds": field_map,
            "schemaIds": schema_map,
            "templateIds": template_map,
            "datasetIds": dataset_map,
            "jobIds": job_map,
        }
