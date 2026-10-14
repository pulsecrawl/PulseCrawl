"""Supermarket product recipes for the URL-scoped template-stack example.

The module is data-only: it creates no PulseCrawl or retailer resources.  It
contains concrete mappings only for raw public HTML observed during the survey.
Retailers whose product markup could not be fetched without a challenge remain
seed-only so automatic system fallback and ``needsTemplate`` diagnostics can be
validated honestly.
"""

from __future__ import annotations

from typing import Any, Mapping


CUSTOM_FIELDS = (
    ("product_name", "string", "retailer product name"),
    ("canonical_url", "url", "canonical product URL"),
    ("description", "string", "long product description"),
    ("brand", "string", "manufacturer or consumer brand"),
    ("sku", "string", "retailer SKU or product identifier"),
    ("gtin", "string", "GTIN, UPC, or EAN"),
    ("category", "string", "retailer product category"),
    ("image_url", "url", "primary product image"),
    ("price", "number", "current displayed price"),
    ("price_currency", "string", "ISO-like price currency"),
    ("availability", "string", "schema.org or displayed availability"),
    ("package_size", "string", "pack size or sold unit"),
    ("unit_price", "string", "human-readable price per unit"),
    ("ingredients", "string", "ingredient statement"),
    ("allergens", "string", "allergen and warning statement"),
    ("nutrition_text", "string", "nutrition facts as published text"),
    ("rating", "number", "aggregate product rating"),
    ("review_count", "number", "aggregate rating/review count"),
    ("retailer", "string", "retailer publishing the offer"),
)

SCHEMA_NAME = "supermarket product deep v1"
DATASET_NAME = "supermarket-products-deep"
SCOPE = {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 1_000_000, "maxDepth": 6}


def _ids(field_ids: Mapping[str, str] | None) -> dict[str, str]:
    names = [name for name, _type, _description in CUSTOM_FIELDS]
    resolved = {name: name for name in names}
    if field_ids:
        missing = sorted(set(names).difference(field_ids))
        if missing:
            raise ValueError(f"missing supermarket field IDs: {missing}")
        resolved.update(field_ids)
    return resolved


def _product_jsonld(F: Mapping[str, str]) -> dict[str, Any]:
    return {
        "engine": "jsonld",
        "mappings": {
            F["product_name"]: ("Product.name",),
            F["canonical_url"]: ("Product.url", "Product.offers.url"),
            F["description"]: ("Product.description",),
            F["brand"]: ("Product.brand.name", "Product.brand"),
            F["sku"]: (
                "Product.sku",
                "Product.productID",
                "Product.asin",
                "Product.mpn",
            ),
            F["gtin"]: (
                "Product.gtin13",
                "Product.gtin12",
                "Product.gtin14",
                "Product.gtin",
            ),
            F["category"]: ("Product.category",),
            F["image_url"]: ("Product.image.url", "Product.image"),
            F["price"]: ("Product.offers.price", "Product.offers.lowPrice"),
            F["price_currency"]: ("Product.offers.priceCurrency",),
            F["availability"]: ("Product.offers.availability",),
            F["package_size"]: ("Product.size",),
            F["rating"]: ("Product.aggregateRating.ratingValue",),
            F["review_count"]: (
                "Product.aggregateRating.reviewCount",
                "Product.aggregateRating.ratingCount",
            ),
        },
    }


def _product_meta(F: Mapping[str, str], retailer: str) -> dict[str, Any]:
    return {
        "engine": "meta",
        "mappings": {
            F["product_name"]: ("og:title", "twitter:title", "<title>"),
            F["canonical_url"]: ("og:url",),
            F["description"]: ("og:description", "description", "twitter:description"),
            F["image_url"]: ("og:image", "twitter:image"),
            # URL scoping makes the constant safe. A literal must not make an
            # otherwise empty template count as a content match.
            F["retailer"]: ("og:site_name", f"literal:{retailer}"),
        },
    }


def _product_css(
    F: Mapping[str, str], retailer: str, mappings: Mapping[str, tuple[str, ...]]
) -> dict[str, Any]:
    resolved = {F[field]: selectors for field, selectors in mappings.items()}
    resolved[F["retailer"]] = (f"literal:{retailer}",)
    return {"engine": "css", "mappings": resolved}


