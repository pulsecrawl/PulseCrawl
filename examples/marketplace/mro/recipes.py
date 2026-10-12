"""MRO product recipes for the URL-scoped template-stack example.

This module is data-only.  Importing it does not create PulseCrawl resources or
make network requests.  Every authored selector was observed in a public raw
HTML response during the survey; suppliers that challenged or blocked the
research fetch remain seed-only for automatic system fallback diagnostics.
"""

from __future__ import annotations

from typing import Any, Mapping


CUSTOM_FIELDS = (
    ("product_name", "string", "supplier product title"),
    ("canonical_url", "url", "canonical product URL"),
    ("description", "string", "product overview or description"),
    ("brand", "string", "product brand"),
    ("manufacturer", "string", "manufacturer name"),
    ("supplier_sku", "string", "supplier item or stock number"),
    ("manufacturer_part_number", "string", "manufacturer part or model number"),
    ("gtin", "string", "UPC, EAN, or GTIN"),
    ("category", "string", "supplier product category"),
    ("image_url", "url", "primary product image"),
    ("price", "number", "current public unit price"),
    ("price_currency", "string", "price currency"),
    ("availability", "string", "published availability or stock status"),
    ("unit_of_measure", "string", "offer unit such as each, box, or case"),
    ("minimum_order_quantity", "number", "minimum purchasable quantity"),
    ("specifications_text", "string", "published technical specifications"),
    ("document_urls", "string", "published manuals, drawings, and data sheets"),
    ("country_of_origin", "string", "published country of origin"),
    ("unspsc", "string", "UNSPSC commodity code"),
    ("rating", "number", "aggregate product rating"),
    ("review_count", "number", "aggregate rating or review count"),
    ("supplier", "string", "distributor publishing the offer"),
)

SCHEMA_NAME = "mro industrial product deep v1"
DATASET_NAME = "mro-products-deep"
SCOPE = {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 1_000_000, "maxDepth": 6}


def _ids(field_ids: Mapping[str, str] | None) -> dict[str, str]:
    names = [name for name, _type, _description in CUSTOM_FIELDS]
    resolved = {name: name for name in names}
    if field_ids:
        missing = sorted(set(names).difference(field_ids))
        if missing:
            raise ValueError(f"missing MRO field IDs: {missing}")
        resolved.update(field_ids)
    return resolved


def _product_jsonld(F: Mapping[str, str]) -> dict[str, Any]:
    """Schema.org Product fields supported by the current JSON-LD walker."""
    return {
        "engine": "jsonld",
        "mappings": {
            F["product_name"]: ("Product.name",),
            F["canonical_url"]: ("Product.url", "Product.offers.url", "Product.@id"),
            F["description"]: ("Product.description",),
            F["brand"]: ("Product.brand.name", "Product.brand"),
            F["manufacturer"]: ("Product.manufacturer.name", "Product.manufacturer"),
            F["supplier_sku"]: ("Product.sku", "Product.productID"),
            F["manufacturer_part_number"]: ("Product.mpn", "Product.model"),
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
            F["price_currency"]: (
                "Product.offers.priceCurrency",
                "Product.offers.priceSpecification.priceCurrency",
            ),
            F["availability"]: ("Product.offers.availability",),
            F["rating"]: ("Product.aggregateRating.ratingValue",),
            F["review_count"]: (
                "Product.aggregateRating.reviewCount",
                "Product.aggregateRating.ratingCount",
            ),
        },
    }


def _product_meta(F: Mapping[str, str], supplier: str) -> dict[str, Any]:
    return {
        "engine": "meta",
        "mappings": {
            F["product_name"]: ("og:title", "twitter:title", "<title>"),
            F["canonical_url"]: ("og:url",),
            F["description"]: ("og:description", "description", "twitter:description"),
            F["image_url"]: ("og:image", "twitter:image"),
            F["price"]: ("product:price:amount", "og:price:amount"),
            F["price_currency"]: ("product:price:currency", "og:price:currency"),
            # Host/path scoping makes this constant safe. A literal must not
            # make an otherwise empty template count as a content match.
            F["supplier"]: ("og:site_name", f"literal:{supplier}"),
        },
    }


