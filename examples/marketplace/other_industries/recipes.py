"""URL-scoped product recipes spanning 20 non-apparel, non-grocery verticals.

The module is data-only: importing it performs no network requests and creates
no PulseCrawl resources.  Authored templates are included only where the
research survey observed their mapped values in permitted raw HTML.  Sources
without a row-safe raw sample remain seed-only so the proposed automatic system
template fallback can classify them as ``system_fallback`` or ``unmatched``.
"""

from __future__ import annotations

from typing import Any, Mapping


CUSTOM_FIELDS = (
    ("product_name", "string", "product or listing title"),
    ("canonical_url", "url", "canonical product URL"),
    ("description", "string", "public product description"),
    ("brand", "string", "product brand or manufacturer"),
    ("sku", "string", "seller stock-keeping unit"),
    ("mpn", "string", "manufacturer part or model number"),
    ("gtin", "string", "UPC, EAN, ISBN, or other GTIN"),
    ("category", "string", "published product category"),
    ("image_url", "url", "primary product image"),
    ("price", "number", "current public offer price"),
    ("currency", "string", "offer currency"),
    ("availability", "string", "published stock status"),
    ("condition", "string", "published item condition"),
    ("rating", "number", "aggregate rating value"),
    ("review_count", "number", "aggregate review or rating count"),
    ("specifications_text", "string", "flattened public specifications"),
    ("seller", "string", "storefront publishing the offer"),
    ("industry", "string", "cross-industry source classification"),
)

SCHEMA_NAME = "cross-industry public products v1"
DATASET_NAME = "marketplace-other-industries"
SCOPE = {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 1_000_000, "maxDepth": 6}


def _ids(field_ids: Mapping[str, str] | None) -> dict[str, str]:
    names = [name for name, _type, _description in CUSTOM_FIELDS]
    resolved = {name: name for name in names}
    if field_ids:
        missing = sorted(set(names).difference(field_ids))
        if missing:
            raise ValueError(f"missing cross-industry field IDs: {missing}")
        resolved.update(field_ids)
    return resolved


def _product_jsonld(F: Mapping[str, str]) -> dict[str, Any]:
    """Product and ProductGroup expressions supported by the JSON-LD walker."""
    return {
        "engine": "jsonld",
        "mappings": {
            F["product_name"]: ("Product.name",),
            F["canonical_url"]: ("Product.url", "Product.offers.url", "Product.@id"),
            F["description"]: ("Product.description",),
            F["brand"]: ("Product.brand.name", "Product.brand"),
            F["sku"]: ("Product.sku", "Product.productID"),
            F["mpn"]: ("Product.mpn", "Product.model"),
            F["gtin"]: (
                "Product.gtin14",
                "Product.gtin13",
                "Product.gtin12",
                "Product.gtin8",
                "Product.gtin",
            ),
            F["category"]: ("Product.category",),
            F["image_url"]: ("Product.image.url", "Product.image"),
            F["price"]: (
                "Product.offers.price",
                "Product.offers.lowPrice",
                "Product.offers.priceSpecification.price",
            ),
            F["currency"]: (
                "Product.offers.priceCurrency",
                "Product.offers.priceSpecification.priceCurrency",
            ),
            F["availability"]: ("Product.offers.availability",),
            F["condition"]: ("Product.offers.itemCondition",),
            F["rating"]: ("Product.aggregateRating.ratingValue",),
            F["review_count"]: (
                "Product.aggregateRating.reviewCount",
                "Product.aggregateRating.ratingCount",
            ),
        },
    }


def _product_meta(F: Mapping[str, str], seller: str, industry: str) -> dict[str, Any]:
    return {
        "engine": "meta",
        "mappings": {
            F["product_name"]: ("og:title", "twitter:title", "<title>"),
            F["canonical_url"]: ("og:url",),
            F["description"]: ("og:description", "twitter:description", "description"),
            F["image_url"]: ("og:image:secure_url", "og:image", "twitter:image"),
            F["price"]: ("product:price:amount", "og:price:amount"),
            F["currency"]: ("product:price:currency", "og:price:currency"),
            F["availability"]: ("product:availability",),
            # The meta engine rejects literal-only matches. Host/path scoping
            # then makes these provenance constants safe.
            F["seller"]: ("og:site_name", f"literal:{seller}"),
            F["industry"]: (f"literal:{industry}",),
        },
    }


