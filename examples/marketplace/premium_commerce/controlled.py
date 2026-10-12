"""Original synthetic inputs: no network calls and no copied merchant HTML."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
from urllib.parse import urlsplit

from pulsecrawl.domain.crawling.model import FetchResult

from .recipes import FICTIONAL_SOURCES as SOURCES, Source


OBSERVATIONS = (
    datetime(2026, 10, 11, 12, tzinfo=timezone.utc),
    datetime(2026, 10, 11, 13, tzinfo=timezone.utc),
)


def product_html(source: Source, execution: int, *, layout: str = "jsonld") -> str:
    """Fully fictional prices, identifiers, store names, and .example URLs."""
    if not source.host.endswith(".example"):
        raise ValueError("synthetic product inputs require a fictional .example source")
    if execution not in (0, 1):
        raise ValueError("controlled fixture has exactly two observations")
    price = "120.00" if execution == 0 else "99.00"
    name = f"SYNTHETIC {source.store} product - not a live price"
    url = escape(source.sample_url, quote=True)
    title = f'<meta property="og:title" content="{escape(name, quote=True)}">'
    if layout == "meta":
        return (
            title
            + f'''<meta property="og:url" content="{url}">
        <meta property="product:price:amount" content="{price}">
        <meta property="product:price:currency" content="USD">'''
        )
    if layout == "css":
        return (
            title
            + f'''<main itemscope itemtype="https://schema.org/Product">
        <h1 itemprop="name">{escape(name)}</h1>
        <meta itemprop="price" content="{price}">
        <meta itemprop="priceCurrency" content="USD">
        <meta itemprop="sku" content="SYNTHETIC-{source.slug}-M-BLACK"></main>'''
        )
    entity = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "url": source.sample_url,
        "brand": {"name": "SYNTHETIC brand"},
        "productID": f"SYNTHETIC-{source.slug}",
        "sku": f"SYNTHETIC-{source.slug}-M-BLACK",
        "color": "SYNTHETIC Black",
        "size": "SYNTHETIC M",
        "offers": {
            "@type": "Offer",
            "price": price,
            "priceCurrency": "USD",
            "url": source.sample_url,
            "availability": "https://schema.org/InStock",
        },
    }
    if layout == "range":
        entity["offers"] = {
            "@type": "AggregateOffer",
            "lowPrice": "80.00",
            "highPrice": "150.00",
            "priceCurrency": "USD",
        }
    if layout not in ("jsonld", "graph", "range", "malformed"):
        raise ValueError("unknown controlled layout")
    data = {"@graph": [entity]} if layout == "graph" else entity
    script = "{ malformed" if layout == "malformed" else json.dumps(data)
    suffix = (
        product_html(source, execution, layout="css")
        if layout == "malformed"
        else title
    )
    return f'<script type="application/ld+json">{script}</script>' + suffix


class ControlledFetcher:
    """Only serves the selected exact URLs and synthetic robots documents.

    Fictional .example URLs exercise scope matching without contacting websites.
    Unknown URLs fail closed; there is no fallback HTTP client.
    """

    def __init__(self, execution: int):
        if execution not in (0, 1):
            raise ValueError("expected controlled observation 0 or 1")
        self.execution = execution
        self.calls: list[str] = []
        self.pages = {s.sample_url: product_html(s, execution) for s in SOURCES}
        self.origins = {"https://" + urlsplit(s.sample_url).netloc for s in SOURCES}

    async def fetch(self, url: str, *, user_agent: str) -> FetchResult:
        self.calls.append(url)
        if len(self.calls) > 20:
            raise RuntimeError("controlled execution request cap exceeded")
        if url in {origin + "/robots.txt" for origin in self.origins}:
            body, status = "User-agent: *\nAllow: /\n", 200
        else:
            body = self.pages.get(url)
            status = 200 if body is not None else 404
        return FetchResult(
            url=url,
            final_url=url,
            status=status,
            headers={"content-type": "text/html"},
            body=body,
            error=None if status == 200 else "outside controlled input set",
            fetched_at=OBSERVATIONS[self.execution],
            body_bytes=len((body or "").encode()),
        )
