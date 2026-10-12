"""Provisional product templates for ten selected storefronts.

Scopes are based on official product URLs, not an assertion that those sites
permit live crawling or expose this markup to a non-browser client. The shared
JSON-LD/semantic-markup strategies are verified against controlled fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from pulsecrawl.domain.crawling.urls import template_scope_matches


@dataclass(frozen=True)
class Source:
    slug: str
    store: str
    host: str
    paths: tuple[str, ...]
    sample_url: str
    terms_url: str


SOURCES = (
    Source(
        "lululemon",
        "lululemon",
        "shop.lululemon.com",
        ("/p/*/*",),
        "https://shop.lululemon.com/p/align-pant-2/i4goprzy85?color=77648&locale=en_US",
        "https://shop.lululemon.com/help/legal/terms-of-use/",
    ),
    Source(
        "alo",
        "Alo Yoga",
        "www.aloyoga.com",
        ("/products/*",),
        "https://www.aloyoga.com/products/w5561r-high-waist-airlift-legging-black?variant=22032629170294",
        "https://www.aloyoga.com/pages/terms-of-use",
    ),
    Source(
        "nordstrom",
        "Nordstrom",
        "www.nordstrom.com",
        ("/s/*/[0-9]*",),
        "https://www.nordstrom.com/s/alo-airbrush-high-waist-leggings/5538850",
        "https://www.nordstrom.com/browse/customer-service/policy/terms-conditions",
    ),
    Source(
        "revolve",
        "REVOLVE",
        "www.revolve.com",
        ("/*/dp/*/",),
        "https://www.revolve.com/nike-air-footscape-woven-og-sneakers-in-black-white/dp/NIKR-MZ933/",
        "https://www.revolve.com/r/infoTerms.jsp",
    ),
    Source(
        "nike",
        "Nike",
        "www.nike.com",
        ("/t/*/*",),
        "https://www.nike.com/t/air-force-1-07-ayakkab%C4%B1s%C4%B1-rWtqPn/CW2288-001",
        "https://agreementservice.svs.nike.com/gb/en_gb/rest/agreement?agreementType=termsOfUse&uxId=com.nike&country=US&language=en&requestType=redirect",
    ),
    Source(
        "adidas",
        "Adidas",
        "www.adidas.com",
        ("/us/*/*.html",),
        "https://www.adidas.com/us/samba-og-shoes/B75806.html",
        "https://www.adidas.com/us/help/us-company-information/what-are-the-terms-and-conditions",
    ),
    Source(
        "new-balance",
        "New Balance",
        "www.newbalance.com",
        ("/pd/*/*.html",),
        "https://www.newbalance.com/pd/made-in-usa-990v6/M990NV6-D-11.html",
        "https://www.newbalance.com/terms.html",
    ),
    Source(
        "on",
        "On",
        "www.on.com",
        ("/en-us/products/*/mens/*", "/en-us/products/*/womens/*"),
        "https://www.on.com/en-us/products/cloudmonster-2-m-3mf3115/mens/ivory-steel-shoes-3MF31154571",
        "https://www.on.com/en-us/terms-and-conditions",
    ),
    Source(
        "hoka",
        "HOKA",
        "www.hoka.com",
        ("/en/us/*/*/[0-9]*.html",),
        "https://www.hoka.com/en/us/mens-everyday-running-gear/clifton-11/1176572.html?dwvar_1176572_color=BKCS",
        "https://www.hoka.com/en/us/terms-and-conditions.html",
    ),
    Source(
        "ugg",
        "UGG",
        "www.ugg.com",
        ("/women-*/*/[0-9]*.html", "/men-*/*/[0-9]*.html"),
        "https://www.ugg.com/women-boots/classic-ultra-mini/1116109.html?dwvar_1116109_color=CRBO&dwvar_1116109_size=11",
        "https://www.ugg.com/terms-and-conditions.html",
    ),
)
BY_SLUG = {source.slug: source for source in SOURCES}

# Fictional inputs must never carry real retailer identities or product URLs.
FICTIONAL_SOURCES = tuple(
    Source(
        f"shop-{i:02d}",
        f"Fictional Store {i:02d}",
        f"shop-{i:02d}.example",
        ("/products/*",),
        f"https://shop-{i:02d}.example/products/item-{i:02d}?color=black&size=m",
        f"https://shop-{i:02d}.example/policies",
    )
    for i in range(1, 11)
)

# Nullable fields: absence must remain absence, not an invented price, USD,
# brand, variant or availability. Runtime adds _source_url/_crawled_at/etc.
CUSTOM_FIELDS = (
    ("name", "string", "Advertised product name"),
    ("store", "string", "Storefront; not necessarily the product brand"),
    ("brand", "string", "Brand stated by the page"),
    ("product_id", "string", "Page product identifier, if supplied"),
    ("sku", "string", "Product-level SKU, if supplied"),
    ("gtin", "string", "Advertised GTIN; no cross-store matching inferred"),
    ("product_url", "url", "Page-declared product URL; may omit variant context"),
    ("offer_url", "url", "First structured offer URL, if supplied"),
    ("offer_sku", "string", "First structured offer SKU, if supplied"),
    ("current_price", "number", "First structured offer or semantic page price"),
    ("regular_price", "number", "Reserved: no validated compare-at mapping yet"),
    ("low_price", "number", "Aggregate offer minimum; not the selected price"),
    ("high_price", "number", "Aggregate offer maximum; not the selected price"),
    ("currency", "string", "Explicit currency; never inferred from a symbol"),
    ("availability", "string", "Page-level or first-offer availability only"),
    ("color", "string", "Product color stated by markup, if supplied"),
    ("size", "string", "Product size stated by markup, if supplied"),
    ("group_id", "string", "Product group identifier; not a unique variant identifier"),
)


def field_ids() -> dict[str, str]:
    return {name: f"fld_premium_{name}" for name, _, _ in CUSTOM_FIELDS}


def source_for_url(url: str) -> Source:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError(
            "use a public HTTPS product URL without credentials or custom ports"
        )
    for source in SOURCES:
        if template_scope_matches(url, hosts=(source.host,), url_patterns=source.paths):
            return source
    raise ValueError("URL is outside the ten selected product scopes")


def build_recipes(
    ids: Mapping[str, str] | None = None, *, sources=SOURCES
) -> list[dict]:
    fields = dict(ids or field_ids())
    if set(fields) != {name for name, _, _ in CUSTOM_FIELDS}:
        raise ValueError("provide exactly the shared commerce field names")
    paths = {
        "name": ("Product.name",),
        "brand": ("Product.brand.name", "Product.brand"),
        "product_id": ("Product.productID", "Product.mpn"),
        "sku": ("Product.sku",),
        "gtin": (
            "Product.gtin13",
            "Product.gtin12",
            "Product.gtin",
        ),
        "product_url": ("Product.url",),
        "offer_url": ("Product.offers.url",),
        "offer_sku": ("Product.offers.sku",),
        "current_price": ("Product.offers.price",),
        "low_price": ("Product.offers.lowPrice",),
        "high_price": ("Product.offers.highPrice",),
        "currency": ("Product.offers.priceCurrency",),
        "availability": ("Product.offers.availability",),
        "color": ("Product.color",),
        "size": ("Product.size", "Product.size.name"),
        "group_id": ("Product.productGroupID",),
    }
    recipes = []
    for source in sources:
        strategies = (
            ("jsonld", {fields[key]: value for key, value in paths.items()}),
            (
                "css",
                {
                    fields["name"]: ("[itemtype$='/Product'] [itemprop='name']",),
                    fields["current_price"]: (
                        "[itemtype$='/Product'] [itemprop='price']@content",
                    ),
                    fields["currency"]: (
                        "[itemtype$='/Product'] [itemprop='priceCurrency']@content",
                    ),
                    fields["sku"]: ("[itemtype$='/Product'] [itemprop='sku']@content",),
                },
            ),
            (
                "meta",
                {
                    fields["name"]: ("og:title",),
                    fields["product_url"]: ("og:url",),
                    fields["current_price"]: (
                        "product:price:amount",
                        "og:price:amount",
                    ),
                    fields["currency"]: ("product:price:currency", "og:price:currency"),
                    fields["availability"]: ("product:availability",),
                    fields["brand"]: ("product:brand",),
                    fields["store"]: (f"literal:{source.store}",),
                },
            ),
        )
        recipes.append(
            {
                "slug": source.slug,
                "store": source.store,
                "sampleUrl": source.sample_url,
                "liveStatus": "disabled-provisional",
                "templateStack": [
                    {
                        "template_id": f"premium_{source.slug}_{engine}",
                        "engine": engine,
                        "mappings": mappings,
                        "hosts": [source.host],
                        "url_patterns": list(source.paths),
                    }
                    for engine, mappings in strategies
                ],
            }
        )
    return recipes
