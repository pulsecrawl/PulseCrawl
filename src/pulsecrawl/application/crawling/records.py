"""Turn resolved raw fields into typed records with provenance."""

from pulsecrawl.domain.crawling.model import Record
from pulsecrawl.domain.templates.coercion import coerce, CoercionError
from pulsecrawl.application.templates.resolution import (
    TemplateResolution,
    TemplateResolver,
)


class RecordExtractor:
    def __init__(self, resolver: TemplateResolver):
        self._resolver = resolver

    def extract(
        self, intent, extractors, system_extractors, body, source_url, fetched_at
    ) -> tuple[list[Record], TemplateResolution]:
        resolution = self._resolver.resolve(
            extractors, system_extractors, body, source_url
        )
        base_raw, base_template, match_tier = (
            resolution.records,
            resolution.winner,
            resolution.match_tier,
        )
        records: list[Record] = []
        for raw in base_raw:
            fields: dict[str, object] = {}
            for field_spec in intent.schema.fields:
                raw_value = raw.get(field_spec.field_id)
                if raw_value is None:
                    fields[field_spec.name] = None
                    continue
                try:
                    fields[field_spec.name] = coerce(
                        raw_value, field_spec.type, base_url=source_url
                    )
                except CoercionError:
                    fields[field_spec.name] = None
            required_names = {
                spec.name
                for field_id in (base_template.required_fields if base_template else ())
                if (spec := intent.schema.by_id(field_id)) is not None
            }
            if required_names and any(fields[name] is None for name in required_names):
                continue
            if any(v is not None for v in fields.values()):
                records.append(
                    Record(
                        fields=fields,
                        source_url=source_url,
                        fetched_at=fetched_at,
                        template_id=base_template.template_id
                        if base_template
                        else None,
                        template_origin=base_template.origin if base_template else None,
                        match_tier=match_tier,
                    )
                )
        return records, resolution
