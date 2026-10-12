"""URL-scoped apparel product recipes for 20 public storefronts.

The recipes are intentionally data-only. ``build_recipes`` accepts the
field-name -> field-id mapping returned while authoring a schema. Leaving it
out retains semantic names, which is convenient for the live validator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


CUSTOM_FIELDS = (
    ("product_id", "string", "storefront product identifier"),
    ("sku", "string", "stock-keeping unit"),
    ("name", "string", "product name"),
    ("url", "url", "canonical product URL"),
    ("description", "string", "product description"),
    ("brand", "string", "product brand"),
    ("category", "string", "merchant or schema.org category"),
    ("color", "string", "advertised color"),
    ("material", "string", "advertised material"),
    ("audience", "string", "advertised gender or audience"),
    ("price", "number", "current offer price"),
    ("low_price", "number", "lowest aggregate-offer price"),
    ("high_price", "number", "highest aggregate-offer price"),
    ("currency", "string", "offer currency"),
    ("availability", "string", "schema.org availability value"),
    ("condition", "string", "schema.org item condition"),
    ("image_url", "url", "primary or social-preview image"),
    ("rating_value", "number", "aggregate rating"),
    ("rating_count", "number", "aggregate rating count"),
)


@dataclass(frozen=True)
class Source:
    slug: str
    brand: str
    seed: str
    hosts: tuple[str, ...]
    url_patterns: tuple[str, ...]
    sample_url: str


SOURCES = (
    Source(
        "allbirds",
        "Allbirds",
        "https://www.allbirds.com/collections/mens-shoes",
        ("allbirds.com",),
        ("/products/**",),
        "https://www.allbirds.com/products/womens-cruiser-canvas-sea-spray",
    ),
    Source(
        "gymshark",
        "Gymshark",
        "https://www.gymshark.com/collections/new-releases",
        ("gymshark.com",),
        ("/products/**",),
        "https://www.gymshark.com/products/gymshark-micro-logo-tank-crop-tops-pink-ss26",
    ),
    Source(
        "fashion-nova",
        "Fashion Nova",
        "https://www.fashionnova.com/collections/new",
        ("fashionnova.com",),
        ("/products/**",),
        "https://www.fashionnova.com/products/zyler-textured-shorts",
    ),
    Source(
        "buck-mason",
        "Buck Mason",
        "https://www.buckmason.com/collections/new-arrivals",
        ("buckmason.com",),
        ("/products/**",),
        "https://www.buckmason.com/products/raw-japanese-selvedge-full-saddle-jean",
    ),
    Source(
        "taylor-stitch",
        "Taylor Stitch",
        "https://www.taylorstitch.com/collections/mens-new-arrivals",
        ("taylorstitch.com",),
        ("/products/**",),
        "https://www.taylorstitch.com/products/the-camp-pant-in-charcoal-wool",
    ),
    Source(
        "tentree",
        "tentree",
        "https://www.tentree.com/collections/new-arrivals",
        ("tentree.com",),
        ("/products/**",),
        "https://www.tentree.com/products/mens-portal-t-shirt-olive-night-green",
    ),
    Source(
        "chubbies",
        "Chubbies",
        "https://www.chubbiesshorts.com/collections/new-arrivals",
        ("chubbiesshorts.com",),
        ("/products/**",),
        "https://www.chubbiesshorts.com/products/the-24-7-365-essential-non-pocket-t-shirt-mhg-1",
    ),
    Source(
        "cuts",
        "CUTS",
        "https://www.cutsclothing.com/collections/new-releases",
        ("cutsclothing.com",),
        ("/products/**",),
        "https://www.cutsclothing.com/products/black-l-s-crew-curve-hem",
    ),
    Source(
        "fresh-clean-threads",
        "Fresh Clean Threads",
        "https://freshcleantees.com/collections/new-arrivals",
        ("freshcleantees.com",),
        ("/products/**",),
        "https://freshcleantees.com/products/mosswood-long-sleeve-crew-neck",
    ),
    Source(
        "true-classic",
        "True Classic",
        "https://www.trueclassictees.com/collections/new-arrivals",
        ("trueclassictees.com",),
        ("/products/**",),
        "https://www.trueclassictees.com/products/womens-oatmeal-ribbed-u-neck-tee",
    ),
    Source(
        "marine-layer",
        "Marine Layer",
        "https://www.marinelayer.com/collections/new",
        ("marinelayer.com",),
        ("/products/**",),
        "https://www.marinelayer.com/products/allison-corduroy-trouser-3",
    ),
    Source(
        "rothys",
        "Rothy's",
        "https://rothys.com/collections/womens-new-arrivals",
        ("rothys.com",),
        ("/products/**",),
        "https://rothys.com/products/womens-max-square-ballerina-revelvet-dark-rodeo",
    ),
    Source(
        "vuori",
        "Vuori",
        "https://vuoriclothing.com/collections/new-arrivals",
        ("vuoriclothing.com",),
        ("/products/**",),
        "https://vuoriclothing.com/products/quarter-crew-v1-sock-2-0-black",
    ),
    Source(
        "outdoor-voices",
        "Outdoor Voices",
        "https://www.outdoorvoices.com/collections/new-arrivals",
        ("outdoorvoices.com",),
        ("/products/**",),
        "https://www.outdoorvoices.com/products/w-rectrek-zip-pant-sandstone",
    ),
    Source(
        "cotopaxi",
        "Cotopaxi",
        "https://www.cotopaxi.com/collections/new-arrivals",
        ("cotopaxi.com",),
        ("/products/**",),
        "https://www.cotopaxi.com/products/vintage-trucker-hat-1",
    ),
    Source(
        "good-american",
        "Good American",
        "https://www.goodamerican.com/collections/new-arrivals",
        ("goodamerican.com",),
        ("/products/**",),
        "https://www.goodamerican.com/products/the-cable-zip-up-chalk",
    ),
    Source(
        "princess-polly",
        "Princess Polly",
        "https://us.princesspolly.com/collections/new-arrivals",
        ("us.princesspolly.com",),
        ("/products/**",),
        "https://us.princesspolly.com/products/after-dark-eco-sequin-mini-dress-black",
    ),
    Source(
        "mavi",
        "Mavi",
        "https://us.mavi.com/collections/new-arrivals",
        ("us.mavi.com",),
        ("/products/**",),
        "https://us.mavi.com/products/one-pocket-button-up-shirt-in-antique-white-1",
    ),
    Source(
        "frank-and-oak",
        "Frank And Oak",
        "https://www.frankandoak.com/collections/women-new-arrivals",
        ("frankandoak.com",),
        ("/products/**",),
        "https://www.frankandoak.com/products/mens-knit-t-shirt-moss-green-2mkt0031fe-moss",
    ),
    Source(
        "teddy-fresh",
        "Teddy Fresh",
        "https://teddyfresh.com/collections/latest-releases",
        ("teddyfresh.com",),
        ("/products/**",),
        "https://teddyfresh.com/products/striped-quarter-sock-3-packs",
    ),
)


def _ids(field_ids: Mapping[str, str] | None) -> dict[str, str]:
    names = [name for name, _type, _description in CUSTOM_FIELDS]
    resolved = {name: name for name in names}
    if field_ids:
        missing = set(names).difference(field_ids)
        if missing:
            raise ValueError(f"missing clothing field ids: {sorted(missing)}")
        resolved.update(field_ids)
    return resolved


def _jsonld(F: Mapping[str, str]) -> dict[str, object]:
    return {
        "engine": "jsonld",
        "mappings": {
            F["product_id"]: ("Product.productID", "Product.mpn"),
            F["sku"]: ("Product.sku",),
            F["name"]: ("Product.name",),
            F["url"]: ("Product.url", "Product.offers.url"),
            F["description"]: ("Product.description",),
            F["brand"]: ("Product.brand.name",),
            F["category"]: ("Product.category",),
            F["color"]: ("Product.color",),
            F["material"]: ("Product.material",),
            F["audience"]: ("Product.audience.suggestedGender",),
            F["price"]: ("Product.offers.price", "Product.offers.lowPrice"),
            F["low_price"]: ("Product.offers.lowPrice",),
            F["high_price"]: ("Product.offers.highPrice",),
            F["currency"]: ("Product.offers.priceCurrency",),
            F["availability"]: ("Product.offers.availability",),
            F["condition"]: ("Product.offers.itemCondition",),
            F["image_url"]: (
                "Product.image.url",
                "Product.primaryImageOfPage.contentUrl",
            ),
            F["rating_value"]: ("Product.aggregateRating.ratingValue",),
            F["rating_count"]: (
                "Product.aggregateRating.ratingCount",
                "Product.aggregateRating.reviewCount",
            ),
        },
    }


def _css(F: Mapping[str, str], brand: str) -> dict[str, object]:
    return {
        "engine": "css",
        "mappings": {
            F["name"]: (
                "h1.product__title",
                "h1.product-title",
                "h1.product-single__title",
                "[data-product-title]",
                "main h1",
            ),
            F["description"]: (
                ".product__description",
                ".product-description",
                ".product-single__description",
                "[data-product-description]",
            ),
            F["sku"]: ("[itemprop='sku']@content", "[data-product-sku]"),
            F["price"]: (
                "[itemprop='price']@content",
                "[data-product-price]@data-product-price",
                ".price-item--sale",
                ".price-item--regular",
            ),
            F["currency"]: ("[itemprop='priceCurrency']@content",),
            F["image_url"]: (
                "meta[property='og:image:secure_url']@content",
                "meta[property='og:image']@content",
            ),
            # This constant is safe because every entry is host + path scoped.
            F["brand"]: (f"literal:{brand}",),
        },
    }


def _meta(F: Mapping[str, str], brand: str) -> dict[str, object]:
    return {
        "engine": "meta",
        "mappings": {
            F["name"]: ("og:title", "twitter:title", "<title>"),
            F["url"]: ("og:url",),
            F["description"]: ("og:description", "twitter:description", "description"),
            F["price"]: ("product:price:amount", "og:price:amount"),
            F["currency"]: ("product:price:currency", "og:price:currency"),
            F["availability"]: ("product:availability",),
            F["image_url"]: ("og:image:secure_url", "og:image", "twitter:image"),
            F["brand"]: (f"literal:{brand}",),
        },
    }


def build_recipes(
    field_ids: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Return one seed and a three-stage scoped stack for each retailer."""
    F = _ids(field_ids)
    recipes: list[dict[str, object]] = []
    for source in SOURCES:
        templates = (_jsonld(F), _css(F, source.brand), _meta(F, source.brand))
        stack = []
        for index, template in enumerate(templates, start=1):
            stack.append(
                {
                    "name": f"clothes: {source.brand} · {index}-{template['engine']}",
                    "engine": template["engine"],
                    "mappings": template["mappings"],
                    "hosts": list(source.hosts),
                    "urlPatterns": list(source.url_patterns),
                }
            )
        recipes.append(
            {
                "slug": source.slug,
                "brand": source.brand,
                "seed": source.seed,
                "sampleUrl": source.sample_url,
                "templateStack": stack,
            }
        )
    return recipes


RECIPES = build_recipes()
