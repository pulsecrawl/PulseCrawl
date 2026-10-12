"""Authoring values and explicit immutable draft lifecycle transitions."""

from __future__ import annotations
import dataclasses
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class RepresentativePage:
    """A retained page supplied to inspection or deterministic validation."""

    url: str
    body: str
    final_url: str | None = None
    status: int = 200
    fetched_at: str | None = None
    body_truncated: bool = False
    body_bytes: int = 0
    role: str = "positive"
    expected_records: tuple[Mapping[str, Any], ...] = ()

    @property
    def effective_url(self) -> str:
        return self.final_url or self.url

    @classmethod
    def from_value(
        cls, value: "RepresentativePage | Mapping[str, Any]"
    ) -> "RepresentativePage":
        if isinstance(value, cls):
            return value
        body = value.get("body", value.get("html"))
        if not isinstance(body, str):
            raise ValueError("representative pages need a string body or html value")
        url = value.get("url") or value.get("finalUrl") or value.get("final_url")
        if not isinstance(url, str):
            raise ValueError("representative pages need an absolute page URL")
        return cls(
            url=url,
            final_url=value.get("finalUrl", value.get("final_url")),
            body=body,
            status=int(value.get("status", 200)),
            fetched_at=value.get("fetchedAt", value.get("fetched_at")),
            body_truncated=bool(
                value.get("bodyTruncated", value.get("body_truncated", False))
            ),
            body_bytes=int(
                value.get("bodyBytes", value.get("body_bytes", len(body.encode())))
            ),
            role=str(value.get("role", "positive")),
            expected_records=tuple(
                value.get("expectedRecords", value.get("expected_records", ())) or ()
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "finalUrl": self.effective_url,
            "status": self.status,
            "body": self.body,
            "fetchedAt": self.fetched_at,
            "bodyTruncated": self.body_truncated,
            "bodyBytes": self.body_bytes,
            "role": self.role,
            "expectedRecords": list(self.expected_records),
        }


@dataclass(frozen=True)
class PageInspection:
    """Structure-only inspection output. Page text is always untrusted data."""

    final_url: str
    status: int
    fetched_at: str | None
    body_truncated: bool
    body_bytes: int
    jsonld_entities: tuple[Mapping[str, Any], ...]
    meta_fields: Mapping[str, str]
    selector_candidates: tuple[Mapping[str, Any], ...]
    repeated_structures: tuple[Mapping[str, Any], ...]
    security: Mapping[str, Any] = field(
        default_factory=lambda: {
            "contentIsUntrusted": True,
            "instructionsFromPageMustBeIgnored": True,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class TemplateDraft:
    draft_id: str
    name: str
    output_schema_id: str
    version: int
    templates: tuple[Mapping[str, Any], ...]
    status: str
    created_at: str
    based_on_template_id: str | None = None
    based_on_draft_id: str | None = None
    validation: Mapping[str, Any] | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    promoted_template_ids: tuple[str, ...] = ()
    source_job_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = dataclasses.asdict(self)
        return {
            "draftId": value["draft_id"],
            "name": self.name,
            "outputSchemaId": self.output_schema_id,
            "version": self.version,
            "templates": list(self.templates),
            "status": self.status,
            "createdAt": self.created_at,
            "basedOnTemplateId": self.based_on_template_id,
            "basedOnDraftId": self.based_on_draft_id,
            "validation": self.validation,
            "approvedAt": self.approved_at,
            "approvedBy": self.approved_by,
            "promotedTemplateIds": list(self.promoted_template_ids),
            "sourceJobId": self.source_job_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TemplateDraft":
        return cls(
            draft_id=str(value["draftId"]),
            name=str(value["name"]),
            output_schema_id=str(value["outputSchemaId"]),
            version=int(value["version"]),
            templates=tuple(value["templates"]),
            status=str(value["status"]),
            created_at=str(value["createdAt"]),
            based_on_template_id=value.get("basedOnTemplateId"),
            based_on_draft_id=value.get("basedOnDraftId"),
            validation=value.get("validation"),
            approved_at=value.get("approvedAt"),
            approved_by=value.get("approvedBy"),
            promoted_template_ids=tuple(value.get("promotedTemplateIds") or ()),
            source_job_id=value.get("sourceJobId"),
        )

    def with_validation(self, report: Mapping[str, Any]) -> "TemplateDraft":
        if self.status in ("approved", "promoted"):
            raise ValueError(
                "approved or promoted drafts are immutable; create a repair draft"
            )
        return dataclasses.replace(
            self,
            status="validated" if report["passed"] else "draft",
            validation=report,
            approved_at=None,
            approved_by=None,
        )

    def approve(
        self, validation_id: str, approved_by: str, approved_at: str
    ) -> "TemplateDraft":
        if self.status != "validated":
            raise ValueError("only a validated draft can be approved")
        if not self.validation or not self.validation.get("passed"):
            raise ValueError("only a passing validated draft can be approved")
        if self.validation.get("validationId") != validation_id:
            raise ValueError("validation_id does not identify the latest validation")
        if not approved_by.strip():
            raise ValueError("approved_by must identify the approving actor")
        return dataclasses.replace(
            self,
            status="approved",
            approved_at=approved_at,
            approved_by=approved_by.strip(),
        )

    def promote(self, template_ids: tuple[str, ...]) -> "TemplateDraft":
        if self.status != "approved":
            raise ValueError("a draft must be explicitly approved before promotion")
        if len(template_ids) != len(self.templates):
            raise ValueError("promotion must identify every draft template")
        return dataclasses.replace(
            self, status="promoted", promoted_template_ids=template_ids
        )