def _product_css(
    F: Mapping[str, str], mappings: Mapping[str, tuple[str, ...]]
) -> dict[str, Any]:
    # Do not add literals here: the current CSS engine can emit a literal-only
    # record. Every CSS match below therefore proves product-page content.
    return {
        "engine": "css",
        "mappings": {F[field]: expressions for field, expressions in mappings.items()},
    }


SOURCE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "framework",
        "name": "Framework Marketplace",
        "industry": "consumer electronics",
        "seed": "https://frame.work/marketplace",
        "hosts": ["frame.work"],
        "url_patterns": ["/marketplace/**"],
        "sample_url": "https://frame.work/marketplace",
        "authored": False,
        "research_status": "raw_listing_has_client_data_but_no_row_safe_product_markup",
    },
    {
        "key": "moment",
        "name": "Moment",
        "industry": "photo and video",
        "seed": "https://www.shopmoment.com/gear",
        "hosts": ["shopmoment.com"],
        "url_patterns": ["/products/**"],
        "sample_url": "https://www.shopmoment.com/products/moment-cinebloom-diffusion-filters",
        "profile": "moment",
    },
    {
        "key": "ikea",
        "name": "IKEA",
        "industry": "furniture",
        "seed": "https://www.ikea.com/us/en/cat/products-products/",
        "hosts": ["ikea.com"],
        "url_patterns": ["/us/en/p/**"],
        "sample_url": "https://www.ikea.com/us/en/p/sektion-maximera-base-cabinet-p-out-storage-2-drawer-white-ringhult-white-s99034143/",
        "profile": "ikea",
    },
    {
        "key": "barnes_noble",
        "name": "Barnes & Noble",
        "industry": "books",
        "seed": "https://www.barnesandnoble.com/b/books/_/N-29Z8q8",
        "hosts": ["barnesandnoble.com"],
        "url_patterns": ["/w/**"],
        "sample_url": "https://www.barnesandnoble.com/w/the-great-gatsby-and-other-classic-works-f-scott-fitzgerald/1131596848",
        "profile": "barnes_noble",
    },
    {
        "key": "glossier",
        "name": "Glossier",
        "industry": "beauty",
        "seed": "https://www.glossier.com/pages/skincare",
        "hosts": ["glossier.com"],
        "url_patterns": ["/products/**"],
        "sample_url": "https://www.glossier.com/products/futuredew",
        "profile": "glossier",
    },
    {
        "key": "wild_one",
        "name": "Wild One",
        "industry": "pet care",
        "seed": "https://wildone.com/collections/dog",
        "hosts": ["wildone.com"],
        "url_patterns": ["/products/**"],
        "sample_url": "https://wildone.com/products/dog-toy-set",
        "profile": "wild_one",
    },
    {
        "key": "chemical_guys",
        "name": "Chemical Guys",
        "industry": "automotive care",
        "seed": "https://www.chemicalguys.com/collections/car-wash-products",
        "hosts": ["chemicalguys.com"],
        "url_patterns": ["/products/**"],
        "sample_url": "https://www.chemicalguys.com/products/honeydew-snow-foam-extreme-suds-cleansing-wash-shampoo",
        "profile": "chemical_guys",
    },
    {
        "key": "sweetwater",
        "name": "Sweetwater",
        "industry": "musical instruments",
        "seed": "https://www.sweetwater.com/shop/guitars/",
        "hosts": ["sweetwater.com"],
        "url_patterns": ["/store/detail/**"],
        "sample_url": "https://www.sweetwater.com/store/detail/GD37CE12PW--takamine-gd-37ce-pw-12-string-acoustic-electric-guitar-pearl-white",
        "profile": "sweetwater",
    },
    {
        "key": "solo_stove",
        "name": "Solo Stove",
        "industry": "outdoor living",
        "seed": "https://www.solostove.com/us/en-us/c/smokeless-fire-pits",
        "hosts": ["solostove.com"],
        "url_patterns": ["/us/en-us/p/**"],
        "sample_url": "https://www.solostove.com/us/en-us/p/PRO-BONFIRE-2.0",
        "profile": "solo_stove",
    },
    {
        "key": "lego",
        "name": "LEGO",
        "industry": "toys",
        "seed": "https://www.lego.com/en-us/categories/all-sets",
        "hosts": ["lego.com"],
        "url_patterns": ["/en-us/product/**"],
        "sample_url": "https://www.lego.com/en-us/product/millennium-falcon-75375",
        "profile": "lego",
        "research_status": "authored_from_permitted_sample_later_fetch_intermittently_403",
    },
    {
        "key": "grovemade",
        "name": "Grovemade",
        "industry": "office accessories",
        "seed": "https://grovemade.com/shop/",
        "hosts": ["grovemade.com"],
        "url_patterns": ["/product/**"],
        "sample_url": "https://grovemade.com/product/notepad/",
        "profile": "grovemade",
    },
    {
        "key": "michaels",
        "name": "Michaels",
        "industry": "arts and crafts",
        "seed": "https://www.michaels.com/shop/crafts-hobbies",
        "hosts": ["michaels.com"],
        "url_patterns": ["/product/**"],
        "sample_url": "https://www.michaels.com/product/acrylic-paint-value-pack-by-craft-smart-10278752",
        "authored": False,
        "research_status": "robots_allowed_but_raw_product_returned_403",
    },
    {
        "key": "made_in",
        "name": "Made In",
        "industry": "restaurant cookware",
        "seed": "https://madeincookware.com/collections/proven-to-perform",
        "hosts": ["madeincookware.com"],
        "url_patterns": ["/products/**"],
        "sample_url": "https://madeincookware.com/products/dinner-plates",
        "profile": "made_in",
    },
    {
        "key": "carewell",
        "name": "Carewell",
        "industry": "medical supplies",
        "seed": "https://www.carewell.com/catalog/",
        "hosts": ["carewell.com"],
        "url_patterns": ["/product/**"],
        "sample_url": "https://www.carewell.com/product/attends-adult-diapers-with-tabs-heavy/?sku=DDA40-CS60",
        "profile": "carewell",
    },
    {
        "key": "blue_nile",
        "name": "Blue Nile",
        "industry": "fine jewelry",
        "seed": "https://www.bluenile.com/jewelry/rings",
        "hosts": ["bluenile.com"],
        "url_patterns": ["/jewelry/**", "/wedding-rings/**"],
        "sample_url": "https://www.bluenile.com/jewelry/rings",
        "profile": "blue_nile",
        "meta": False,
        "css": False,
    },
    {
        "key": "tractor_supply",
        "name": "Tractor Supply",
        "industry": "farm and ranch",
        "seed": "https://www.tractorsupply.com/tsc/catalog/livestock-feed",
        "hosts": ["tractorsupply.com"],
        "url_patterns": ["/tsc/product/**"],
        "sample_url": "https://www.tractorsupply.com/tsc/product/producer-s-pride-12-percent-sweet-feed-50-lb",
        "authored": False,
        "research_status": "robots_request_timed_out_no_raw_product_fetch_made",
    },
    {
        "key": "lakeshore",
        "name": "Lakeshore Learning",
        "industry": "education supplies",
        "seed": "https://www.lakeshorelearning.com/products/",
        "hosts": ["lakeshorelearning.com"],
        "url_patterns": ["/products/**"],
        "sample_url": "https://www.lakeshorelearning.com/products/",
        "authored": False,
        "research_status": "raw_directory_has_no_row_safe_product_entities",
    },
    {
        "key": "trek",
        "name": "Trek",
        "industry": "bicycles",
        "seed": "https://www.trekbikes.com/us/en_US/bikes/road-bikes/performance-road-bikes/domane/domane-al/c/B221-5/",
        "hosts": ["trekbikes.com"],
        "url_patterns": ["/us/en_US/bikes/**/p/*/**"],
        "sample_url": "https://www.trekbikes.com/us/en_US/bikes/road-bikes/performance-road-bikes/domane/domane-al/c/B221-5/",
        "authored": False,
        "research_status": "listing_products_are_embedded_attributes_not_row_safe_for_current_css_engine",
    },
    {
        "key": "golf_galaxy",
        "name": "Golf Galaxy",
        "industry": "golf equipment",
        "seed": "https://www.golfgalaxy.com/f/shop-drivers",
        "hosts": ["golfgalaxy.com"],
        "url_patterns": ["/p/**"],
        "sample_url": "https://www.golfgalaxy.com/f/shop-drivers",
        "authored": False,
        "research_status": "robots_endpoint_returned_403_no_raw_page_fetch_made",
    },
    {
        "key": "flinn",
        "name": "Flinn Scientific",
        "industry": "laboratory supplies",
        "seed": "https://www.flinnsci.com/products/apparatus/laboratory-equipment/",
        "hosts": ["flinnsci.com"],
        "url_patterns": ["/products/**/product-*/**"],
        "sample_url": "https://www.flinnsci.com/products/apparatus/laboratory-equipment/product-12115/",
        "profile": "flinn",
    },
)


