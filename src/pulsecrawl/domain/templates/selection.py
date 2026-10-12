"""Deterministic template applicability and precedence policy."""

from pulsecrawl.domain.crawling.urls import (
    template_scope_matches,
    matching_url_pattern_specificity,
)


class TemplateSelection:
    @staticmethod
    def applicable(extractors, source_url):
        """URL-pattern scopes first, then host scopes, then unscoped fallbacks.

        Declaration order remains stable within each tier.
        """
        url_scoped = []
        host_scoped = []
        unscoped = []
        for pair in extractors:
            template = pair[0]
            if template.scope is None:
                unscoped.append(pair)
                continue
            if not template_scope_matches(
                source_url,
                hosts=template.scope.hosts,
                url_patterns=template.scope.url_patterns,
            ):
                continue
            if template.scope.url_patterns:
                url_scoped.append(
                    (
                        matching_url_pattern_specificity(
                            source_url, template.scope.url_patterns
                        ),
                        pair,
                    )
                )
            else:
                host_scoped.append(pair)
        # Python's sort is stable, so declaration order remains the tie-breaker
        # for a site's JSON-LD/meta/CSS entries that share the same scope.
        url_scoped.sort(key=lambda item: item[0], reverse=True)
        return [pair for _specificity, pair in url_scoped] + host_scoped + unscoped
