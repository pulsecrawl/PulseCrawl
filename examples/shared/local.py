"""Local example provisioning through the public Workspace facade."""

import hashlib
import importlib
from typing import Any
from pulsecrawl import Workspace
from .catalog import Case
from .catalog import RESPONSIBLE_POLITENESS
from .recipes import normalize
from pulsecrawl.domain.crawling.model import TemplateSpec


def _stack_snapshot(entries, *, system=False):
    result = []
    for entry in entries:
        scope = {}
        if entry.get("hosts"):
            scope["hosts"] = list(entry["hosts"])
        if entry.get("url_patterns"):
            scope["urlPatterns"] = list(entry["url_patterns"])
        result.append(
            {
                "templateId": entry["template_id"],
                "engine": entry["engine"],
                "mappings": {
                    key: list(value)
                    for key, value in TemplateSpec.normalize_mappings(
                        entry["mappings"]
                    ).items()
                },
                "origin": "system" if system else "org",
                **({"scope": scope} if scope else {}),
            }
        )
    return result


SYSTEM_FIELDS: dict[str, tuple[str, str]] = {
    "fld_sys_title": ("title", "string"),
    "fld_sys_url": ("url", "url"),
    "fld_sys_description": ("description", "string"),
    "fld_sys_author": ("author", "string"),
    "fld_sys_published_at": ("published_at", "datetime"),
    "fld_sys_image_url": ("image_url", "url"),
    "fld_sys_name": ("name", "string"),
    "fld_sys_price": ("price", "number"),
    "fld_sys_currency": ("currency", "string"),
    "fld_sys_sku": ("sku", "string"),
    "fld_sys_brand": ("brand", "string"),
    "fld_sys_rating": ("rating", "number"),
}


def _field_id(name: str) -> str:
    return "fld_local_" + hashlib.sha256(name.encode()).hexdigest()[:16]


def _system_fallbacks(
    field_ids: set[str], *, namespace: str = ""
) -> list[dict[str, Any]]:
    mappings = {
        "fld_sys_title": ["og:title", "twitter:title", "<title>"],
        "fld_sys_url": ["og:url"],
        "fld_sys_description": ["og:description", "description"],
        "fld_sys_author": ["article:author", "author"],
        "fld_sys_published_at": ["article:published_time"],
        "fld_sys_image_url": ["og:image", "twitter:image"],
        "fld_sys_name": ["og:title", "<title>"],
        "fld_sys_price": ["product:price:amount"],
        "fld_sys_currency": ["product:price:currency"],
        "fld_sys_brand": ["product:brand"],
    }
    selected = {key: value for key, value in mappings.items() if key in field_ids}
    signature = hashlib.sha256(
        (namespace + "\0" + "\0".join(sorted(selected))).encode()
    ).hexdigest()[:16]
    return (
        [
            {
                "template_id": f"tmpl_local_system_meta_{signature}",
                "engine": "meta",
                "mappings": selected,
                "origin": "system",
            }
        ]
        if selected
        else []
    )


class LocalCaseProvisioner:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def provision(
        self,
        case: Case,
        *,
        run: bool = False,
        cron: str | None = None,
        fetcher=None,
        timezone: str = "UTC",
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        workspace = self.workspace
        module = importlib.import_module(case.module)
        system_by_name = {
            name: field_id for field_id, (name, _field_type) in SYSTEM_FIELDS.items()
        }
        custom = {
            name: system_by_name.get(name, _field_id(name))
            for name, _field_type, _description in module.CUSTOM_FIELDS
        }
        sources, seeds = normalize(case, custom)
        fields = [
            {
                "fieldId": field_id,
                "name": SYSTEM_FIELDS[field_id][0],
                "type": SYSTEM_FIELDS[field_id][1],
            }
            for field_id in case.system_fields
        ]
        existing_ids = {field["fieldId"] for field in fields}
        for name, field_type, _description in module.CUSTOM_FIELDS:
            field_id = custom[name]
            if field_id in existing_ids:
                expected = SYSTEM_FIELDS[field_id][1]
                if field_type != expected:
                    raise ValueError(
                        f"{case.key} custom field {name} conflicts with system type {expected}"
                    )
                continue
            fields.append({"fieldId": field_id, "name": name, "type": field_type})
            existing_ids.add(field_id)
        dataset = next(
            (
                item
                for item in workspace.datasets.list()
                if item["name"] == case.dataset_name
            ),
            None,
        )
        if dataset is None:
            dataset = workspace.datasets.create(
                case.dataset_name,
                fields=fields,
                schema_id="schema_local_"
                + hashlib.sha256(case.schema_name.encode()).hexdigest()[:16],
                mode=case.dataset_mode,
            )
        elif (
            dataset.get("mode") != case.dataset_mode
            or [
                {key: field[key] for key in ("fieldId", "name", "type")}
                for field in dataset["fields"]
            ]
            != fields
        ):
            raise RuntimeError(
                f"dataset {case.dataset_name!r} differs from the recipe; choose a fresh workspace"
            )
        templates: list[dict[str, Any]] = []
        for source in sources:
            for index, spec in enumerate(source["templates"]):
                templates.append(
                    {
                        "template_id": "tmpl_local_"
                        + hashlib.sha256(
                            f"{case.key}\0{spec['name']}\0{index}".encode()
                        ).hexdigest()[:20],
                        "engine": spec["engine"],
                        "mappings": spec["mappings"],
                        "hosts": list(spec.get("hosts", source.get("hosts", ()))),
                        "url_patterns": list(
                            spec.get("urlPatterns", source.get("url_patterns", ()))
                        ),
                    }
                )
        job = next(
            (item for item in workspace.jobs.list() if item["name"] == case.label), None
        )
        fallbacks = _system_fallbacks(set(case.system_fields), namespace=case.key)
        politeness = {**RESPONSIBLE_POLITENESS}
        if user_agent:
            politeness["userAgent"] = user_agent
        if job and (
            job["datasetId"] != dataset["datasetId"]
            or job["seeds"] != seeds
            or job["templates"] != _stack_snapshot(templates)
            or job["systemTemplates"] != _stack_snapshot(fallbacks, system=True)
            or any(job["scope"].get(key) != value for key, value in case.scope.items())
            or (user_agent and job["politeness"].get("userAgent") != user_agent)
        ):
            raise RuntimeError(
                f"job {case.label!r} differs from the recipe; choose a fresh workspace"
            )
        if job is None:
            job = workspace.jobs.create(
                case.label,
                seeds=seeds,
                dataset_id=dataset["datasetId"],
                templates=templates,
                system_templates=fallbacks,
                scope=case.scope,
                politeness=politeness,
            )
        if cron:
            workspace.schedules.set(job["jobId"], cron, timezone_name=timezone)
        execution = workspace.jobs.run(job["jobId"], fetcher=fetcher) if run else None
        return {
            "case": case.key,
            "job": job,
            "dataset": dataset,
            "sourceCount": len(sources),
            "seedCount": len(seeds),
            "templateCount": len(templates),
            "execution": execution,
        }


def provision_local_case(workspace, case, **options):
    return LocalCaseProvisioner(workspace).provision(case, **options)