CSS_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "moment": {
        "product_name": ("main h1",),
        "image_url": ("meta[property='og:image']@content",),
    },
    "ikea": {
        "product_name": ("main h1",),
        "price": ("[data-product-price]@data-product-price",),
        "image_url": ("meta[property='og:image']@content",),
    },
    "barnes_noble": {
        "product_name": ("h1.product__title", "main h1"),
        "description": (
            "#accordion-content-overview .leading-5",
            ".product-description",
        ),
        "price": (".product-price",),
        "image_url": ("meta[property='og:image']@content",),
    },
    "glossier": {
        "product_name": ("main h1",),
        "price": ("[itemprop='price']@content",),
        "currency": ("[itemprop='priceCurrency']@content",),
        "image_url": ("meta[property='og:image:secure_url']@content",),
    },
    "wild_one": {
        "product_name": ("main h1",),
        "description": (".vg-accordion-content",),
        "price": ("[data-price]@data-price",),
        "currency": ("[data-currency]@data-currency",),
        "image_url": ("meta[property='og:image:secure_url']@content",),
    },
    "chemical_guys": {
        "product_name": ("main h1",),
        "sku": ("[data-sku]@data-sku",),
        "description": ("[id^='Toggle-'][id$='-details']",),
        "price": ("[data-price]@data-price",),
        "currency": ("[data-currency]@data-currency",),
        "image_url": ("meta[property='og:image:secure_url']@content",),
    },
    "sweetwater": {
        "product_name": ("h1.product-title", "main h1"),
        "description": (".webtext-block--mixed-content",),
        "price": (".product-price",),
    },
    "solo_stove": {
        "product_name": ("main h1",),
        "description": (".chakra-accordion__panel",),
        "image_url": ("meta[property='og:image']@content",),
    },
    "lego": {
        "product_name": ("main h1",),
        "description": ("[class^='ProductSpecifications_copy']",),
        "image_url": ("meta[property='og:image']@content",),
    },
    "grovemade": {
        "product_name": ("h1",),
        "image_url": ("meta[property='og:image']@content",),
    },
    "made_in": {
        "product_name": ("main h1",),
        "description": ("[data-test-id='pdp-short-description']",),
        "image_url": ("meta[property='og:image']@content",),
    },
    "carewell": {
        "product_name": ("main h1",),
        "description": (".TabContent.active .col-sm-7",),
        "price": ("[data-price]@data-price",),
        "currency": ("[data-currency]@data-currency",),
        "image_url": ("meta[property='og:image']@content",),
    },
    "blue_nile": {},
    "flinn": {
        "product_name": ("h1",),
    },
}