AHOLD_SPECS = (
    (
        "food_lion",
        "Food Lion",
        "foodlion.com",
        "https://foodlion.com/groceries/dairy-eggs/milk.html",
        "https://foodlion.com/groceries/product/food-lion-2-reduced-fat-milk-1-quart/296838",
    ),
    (
        "giant_food",
        "Giant Food",
        "giantfood.com",
        "https://giantfood.com/groceries/dairy-eggs/milk.html",
        "https://giantfood.com/groceries/product/giant-100-pure-orange-juice-with-calcium-frozen-concentrate-12-oz-can/57042",
    ),
    (
        "stop_and_shop",
        "Stop & Shop",
        "stopandshop.com",
        "https://stopandshop.com/groceries/snacks/nuts-trail-mix.html",
        "https://stopandshop.com/groceries/product/stop-shop-almonds-whole-12-oz-bag/348183",
    ),
    (
        "hannaford",
        "Hannaford",
        "hannaford.com",
        "https://www.hannaford.com/groceries/dairy-eggs/milk.html",
        "https://www.hannaford.com/groceries/product/hannaford-original-half-half-1-pint/291246",
    ),
    (
        "giant_food_stores",
        "GIANT Food Stores",
        "giantfoodstores.com",
        "https://giantfoodstores.com/groceries/browse-aisles/827-milk",
        "https://giantfoodstores.com/groceries/product/our-brand-1-low-fat-milk-1-2-gallon/135679",
    ),
    (
        "martins",
        "MARTIN'S",
        "martinsfoods.com",
        "https://martinsfoods.com/groceries/dairy-eggs/milk.html",
        "https://martinsfoods.com/groceries/product/our-brand-1-low-fat-milk-1-2-gallon/135679",
    ),
)


RETAILER_SPECS: tuple[dict[str, Any], ...] = tuple(
    {
        "key": key,
        "name": name,
        "seed": seed,
        "hosts": [host],
        "url_patterns": ["/groceries/product/**"],
        "sample_url": sample_url,
        "profile": "ahold",
    }
    for key, name, host, seed, sample_url in AHOLD_SPECS
) + (
    {
        "key": "wegmans",
        "name": "Wegmans",
        "seed": "https://www.wegmans.com/shop/categories",
        "hosts": ["wegmans.com"],
        "url_patterns": ["/shop/product/**"],
        "sample_url": "https://www.wegmans.com/shop/product/38858-Tuscan-Kale",
        "profile": "wegmans",
    },
    {
        "key": "whole_foods",
        "name": "Whole Foods Market",
        "seed": "https://www.wholefoodsmarket.com/grocery",
        "hosts": ["wholefoodsmarket.com"],
        "url_patterns": ["/grocery/product/**"],
        "sample_url": "https://www.wholefoodsmarket.com/grocery/product/12-fl-oz-pack-of-1-b01ayyf1nc",
        "profile": "whole_foods",
    },
    {
        "key": "target",
        "name": "Target",
        "seed": "https://www.target.com/c/grocery/-/N-5xt1a",
        "hosts": ["target.com"],
        "url_patterns": ["/p/**/A-*", "/p/-/A-*"],
        "sample_url": "https://www.target.com/p/-/A-91745858",
        "profile": "target",
    },
    {
        "key": "walmart",
        "name": "Walmart",
        "seed": "https://www.walmart.com/cp/food/976759",
        "hosts": ["walmart.com"],
        "url_patterns": ["/ip/**"],
        "sample_url": "https://www.walmart.com/ip/5314190329",
        "profile": "walmart",
    },
    {
        "key": "metro_ca",
        "name": "Metro Canada",
        "seed": "https://www.metro.ca/en/online-grocery/aisles",
        "hosts": ["metro.ca"],
        "url_patterns": ["/en/online-grocery/aisles/**/p/*"],
        "sample_url": "https://www.metro.ca/en/online-grocery/aisles/pantry/baking-ingredients/canned-powdered-milk/evaporated-milk/p/059749948111",
        "profile": "metro",
    },
    {
        "key": "aldi_us",
        "name": "ALDI US",
        "seed": "https://www.aldi.us/store/aldi/storefront",
        "hosts": ["aldi.us"],
        "url_patterns": ["/store/aldi/products/**"],
        "sample_url": "https://www.aldi.us/store/aldi/products/97977523-elevation-vanilla-nutrition-shake-6-ct",
        "profile": "aldi",
    },
    {
        "key": "heb",
        "name": "H-E-B",
        "seed": "https://www.heb.com/browse/shop",
        "hosts": ["heb.com"],
        "url_patterns": ["/product-detail/**"],
        "sample_url": "https://www.heb.com/product-detail/h-e-b-whole-milk/314135",
        "authored": False,
        "research_status": "raw_response_missing_product_markup",
    },
    {
        "key": "trader_joes",
        "name": "Trader Joe's",
        "seed": "https://www.traderjoes.com/home/products/category/products-2",
        "hosts": ["traderjoes.com"],
        "url_patterns": ["/home/products/pdp/**"],
        "sample_url": "https://www.traderjoes.com/home/products/pdp/066493",
        "authored": False,
        "research_status": "robots_and_page_returned_403",
    },
    {
        "key": "kroger",
        "name": "Kroger",
        "seed": "https://www.kroger.com/pl/milk/0200100011",
        "hosts": ["kroger.com"],
        "url_patterns": ["/p/**"],
        "sample_url": "https://www.kroger.com/p/kroger-whole-milk/0001111041700",
        "authored": False,
        "research_status": "raw_request_timed_out",
    },
    {
        "key": "publix",
        "name": "Publix",
        "seed": "https://www.publix.com/products-services",
        "hosts": ["publix.com"],
        "url_patterns": ["/pd/**"],
        "sample_url": "https://www.publix.com/pd/publix-milk-whole/RIO-PCI-118106",
        "authored": False,
        "research_status": "challenge_shell_without_product_markup",
    },
    {
        "key": "meijer",
        "name": "Meijer",
        "seed": "https://www.meijer.com/shopping/departments/grocery.html",
        "hosts": ["meijer.com"],
        "url_patterns": ["/shopping/product/**"],
        "sample_url": "https://www.meijer.com/shopping/product/meijer-whole-milk-gallon/4125085402.html",
        "authored": False,
        "research_status": "product_request_returned_403",
    },
    {
        "key": "costco",
        "name": "Costco",
        "seed": "https://www.costco.com/grocery-household.html",
        "hosts": ["costco.com"],
        "url_patterns": ["/*.product.*.html"],
        "sample_url": None,
        "authored": False,
        "research_status": "raw_product_request_timed_out",
    },
    {
        "key": "tesco",
        "name": "Tesco",
        "seed": "https://www.tesco.com/groceries/en-GB/",
        "hosts": ["tesco.com"],
        "url_patterns": ["/groceries/en-GB/products/*"],
        "sample_url": "https://www.tesco.com/shop/en-GB/products/251882481",
        "authored": False,
        "research_status": "robots_and_product_returned_403",
    },
    {
        "key": "morrisons",
        "name": "Morrisons",
        "seed": "https://groceries.morrisons.com/categories",
        "hosts": ["groceries.morrisons.com"],
        "url_patterns": ["/products/**"],
        "sample_url": "https://groceries.morrisons.com/products/morrisons-instant-skimmed-milk-powder/113394384",
        "authored": False,
        "research_status": "product_request_returned_403",
    },
)


