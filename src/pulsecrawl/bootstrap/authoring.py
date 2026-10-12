"""Local composition for template authoring and validation."""

import secrets
from pulsecrawl.domain.templates.authoring import (
    RepresentativePage,
    PageInspection,
    TemplateDraft,
)
from pulsecrawl.adapters.outbound.html.inspection import inspect_page
from pulsecrawl.adapters.outbound.html.extraction import HtmlExtractorRegistry
from pulsecrawl.application.templates.validation import (
    validate_template_stack as _validate,
)
from pulsecrawl.application.templates.authoring import TemplateAuthoringService


def _identifier(prefix):
    return f"{prefix}_{secrets.token_hex(10)}"


def validate_template_stack(*args, **kwargs):
    return _validate(
        *args, registry=HtmlExtractorRegistry(), id_factory=_identifier, **kwargs
    )


class WorkspaceTemplateAuthoring(TemplateAuthoringService):
    def __init__(self, workspace):
        from pulsecrawl.adapters.outbound.filesystem.drafts import (
            JsonDraftRepository,
            JsonRepresentativePages,
        )
        from pulsecrawl.adapters.outbound.sqlite.clock import utc_now

        super().__init__(
            drafts=JsonDraftRepository(workspace.path),
            schemas=workspace.schemas,
            templates=workspace.templates,
            jobs=workspace.jobs,
            executions=workspace.executions,
            pages=JsonRepresentativePages(workspace.path),
            inspector=inspect_page,
            validator=validate_template_stack,
            now=utc_now,
            id_factory=_identifier,
        )
