"""Pure recipe catalog shared by local and hosted example runners."""

from dataclasses import dataclass
from typing import Any, Mapping

ARTICLE_SYSTEM_FIELDS = (
    "fld_sys_title",
    "fld_sys_url",
    "fld_sys_description",
    "fld_sys_author",
    "fld_sys_published_at",
    "fld_sys_image_url",
)

PRODUCT_SYSTEM_FIELDS = (
    "fld_sys_name",
    "fld_sys_url",
    "fld_sys_description",
    "fld_sys_price",
    "fld_sys_currency",
    "fld_sys_sku",
    "fld_sys_brand",
    "fld_sys_rating",
    "fld_sys_image_url",
)

PAGE_SYSTEM_FIELDS = ("fld_sys_title", "fld_sys_url", "fld_sys_description")

RESPONSIBLE_POLITENESS = {
    "respectRobotsTxt": True,
    "requestsPerSecond": 1.0,
}


@dataclass(frozen=True)
class Case:
    key: str
    module: str
    label: str
    schema_name: str
    dataset_name: str
    dataset_mode: str
    system_fields: tuple[str, ...]
    scope: Mapping[str, Any]


CASES: dict[str, Case] = {
    "jobsearch": Case(
        "jobsearch",
        "examples.jobsearch.recipes",
        "Software engineering opportunities · 20 companies",
        "software engineering job posting deep v1",
        "software-engineer-opportunities",
        "new_urls_only",
        PAGE_SYSTEM_FIELDS,
        {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 10_000_000, "maxDepth": 6},
    ),
    "news/chihuahua": Case(
        "news/chihuahua",
        "examples.news.chihuahua.recipes",
        "Chihuahua press · 20 publications",
        "news article deep v1",
        "chihuahua-news-deep",
        "new_urls_only",
        ARTICLE_SYSTEM_FIELDS,
        {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 10_000_000, "maxDepth": 6},
    ),
    "news/mexico": Case(
        "news/mexico",
        "examples.news.mexico.recipes",
        "Mexico news · 20 publications",
        "mexico news article deep v1",
        "mexico-news-deep",
        "new_urls_only",
        ARTICLE_SYSTEM_FIELDS,
        {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 1_000_000, "maxDepth": 6},
    ),
    "news/stocks": Case(
        "news/stocks",
        "examples.news.stocks.recipes",
        "Stock news · 20 publications",
        "stock market news deep v1",
        "stock-market-news-deep",
        "new_urls_only",
        ARTICLE_SYSTEM_FIELDS,
        {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 10_000_000, "maxDepth": 6},
    ),
    "marketplace/clothes": Case(
        "marketplace/clothes",
        "examples.marketplace.clothes.recipes",
        "Clothing · 20 storefronts",
        "apparel product deep v1",
        "apparel-products-deep",
        "append_all",
        PRODUCT_SYSTEM_FIELDS,
        {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 10_000_000, "maxDepth": 6},
    ),
    "marketplace/supermarkets": Case(
        "marketplace/supermarkets",
        "examples.marketplace.supermarkets.recipes",
        "Supermarkets · 20 retailers",
        "supermarket product deep v1",
        "supermarket-products-deep",
        "append_all",
        PRODUCT_SYSTEM_FIELDS,
        {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 1_000_000, "maxDepth": 6},
    ),
    "marketplace/mro": Case(
        "marketplace/mro",
        "examples.marketplace.mro.recipes",
        "MRO · 20 suppliers",
        "mro industrial product deep v1",
        "mro-products-deep",
        "append_all",
        PRODUCT_SYSTEM_FIELDS,
        {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 1_000_000, "maxDepth": 6},
    ),
    "marketplace/other_industries": Case(
        "marketplace/other_industries",
        "examples.marketplace.other_industries.recipes",
        "Other industries · 20 sources",
        "cross-industry public products v1",
        "marketplace-other-industries",
        "append_all",
        PRODUCT_SYSTEM_FIELDS,
        {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 1_000_000, "maxDepth": 6},
    ),
}
