"""Shared runtime/authoring resolution; parser strategies are supplied by callers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pulsecrawl.domain.crawling.model import TemplateSpec
from pulsecrawl.domain.templates.selection import TemplateSelection


@dataclass(frozen=True)
class TemplateResolution:
    records: list[dict[str, Any]]
    winner: TemplateSpec | None
    match_tier: str | None
    matched: list
    authored_matches: list
    applicable: list
    field_provenance: list[dict[str, str]]
    conflicts: list[dict[str, Any]]


class TemplateResolver:
    """First matching template wins; later singleton results enrich missing fields."""

    def resolve(
        self, authored, systems, body: str, source_url: str
    ) -> TemplateResolution:
        applicable = TemplateSelection.applicable(authored, source_url)
        authored_matches = self._matches(applicable, body)
        selected = authored_matches
        tier = None
        if selected:
            tier = "scoped" if selected[0][0].scope is not None else "stack_fallback"
        elif systems:
            selected = self._matches(
                TemplateSelection.applicable(systems, source_url), body
            )
            if selected:
                tier = "system_fallback"
        records, winner, provenance, conflicts = self._merge(selected)
        return TemplateResolution(
            records,
            winner,
            tier,
            selected,
            authored_matches,
            applicable,
            provenance,
            conflicts,
        )

    @staticmethod
    def _matches(extractors, body):
        return [
            (template, rows)
            for template, extract in extractors
            if (rows := extract(body, template.mappings))
        ]

    @staticmethod
    def _merge(selected):
        if not selected:
            return [], None, [], []
        winner, winner_rows = selected[0]
        records = [dict(row) for row in winner_rows]
        provenance = [{key: winner.template_id for key in row} for row in records]
        conflicts = []
        for template, rows in selected[1:]:
            if len(rows) != 1:
                continue
            for record, sources in zip(records, provenance):
                for key, value in rows[0].items():
                    if key not in record:
                        record[key] = value
                        sources[key] = template.template_id
                    elif record[key] != value:
                        conflicts.append(
                            {
                                "fieldId": key,
                                "winnerTemplateId": sources[key],
                                "otherTemplateId": template.template_id,
                            }
                        )
        return records, winner, provenance, conflicts

    @classmethod
    def apply_stack(cls, extractors, body):
        records, winner, _, _ = cls._merge(cls._matches(extractors, body))
        return records, winner
