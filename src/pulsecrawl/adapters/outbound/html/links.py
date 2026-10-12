"""HTML link discovery adapter."""

from selectolax.parser import HTMLParser
from pulsecrawl.domain.crawling.urls import normalize_url


def extract_links(html: str, base_url: str) -> list[str]:
    """All unique, normalized http(s) links in document order."""
    seen: set[str] = set()
    links: list[str] = []
    tree = HTMLParser(html)
    for anchor in tree.css("a[href]"):
        href = anchor.attributes.get("href")
        if not href:
            continue
        normalized = normalize_url(href, base=base_url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    return links


class HtmlLinkParser:
    def extract_links(self, html: str, base_url: str) -> list[str]:
        return extract_links(html, base_url)
