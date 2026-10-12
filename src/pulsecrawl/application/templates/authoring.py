"""Authoring use cases, independent of local files and crawler construction."""

from __future__ import annotations
from typing import Any, Mapping, Sequence
from pulsecrawl.application.ports.workspace import DraftRepository
from urllib.parse import urlsplit
from pulsecrawl.domain.templates.authoring import TemplateDraft, RepresentativePage
from pulsecrawl.domain.crawling.urls import same_site


class TemplateAuthoringService:
    """Govern draft validation, approval and promotion through injected ports."""

    def __init__(
        self,
        *,
        drafts: DraftRepository,
        schemas,
        templates,
        jobs,
        executions,
        pages,
        inspector,
        validator,
        now,
        id_factory,
    ):
        self._drafts, self._schemas, self._templates = drafts, schemas, templates
        self._jobs, self._executions, self._pages = jobs, executions, pages
        self._inspector, self._validator = inspector, validator
        self._now, self._id = now, id_factory

    def _save(self, draft):
        return self._drafts.save(draft)

    def list_drafts(self):
        return self._drafts.list()

    def get_draft(self, draft_id):
        return self._drafts.get(draft_id)

    def create_draft(
        self,
        name: str,
        *,
        output_schema_id: str,
        templates: Sequence[Mapping[str, Any]],
        source_job_id: str,
        based_on_draft_id: str | None = None,
        based_on_template_id: str | None = None,
    ) -> TemplateDraft:
        if not name.strip():
            raise ValueError("draft name must not be empty")
        schema = self._schemas.get(output_schema_id)
        allowed = {str(item["fieldId"]) for item in schema["fields"]}
        if not templates:
            raise ValueError("a draft needs at least one template entry")
        if based_on_draft_id and based_on_template_id:
            raise ValueError("a draft can have only one direct predecessor")
        previous_draft = (
            self.get_draft(based_on_draft_id) if based_on_draft_id else None
        )
        if previous_draft and previous_draft.output_schema_id != output_schema_id:
            raise ValueError("the predecessor draft uses a different schema")
        if based_on_template_id:
            predecessor = self._templates.get(based_on_template_id)
            if predecessor["outputSchemaId"] != output_schema_id:
                raise ValueError("the predecessor template uses a different schema")
        source_job = self._jobs.get(source_job_id)
        if source_job["schema"]["schemaId"] != output_schema_id:
            raise ValueError("the source job uses a different schema")
        allowed_job_hosts = {
            str(urlsplit(seed).hostname).lower()
            for seed in source_job.get("seeds", ())
            if urlsplit(seed).hostname
        }
        normalized: list[dict[str, Any]] = []
        identifiers: set[str] = set()
        for index, raw in enumerate(templates):
            if raw.get("engine") not in ("css", "jsonld", "meta"):
                raise ValueError("unsupported template engine")
            mappings: dict[str, list[str]] = {}
            for key, value in dict(raw.get("mappings") or {}).items():
                chain = [value] if isinstance(value, str) else list(value)
                if not chain or any(
                    not isinstance(item, str) or not item.strip() for item in chain
                ):
                    raise ValueError("mapping expressions must be non-empty strings")
                mappings[str(key)] = chain
            unknown = sorted(set(mappings) - allowed)
            if not mappings or unknown:
                raise ValueError(
                    "draft mappings must be non-empty and reference only schema fields"
                )
            nested = raw.get("scope") or {}
            hosts = raw.get("hosts", nested.get("hosts")) or ()
            patterns = (
                raw.get(
                    "url_patterns", raw.get("urlPatterns", nested.get("urlPatterns"))
                )
                or ()
            )
            if isinstance(hosts, str) or isinstance(patterns, str):
                raise ValueError(
                    "hosts and URL patterns must be sequences, not strings"
                )
            if any(
                not isinstance(item, str) or not item.strip()
                for item in (*hosts, *patterns)
            ):
                raise ValueError(
                    "hosts and URL patterns must contain non-empty strings"
                )
            if not hosts:
                hosts = tuple(sorted(allowed_job_hosts))
            outside = sorted(
                str(host)
                for host in hosts
                if not any(
                    self._host_within_source(str(host), allowed)
                    for allowed in allowed_job_hosts
                )
            )
            if outside:
                raise ValueError("draft scope expands beyond the source job hosts")
            template_identifier = str(
                raw.get("template_id")
                or raw.get("templateId")
                or f"draft-entry-{index}"
            )
            if template_identifier in identifiers:
                raise ValueError("draft template ids must be unique")
            identifiers.add(template_identifier)
            entry = {
                "templateId": template_identifier,
                "engine": raw["engine"],
                "mappings": mappings,
            }
            if hosts or patterns:
                entry["scope"] = {
                    **({"hosts": list(hosts)} if hosts else {}),
                    **({"urlPatterns": list(patterns)} if patterns else {}),
                }
            normalized.append(entry)
        version = 1
        if previous_draft:
            version = previous_draft.version + 1

        return self._save(
            TemplateDraft(
                draft_id=self._id("draft"),
                name=name,
                output_schema_id=output_schema_id,
                version=version,
                templates=tuple(normalized),
                status="draft",
                created_at=self._now(),
                based_on_template_id=based_on_template_id,
                based_on_draft_id=based_on_draft_id,
                source_job_id=source_job_id,
            )
        )

    @staticmethod
    def _host_within_source(declared: str, allowed: str) -> bool:
        declared = declared.lower().rstrip(".")
        allowed = allowed.lower().rstrip(".")
        if declared.startswith("*."):
            return False
        return same_site(f"https://{declared}/", allowed)

    def sample(
        self,
        job_id: str,
        *,
        max_pages: int,
        max_depth: int | None = None,
        _fetcher: Any = None,
    ) -> dict[str, Any]:
        """Run a bounded governed execution and return its retained pages.

        The downward-only limits are frozen into the ordinary execution intent.
        The normal robots, origin gate, redirect, scope, and response-size rules
        remain in force. ``_fetcher`` is a private deterministic-test hook. A
        custom adapter is trusted code and is not covered by transport-level
        redirect, content-type, or body-size guarantees.
        """
        result = self._jobs.run(
            job_id,
            fetcher=_fetcher,
            max_urls_per_execution=max_pages,
            max_depth=max_depth,
            store_raw_pages=True,
            publish_records=False,
        )
        return {
            "execution": result,
            "pages": [
                page.to_dict()
                for page in self.load_execution_pages(result["executionId"])
            ],
        }

    def load_execution_pages(self, execution_id):
        execution = self._executions.get(execution_id)
        if execution["status"] != "succeeded":
            raise RuntimeError("representative pages require a completed execution")
        return self._pages.load(execution_id)

    def inspect(
        self,
        page: RepresentativePage | Mapping[str, Any],
        *,
        include_content_samples: bool = False,
        max_body_bytes: int = 5 * 1024 * 1024,
    ) -> dict[str, Any]:
        return self._inspector(
            page,
            include_content_samples=include_content_samples,
            max_body_bytes=max_body_bytes,
        ).to_dict()

    def validate(
        self,
        draft_id: str,
        pages: Sequence[RepresentativePage | Mapping[str, Any]],
        *,
        system_templates: Sequence[Mapping[str, Any]] = (),
        required_field_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        draft = self.get_draft(draft_id)
        if draft.status in ("approved", "promoted"):
            raise ValueError(
                "approved or promoted drafts are immutable; create a repair draft"
            )
        schema = self._schemas.get(draft.output_schema_id)
        required = (
            list(required_field_ids)
            if required_field_ids is not None
            else [str(item["fieldId"]) for item in schema["fields"]]
        )
        report = self._validator(
            draft.templates,
            pages,
            system_templates=system_templates,
            required_field_ids=required,
            field_types={
                str(item["fieldId"]): str(item["type"]) for item in schema["fields"]
            },
        )
        self._save(draft.with_validation(report))
        return report

    def approve(self, draft_id, *, validation_id, approved_by):
        draft = self.get_draft(draft_id)
        return self._save(draft.approve(validation_id, approved_by, self._now()))

    def promote(self, draft_id: str) -> dict[str, Any]:
        """Create immutable catalog templates without modifying any active job."""
        draft = self.get_draft(draft_id)
        if draft.promoted_template_ids:
            return {
                "draft": draft,
                "templates": [
                    self._templates.get(item) for item in draft.promoted_template_ids
                ],
                "templateStack": self._promoted_stack(draft),
            }
        if draft.status != "approved":
            raise ValueError("a draft must be explicitly approved before promotion")
        promoted = []
        stack = []
        for index, entry in enumerate(draft.templates):
            stable_suffix = draft.draft_id.removeprefix("draft_")
            template_id = f"tmpl_{stable_suffix}_{index + 1}"
            template = self._templates.create(
                f"{draft.name} v{draft.version} entry {index + 1}",
                output_schema_id=draft.output_schema_id,
                engine=str(entry["engine"]),
                mappings=entry["mappings"],
                template_id=template_id,
            )
            promoted.append(template)
            stack_entry = {"templateId": template["templateId"]}
            if entry.get("scope"):
                stack_entry["scope"] = entry["scope"]
            stack.append(stack_entry)
        promoted_draft = self._save(
            draft.promote(tuple(item["templateId"] for item in promoted))
        )
        return {"draft": promoted_draft, "templates": promoted, "templateStack": stack}

    def _promoted_stack(self, draft: TemplateDraft) -> list[dict[str, Any]]:
        result = []
        for template_id, entry in zip(draft.promoted_template_ids, draft.templates):
            item: dict[str, Any] = {"templateId": template_id}
            if entry.get("scope"):
                item["scope"] = entry["scope"]
            result.append(item)
        return result

    def repair_draft(
        self,
        template_id: str,
        *,
        name: str | None = None,
        scope: Mapping[str, Any] | None = None,
        source_job_id: str,
    ) -> TemplateDraft:
        active = self._templates.get(template_id)
        entry: dict[str, Any] = {
            "templateId": f"repair-{template_id}",
            "engine": active["engine"],
            "mappings": active["mappings"],
        }
        if scope:
            entry["scope"] = dict(scope)
        return self.create_draft(
            name or f"Repair {active['name']}",
            output_schema_id=active["outputSchemaId"],
            templates=[entry],
            based_on_template_id=template_id,
            source_job_id=source_job_id,
        )

    def diagnose_drift(
        self,
        template_id: str,
        baseline_pages: Sequence[RepresentativePage | Mapping[str, Any]],
        current_pages: Sequence[RepresentativePage | Mapping[str, Any]],
        *,
        scope: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        active = self._templates.get(template_id)
        schema = self._schemas.get(active["outputSchemaId"])
        field_types = {
            str(item["fieldId"]): str(item["type"]) for item in schema["fields"]
        }
        entry: dict[str, Any] = {
            "templateId": template_id,
            "engine": active["engine"],
            "mappings": active["mappings"],
        }
        if scope:
            entry["scope"] = dict(scope)
        required = list(active["mappings"])
        before = self._validator(
            [entry],
            baseline_pages,
            required_field_ids=required,
            field_types=field_types,
        )
        after = self._validator(
            [entry], current_pages, required_field_ids=required, field_types=field_types
        )
        before_by_url = {item["url"]: item for item in before["pages"]}
        current_by_url = {item["url"]: item for item in after["pages"]}
        regressions = []
        for url, current in current_by_url.items():
            baseline = before_by_url.get(url)
            if baseline and baseline["entityCount"] > 0 and current["entityCount"] == 0:
                regressions.append(url)

        def field_coverage(report: Mapping[str, Any]) -> dict[str, float]:
            positives = [item for item in report["pages"] if item["role"] == "positive"]
            denominator = max(1, len(positives))
            return {
                field_id: sum(
                    any(field_id in record for record in item["records"])
                    for item in positives
                )
                / denominator
                for field_id in required
            }

        baseline_coverage = field_coverage(before)
        current_coverage = field_coverage(after)
        return {
            "templateId": template_id,
            "baseline": before,
            "current": after,
            "matchRateDelta": (
                after["summary"]["authoredPositiveMatches"]
                / max(1, after["summary"]["positivePages"])
                - before["summary"]["authoredPositiveMatches"]
                / max(1, before["summary"]["positivePages"])
            ),
            "regressionUrls": regressions,
            "fieldCoverage": {
                field_id: {
                    "baseline": baseline_coverage[field_id],
                    "current": current_coverage[field_id],
                    "delta": current_coverage[field_id] - baseline_coverage[field_id],
                }
                for field_id in required
            },
            "repairDraftAvailable": True,
        }