def build_sources(field_ids: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Return 20 seeds and only raw-HTML-backed scoped templates."""
    F = _ids(field_ids)
    sources: list[dict[str, Any]] = []
    for raw_spec in SOURCE_SPECS:
        spec = dict(raw_spec)
        templates: list[dict[str, Any]] = []
        if spec.get("authored", True):
            templates.append(
                {
                    "name": f"tmpl: {spec['name']} · product-jsonld",
                    **_product_jsonld(F),
                }
            )
            if spec.get("css", True):
                templates.append(
                    {
                        "name": f"tmpl: {spec['name']} · product-css",
                        **_product_css(F, CSS_PROFILES[spec["profile"]]),
                    }
                )
            if spec.get("meta", True):
                templates.append(
                    {
                        "name": f"tmpl: {spec['name']} · product-meta",
                        **_product_meta(F, spec["name"], spec["industry"]),
                    }
                )
        spec["templates"] = templates
        sources.append(spec)
    return sources


def build_stack_entries(
    sources: list[dict[str, Any]], template_ids_by_name: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Build ordered entries for the proposed SDK ``template_stack`` field."""
    entries: list[dict[str, Any]] = []
    for source in sources:
        for template in source["templates"]:
            entries.append(
                {
                    "template_id": template_ids_by_name[template["name"]],
                    "hosts": list(source["hosts"]),
                    "url_patterns": list(source["url_patterns"]),
                }
            )
    return entries


def seeds() -> list[str]:
    """Return every vertical seed, including automatic-system-fallback cases."""
    return [spec["seed"] for spec in SOURCE_SPECS]


SOURCES = build_sources()