def _product_css(
    F: Mapping[str, str], supplier: str, mappings: Mapping[str, tuple[str, ...]]
) -> dict[str, Any]:
    resolved = {F[field]: selectors for field, selectors in mappings.items()}
    resolved[F["supplier"]] = (f"literal:{supplier}",)
    return {"engine": "css", "mappings": resolved}


SUPPLIER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "grainger",
        "name": "Grainger",
        "seed": "https://www.grainger.com/",
        "hosts": ["grainger.com"],
        "url_patterns": ["/product/**"],
        "sample_url": "https://www.grainger.com/product/DAYTON-Pneumatic-Vibrator-581-lbf-1DYP6",
        "authored": False,
        "research_status": "robots_endpoint_returned_error_html",
    },
    {
        "key": "msc",
        "name": "MSC Industrial Supply",
        "seed": "https://www.mscdirect.com/browse/tn",
        "hosts": ["mscdirect.com"],
        "url_patterns": ["/product/details/**"],
        "sample_url": None,
        "authored": False,
        "research_status": "no_current_raw_product_sample_verified",
    },
    {
        "key": "fastenal",
        "name": "Fastenal",
        "seed": "https://www.fastenal.com/product",
        "hosts": ["fastenal.com"],
        "url_patterns": ["/product/details/**"],
        "sample_url": None,
        "authored": False,
        "research_status": "robots_returned_403_and_storefront_is_js_shell",
    },
    {
        "key": "mcmaster",
        "name": "McMaster-Carr",
        "seed": "https://www.mcmaster.com/products/material-handling/",
        "hosts": ["mcmaster.com"],
        "url_patterns": ["/products/**"],
        "sample_url": "https://www.mcmaster.com/products/industrial-blowers/",
        "authored": False,
        "research_status": "collection_page_model_not_one_product_per_url",
    },
    {
        "key": "zoro",
        "name": "Zoro",
        "seed": "https://www.zoro.com/",
        "hosts": ["zoro.com"],
        "url_patterns": ["/**/i/*/"],
        "sample_url": "https://www.zoro.com/smc-male-elbow-push-to-connect-x-mnpt-for-14-in-tube-od-18-in-pipe-size-brass-kq2l07-34as-kq2l07-34as/i/G5049965/",
        "authored": False,
        "research_status": "robots_and_raw_requests_returned_403",
    },
    {
        "key": "global_industrial",
        "name": "Global Industrial",
        "seed": "https://www.globalindustrial.com/c/material-handling",
        "hosts": ["globalindustrial.com"],
        "url_patterns": ["/p/**"],
        "sample_url": "https://www.globalindustrial.com/p/global-industrial-153-standard-duty-pallet-jack-truck-5500-lb-capacity-27-x-48-forks",
        "profile": "global_industrial",
    },
    {
        "key": "uline",
        "name": "Uline",
        "seed": "https://www.uline.com/Product/BrowseWebClass.htm",
        "hosts": ["uline.com"],
        "url_patterns": ["/Product/Detail/**"],
        "sample_url": "https://www.uline.com/Product/Detail/H-41/Steel-Strapping-Tools/Industrial-Steel-Strapping-Cutter",
        "profile": "uline",
    },
    {
        "key": "harbor_freight",
        "name": "Harbor Freight Tools",
        "seed": "https://www.harborfreight.com/power-tools.html",
        "hosts": ["harborfreight.com"],
        "url_patterns": ["/**/*.html"],
        "sample_url": "https://www.harborfreight.com/brands/hercules/grinders/20v-brushless-cordless-14-in-die-grinder-tool-only-58846.html",
        "profile": "harbor_freight",
    },
    {
        "key": "automation_direct",
        "name": "AutomationDirect",
        "seed": "https://www.automationdirect.com/products",
        "hosts": ["automationdirect.com"],
        "url_patterns": ["/pn/*", "/adc/shopping/catalog/**"],
        "sample_url": "https://www.automationdirect.com/adc/shopping/catalog/programmable_controllers/click_plcs_%28stackable_micro_brick%29/plc_units/c0-00dd1-d",
        "profile": "automation_direct",
    },
    {
        "key": "ohio_power_tool",
        "name": "Ohio Power Tool",
        "seed": "https://www.ohiopowertool.com/power-tools",
        "hosts": ["ohiopowertool.com"],
        "url_patterns": ["/milwaukee-tools-*"],
        "sample_url": "https://www.ohiopowertool.com/milwaukee-tools-2821-20",
        "profile": "ohio_power_tool",
    },
    {
        "key": "airgas",
        "name": "Airgas",
        "seed": "https://www.airgas.com/",
        "hosts": ["airgas.com"],
        "url_patterns": ["/product/**/p/*"],
        "sample_url": "https://www.airgas.com/product/Welding-Products/Welders-%26-Accessories/Machine-%26-Fixture-Repair-Parts/p/HYP075714",
        "profile": "airgas",
        "jsonld": False,
    },
    {
        "key": "graybar",
        "name": "Graybar",
        "seed": "https://www.graybar.com/",
        "hosts": ["graybar.com"],
        "url_patterns": ["/**/p/*", "/store/en/gb/**"],
        "sample_url": "https://www.graybar.com/store/en/gb/galvanized-rigid-steel-conduit-88272916",
        "profile": "graybar",
        "jsonld": False,
    },
    {
        "key": "fasteners_plus",
        "name": "Fasteners Plus",
        "seed": "https://www.fastenersplus.com/collections/all",
        "hosts": ["fastenersplus.com"],
        "url_patterns": ["/products/**"],
        "sample_url": "https://www.fastenersplus.com/products/simpson-66t-6-x-6-t-shaped-strap-g90-galvanized",
        "profile": "fasteners_plus",
        "jsonld": False,
    },
    {
        "key": "ferguson",
        "name": "Ferguson",
        "seed": "https://www.ferguson.com/category/",
        "hosts": ["ferguson.com"],
        "url_patterns": ["/product/**.html"],
        "sample_url": "https://www.ferguson.com/product/talon-talon-talon-industrial-grade-hand-cleaner-wthc1/7221373.html",
        "authored": False,
        "research_status": "raw_product_request_returned_403",
    },
    {
        "key": "hd_supply",
        "name": "HD Supply",
        "seed": "https://hdsupplysolutions.com/c/maintenance-repair-operations-00-05",
        "hosts": ["hdsupplysolutions.com"],
        "url_patterns": ["/p/**-p*"],
        "sample_url": "https://hdsupplysolutions.com/p/kimtech-white-1-ply-kimwipes-delicate-task-science-wipers-%28144-count-sheets%29-%2815-case%29-p325627",
        "authored": False,
        "research_status": "raw_product_request_returned_generic_400",
    },
    {
        "key": "newark",
        "name": "Newark Electronics",
        "seed": "https://www.newark.com/",
        "hosts": ["newark.com"],
        "url_patterns": ["/**/dp/*"],
        "sample_url": "https://www.newark.com/dwyer/12al0/product-range-proximity-mark-series/dp/82AK8904",
        "authored": False,
        "research_status": "raw_connection_failed_during_survey",
    },
    {
        "key": "motion",
        "name": "Motion",
        "seed": "https://www.motion.com/products/categories",
        "hosts": ["motion.com"],
        "url_patterns": ["/products/sku/*"],
        "sample_url": None,
        "authored": False,
        "research_status": "robots_returned_403_and_indexed_samples_were_stale",
    },
    {
        "key": "applied",
        "name": "Applied Industrial Technologies",
        "seed": "https://www.applied.com/",
        "hosts": ["applied.com"],
        "url_patterns": ["/c-brands/**/p/**"],
        "sample_url": None,
        "authored": False,
        "research_status": "no_current_raw_product_sample_verified",
    },
    {
        "key": "imperial_supplies",
        "name": "Imperial Supplies",
        "seed": "https://www.imperialsupplies.com/",
        "hosts": ["imperialsupplies.com"],
        "url_patterns": ["/item/**"],
        "sample_url": None,
        "authored": False,
        "research_status": "product_url_and_markup_not_verified",
    },
    {
        "key": "northern_tool",
        "name": "Northern Tool + Equipment",
        "seed": "https://www.northerntool.com/categories",
        "hosts": ["northerntool.com"],
        "url_patterns": ["/products/**"],
        "sample_url": "https://www.northerntool.com/products/milwaukee",
        "authored": False,
        "research_status": "raw_storefront_request_returned_403",
    },
)


