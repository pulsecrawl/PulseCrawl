"""Hosted example provisioning through the public PulseCrawl client."""

import importlib
from typing import Any, Iterable, Mapping
from pulsecrawl import PulseCrawl
from pulsecrawl.domain.crawling.model import TemplateSpec
from .catalog import Case, RESPONSIBLE_POLITENESS
from .recipes import normalize


def _by_name(items: Iterable[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("name") == name), None)


def _scope_matches(
    actual: Mapping[str, Any] | None, expected: Mapping[str, Any]
) -> bool:
    """Ignore API-populated defaults not specified by a recipe."""
    actual = actual or {}
    return all(actual.get(key) == value for key, value in expected.items())


def _field_ids(
    pc: PulseCrawl,
    custom_fields: Iterable[tuple[str, str, str]],
    system_field_ids: Iterable[str],
) -> dict[str, str]:
    selected_system_ids = set(system_field_ids)
    system_fields = {
        field["name"]: field
        for field in pc.fields.list(origin="system")
        if field["fieldId"] in selected_system_ids
    }
    fields = pc.fields.list(origin="org")
    result: dict[str, str] = {}
    for name, field_type, description in custom_fields:
        system_field = system_fields.get(name)
        if system_field is not None:
            if system_field.get("type") != field_type:
                raise RuntimeError(
                    f"system field {name!r} is {system_field.get('type')}, "
                    f"expected {field_type}"
                )
            result[name] = system_field["fieldId"]
            continue
        field = _by_name(fields, name)
        if field is not None and field.get("type") != field_type:
            raise RuntimeError(
                f"org field {name!r} is {field.get('type')}, expected {field_type}"
            )
        if field is None:
            field = pc.fields.create(name, field_type, description=description)
            fields.append(field)
        result[name] = field["fieldId"]
    return result


class HostedCaseProvisioner:
    def __init__(self, client: PulseCrawl):
        self.client = client

    def provision(
        self,
        case: Case,
        *,
        run: bool = False,
        cron: str | None = None,
        timezone: str = "UTC",
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        pc = self.client
        politeness = {**RESPONSIBLE_POLITENESS}
        if user_agent:
            politeness["userAgent"] = user_agent
        module = importlib.import_module(case.module)
        fields = _field_ids(pc, module.CUSTOM_FIELDS, case.system_fields)
        sources, seeds = normalize(case, fields)

        schemas = pc.schemas.list(origin="org")
        schema = _by_name(schemas, case.schema_name)
        expected_fields = list(dict.fromkeys([*case.system_fields, *fields.values()]))
        if schema is not None and schema.get("fieldIds") != expected_fields:
            raise RuntimeError(
                f"schema {case.schema_name!r} exists with a different field layout; "
                "archive its jobs and recreate the schema before provisioning"
            )
        if schema is None:
            schema = pc.schemas.create(case.schema_name, expected_fields)

        datasets = pc.datasets.list()
        dataset = _by_name(datasets, case.dataset_name)
        if dataset is None:
            dataset = pc.datasets.create(
                case.dataset_name,
                schema_id=schema["schemaId"],
                mode=case.dataset_mode,
                identity_field="_source_url",
            )
        elif dataset.get("schemaId") != schema["schemaId"]:
            raise RuntimeError(f"dataset {case.dataset_name!r} uses a different schema")
        elif dataset.get("mode", "append_all") != case.dataset_mode:
            raise RuntimeError(
                f"dataset {case.dataset_name!r} uses {dataset.get('mode', 'append_all')}, "
                f"expected {case.dataset_mode}"
            )

        templates = pc.templates.list(origin="org")
        stack: list[dict[str, Any]] = []
        for source in sources:
            for spec in source["templates"]:
                template = _by_name(templates, spec["name"])
                if template is None:
                    template = pc.templates.create(
                        spec["name"],
                        output_schema_id=schema["schemaId"],
                        engine=spec["engine"],
                        mappings=spec["mappings"],
                    )
                    templates.append(template)
                elif (
                    template.get("outputSchemaId") != schema["schemaId"]
                    or template.get("engine") != spec["engine"]
                    or TemplateSpec.normalize_mappings(template.get("mappings", {}))
                    != TemplateSpec.normalize_mappings(spec["mappings"])
                ):
                    raise RuntimeError(
                        f"template {spec['name']!r} differs from the recipe; review it explicitly"
                    )
                stack.append(
                    {
                        "template_id": template["templateId"],
                        "hosts": list(spec.get("hosts", source.get("hosts", ()))),
                        "url_patterns": list(
                            spec.get("urlPatterns", source.get("url_patterns", ()))
                        ),
                    }
                )
        if not stack:
            raise RuntimeError(f"{case.key} has no authored templates")

        expected_stack = [
            {
                "templateId": entry["template_id"],
                "scope": {
                    "hosts": entry["hosts"],
                    "urlPatterns": entry["url_patterns"],
                },
            }
            for entry in stack
        ]
        jobs = pc.jobs.list()
        job = _by_name(jobs, case.label)
        if job and (
            job.get("seeds") != seeds
            or job.get("templateStack") != expected_stack
            or job.get("datasetId") != dataset["datasetId"]
            or not _scope_matches(job.get("scope"), case.scope)
        ):
            raise RuntimeError(
                f"job {case.label!r} differs from the recipe; review it explicitly "
                "or provision into a fresh organization, rather than silently replacing it"
            )
        if job is None:
            job = pc.jobs.create(
                case.label,
                seeds=seeds,
                template_stack=stack,
                dataset_id=dataset["datasetId"],
                scope=case.scope,
                politeness=politeness,
            )
        elif job.get("politeness") != politeness:
            job = pc.jobs.update(
                job["jobId"],
                politeness=politeness,
            )

        if cron:
            pc.schedules.set(job["jobId"], cron, timezone=timezone)

        execution = None
        if run:
            execution = pc.jobs.run(job["jobId"])
        return {
            "case": case.key,
            "job": job,
            "dataset": dataset,
            "sourceCount": len(sources),
            "seedCount": len(seeds),
            "templateCount": len(stack),
            "execution": execution,
        }


def provision_case(pc, case, **options):
    return HostedCaseProvisioner(pc).provision(case, **options)