CSS_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "ahold": {
        "product_name": ("[data-product-title]",),
        "category": ("[data-product-title] + div span",),
        "package_size": ("[data-product-title] ~ div p",),
        # In the sampled storefront, Ingredients is the first h3 immediately
        # followed by a paragraph; earlier nutrition headings wrap tables.
        "ingredients": ("section.mb-6 h3 + p",),
    },
    "wegmans": {
        "product_name": (".product-heading",),
        "package_size": (".product-heading + div",),
        "image_url": (".component--product-details img@src",),
    },
    "whole_foods": {
        "product_name": ("h1.bds--heading-1",),
        "ingredients": ("p.bds--body-1.w-full.text-squid-ink",),
        "image_url": ("[data-testid='pdc-large-slide'] img@src",),
    },
    "target": {"product_name": ("[data-test='product-title']",)},
    "walmart": {
        "product_name": ("h1#main-title",),
        "price": ("[data-testid='price-wrap']",),
        "price_currency": ("[itemprop='priceCurrency']",),
    },
    "metro": {
        "product_name": (".pi--title",),
        "brand": (".pi--brand",),
        "sku": (".pdpDetailsContainer@data-product-code",),
        "category": (".pdpDetailsContainer@data-product-category",),
        "package_size": (".pi--weight",),
        "price": ("[data-main-price]@data-main-price",),
        "description": ("#product-description .accordion--text p",),
        "ingredients": (".pdp-ingredients-list",),
    },
    "aldi": {
        "product_name": (
            "main h1",
            "h1",
        )
    },
}


def build_retailers(field_ids: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Return all seeds and concrete template definitions for accessible sites."""
    F = _ids(field_ids)
    retailers: list[dict[str, Any]] = []
    for raw_spec in RETAILER_SPECS:
        spec = dict(raw_spec)
        templates: list[dict[str, Any]] = []
        if spec.get("authored", True):
            # Ahold embeds Product below a non-schema wrapper object, which the
            # current JSON-LD engine does not recursively flatten. Metro,
            # Target, and Walmart also yielded no directly extractable Product
            # entity in the sampled raw response.
            if spec["profile"] not in {"ahold", "metro", "target", "walmart"}:
                templates.append(
                    {
                        "name": f"tmpl: {spec['name']} · product-jsonld",
                        **_product_jsonld(F),
                    }
                )
            templates.append(
                {
                    "name": f"tmpl: {spec['name']} · product-meta",
                    **_product_meta(F, spec["name"]),
                }
            )
            templates.append(
                {
                    "name": f"tmpl: {spec['name']} · product-css",
                    **_product_css(F, spec["name"], CSS_PROFILES[spec["profile"]]),
                }
            )
        spec["templates"] = templates
        retailers.append(spec)
    return retailers


def seeds() -> list[str]:
    """Return all seeds, including sites deliberately left to system fallback."""
    return [spec["seed"] for spec in RETAILER_SPECS]