CSS_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "global_industrial": {
        "product_name": ("#main-prod-title",),
        "brand": (".prod-item-brand",),
        "supplier_sku": (".prod-itemkey-num span",),
        "description": (".prodInfoFullText",),
    },
    "uline": {
        "product_name": ("#dvTitle h1",),
        "supplier_sku": ("#ProductDetailContentModelNumber@value",),
        "minimum_order_quantity": ("#MinOrderQuantity@value",),
        "description": ("#dvCopy",),
        "image_url": (".itemResultImage@src",),
        "specifications_text": ("#tdChart table",),
    },
    "harbor_freight": {
        "product_name": ("#product-wrap h1",),
        "supplier_sku": ("#product-wrap [class^='product__sku']",),
        "description": ("[data-testid='productDescription']", "#OverviewContent"),
        "price": ("[data-testid='priceWrap'] .sr-only",),
        "specifications_text": ("#SpecificationsContent",),
    },
    "automation_direct": {
        "product_name": ("main h1", "h1"),
        "supplier_sku": ("#itemCode@value",),
        "description": ("#itemdescription",),
        "specifications_text": ("#specifications", "#itemSpecifications"),
    },
    "ohio_power_tool": {
        "product_name": ("h1.page-title",),
        "supplier_sku": (".product.attribute.sku .value",),
        "description": ("#description .product.attribute.description",),
        "price": ("[data-price-type='finalPrice']@data-price-amount",),
        "availability": (".product-info-stock-sku .amstockstatus",),
    },
    "airgas": {
        "product_name": (".product-information h2", "#productName"),
        "brand": (".man-sds-sheet-section .man",),
        "supplier_sku": (".airgas-part-number em", "#productCode"),
        "manufacturer_part_number": (".manufacturer-number em",),
        "description": (".product-details .details-content",),
        "unit_of_measure": ("input[name='uomDescription']@value",),
        "minimum_order_quantity": ("#minQtyReq",),
        "specifications_text": (
            ".features.submain",
            ".attributes",
        ),
        "image_url": (".product-view-wrapper img@src",),
    },
    "graybar": {
        "product_name": (".product-detailsPanel .product-details h1.name",),
        "brand": (".product-detailsPanel .manufacturerName",),
        "supplier_sku": (".product-detailsPanel@data-sku",),
        "manufacturer_part_number": (".product-detailsPanel@data-mpn",),
        "gtin": (".product-detailsPanel@data-upc",),
        "description": (
            ".product-detailsPanel@data-description",
            ".product-overview .summary",
        ),
        "image_url": (".product-detailsPanel .mainImage@src",),
        "specifications_text": (".product-classifications table",),
    },
    "fasteners_plus": {
        "product_name": ("h1.product-h1",),
        "supplier_sku": (".product-sku span",),
        "description": ("#descriptionContainer",),
        "price": (".product-price",),
        "specifications_text": (".specifications-list",),
    },
}


def build_suppliers(field_ids: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Return all seeds and only the templates backed by observed raw HTML."""
    F = _ids(field_ids)
    suppliers: list[dict[str, Any]] = []
    for raw_spec in SUPPLIER_SPECS:
        spec = dict(raw_spec)
        templates: list[dict[str, Any]] = []
        if spec.get("authored", True):
            if spec.get("jsonld", True):
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
        suppliers.append(spec)
    return suppliers


def build_stack_entries(
    suppliers: list[dict[str, Any]], template_ids_by_name: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Build ordered entries for the proposed Python SDK ``template_stack``."""
    entries: list[dict[str, Any]] = []
    for supplier in suppliers:
        for template in supplier["templates"]:
            entries.append(
                {
                    "template_id": template_ids_by_name[template["name"]],
                    "hosts": list(supplier["hosts"]),
                    "url_patterns": list(supplier["url_patterns"]),
                }
            )
    return entries


def seeds() -> list[str]:
    """Return all seeds, including suppliers left to system fallback."""
    return [spec["seed"] for spec in SUPPLIER_SPECS]
