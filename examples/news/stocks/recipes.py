"""URL-scoped recipes for a multi-publisher stock-news crawl.

The module is side-effect free: it defines the fields, seeds, scopes and
templates an eventual hosted example can register.  Every authored template is
scoped to the final host and an article-shaped path.  Compatible system
templates are deliberately absent; the worker appends them only after all
applicable authored templates miss.

``build_publishers`` replaces symbolic custom-field names with actual field
IDs. ``build_stack_entries`` converts registered template names into the
Python SDK ``template_stack`` payload.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


CUSTOM_FIELDS = (
    ("body", "string", "full article text"),
    ("section", "string", "publisher section or market category"),
    ("tags", "string", "keywords, comma-joined"),
    ("symbols", "string", "first structured ticker/topic or metadata keyword"),
    ("source_name", "string", "publisher name"),
    ("modified_at", "datetime", "last modification time"),
)

SYSTEM_FIELDS = (
    "fld_sys_title",
    "fld_sys_url",
    "fld_sys_description",
    "fld_sys_author",
    "fld_sys_published_at",
    "fld_sys_image_url",
)

SCHEMA_NAME = "stock market news deep v1"
DATASET_NAME = "stock-market-news-deep"
SCOPE = {"maxUrlsPerExecution": 1_000, "maxUrlsTotal": 1_000_000, "maxDepth": 6}


def article_jsonld(field_ids: Mapping[str, str]) -> dict[str, Any]:
    """Schema.org Article mapping shared by the sampled financial publishers."""
    return {
        "engine": "jsonld",
        "mappings": {
            "fld_sys_title": ["Article.headline", "Article.name"],
            "fld_sys_url": [
                "Article.url",
                "Article.mainEntityOfPage.@id",
                "Article.mainEntityOfPage",
            ],
            "fld_sys_description": "Article.description",
            "fld_sys_author": ["Article.author.name", "Article.author"],
            "fld_sys_published_at": "Article.datePublished",
            "fld_sys_image_url": ["Article.image.url", "Article.image"],
            field_ids["body"]: "Article.articleBody",
            field_ids["modified_at"]: "Article.dateModified",
            field_ids["section"]: "Article.articleSection",
            field_ids["tags"]: "Article.keywords",
            field_ids["symbols"]: ["Article.about.name", "Article.keywords"],
            field_ids["source_name"]: [
                "Article.publisher.name",
                "Article.provider.name",
            ],
        },
    }


def live_blog_jsonld(field_ids: Mapping[str, str]) -> dict[str, Any]:
    """Structured header fields from CNBC-style ``LiveBlogPosting`` pages."""
    return {
        "engine": "jsonld",
        "mappings": {
            "fld_sys_title": "LiveBlogPosting.headline",
            "fld_sys_url": [
                "LiveBlogPosting.url",
                "LiveBlogPosting.mainEntityOfPage.@id",
            ],
            "fld_sys_description": "LiveBlogPosting.description",
            "fld_sys_author": [
                "LiveBlogPosting.author.name",
                "LiveBlogPosting.creator.name",
            ],
            "fld_sys_published_at": "LiveBlogPosting.datePublished",
            "fld_sys_image_url": [
                "LiveBlogPosting.image.url",
                "LiveBlogPosting.image",
            ],
            field_ids["modified_at"]: "LiveBlogPosting.dateModified",
        },
    }


def article_meta(field_ids: Mapping[str, str], publisher: str) -> dict[str, Any]:
    """Observed OpenGraph/article metadata with a URL-scoped source fallback."""
    return {
        "engine": "meta",
        "mappings": {
            "fld_sys_title": ["og:title", "twitter:title", "<title>"],
            "fld_sys_url": ["og:url", "twitter:url"],
            "fld_sys_description": [
                "og:description",
                "description",
                "twitter:description",
            ],
            "fld_sys_author": ["article:author", "author", "parsely-author"],
            "fld_sys_published_at": [
                "article:published_time",
                "parsely-pub-date",
                "date",
            ],
            "fld_sys_image_url": ["og:image", "twitter:image", "twitter:image:src"],
            field_ids["modified_at"]: [
                "article:modified_time",
                "article:updated_time",
                "og:updated_time",
            ],
            field_ids["section"]: ["article:section", "parsely-section"],
            field_ids["tags"]: ["article:tag", "news_keywords", "keywords"],
            field_ids["symbols"]: ["article:tag", "news_keywords", "keywords"],
            # The literal is safe only because all generated entries carry a
            # final-URL scope.  It also exercises the no-cross-host regression.
            field_ids["source_name"]: ["og:site_name", f"literal:{publisher}"],
        },
    }


def css_body(field_ids: Mapping[str, str], selectors: Sequence[str]) -> dict[str, Any]:
    """Body-only fallbacks; no broad title mapping may claim a listing page."""
    return {
        "engine": "css",
        "mappings": {
            field_ids["body"]: [f"{selector} p::all" for selector in selectors],
        },
    }


# Surveyed from public server responses on 2026-08-21. ``authored=False``
# means the source is still seeded but deliberately has no org template. This
# exercises automatic system fallback and ``needsTemplate`` diagnostics without
# pretending a challenged or empty response proved a selector.
PUBLISHER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "yahoo_finance",
        "name": "Yahoo Finance",
        "seed": "https://finance.yahoo.com/markets/stocks/",
        "hosts": ["finance.yahoo.com"],
        "url_patterns": ["/markets/stocks/articles/*.html", "/markets/live/*.html"],
        "sample_url": "https://finance.yahoo.com/markets/stocks/articles/stocks-finish-mixed-bond-yields-203512126.html",
        "body_selectors": ("article.article-wrap div.body",),
        "robots": "allowed-for-pulsecrawl-user-agent",
    },
    {
        "key": "investopedia",
        "name": "Investopedia",
        # Investopedia category pages and articles share the same numeric-suffix
        # URL shape. Seed a proven article so the broad metadata fallback never
        # turns the category page itself into a row.
        "seed": "https://www.investopedia.com/treasury-buybacks-ease-pressure-on-long-term-bond-yields-12063360",
        "hosts": ["investopedia.com"],
        "url_patterns": ["/*-[0-9]*"],
        "sample_url": "https://www.investopedia.com/treasury-buybacks-ease-pressure-on-long-term-bond-yields-12063360",
        "body_selectors": ("[id^='article-body']",),
        "robots": "allowed-for-pulsecrawl-user-agent",
    },
    {
        "key": "nasdaq",
        "name": "Nasdaq",
        "seed": "https://www.nasdaq.com/articles",
        "hosts": ["nasdaq.com"],
        "url_patterns": ["/articles/*"],
        "sample_url": "https://www.nasdaq.com/articles/chartstopper-august-7-2026",
        "authored": False,
        "research_status": "request_timeout",
        "robots": "robots-request-failed",
    },
    {
        "key": "motley_fool",
        "name": "The Motley Fool",
        "seed": "https://www.fool.com/investing-news/",
        "hosts": ["fool.com"],
        "url_patterns": ["/investing/20??/??/??/*/"],
        "sample_url": "https://www.fool.com/investing/2026/08/21/the-wild-swings-of-earnings-season-continue/",
        "body_selectors": ("#article-body",),
        "robots": "allowed",
    },
    {
        "key": "kiplinger",
        "name": "Kiplinger",
        "seed": "https://www.kiplinger.com/investing/stocks",
        "hosts": ["kiplinger.com"],
        "url_patterns": ["/investing/stocks/*"],
        "sample_url": "https://www.kiplinger.com/investing/stocks/dow-sinks-703-points-as-yield-spike-walmart-slumps-stock-market-today",
        "body_selectors": ("#article-body",),
        "robots": "allowed-for-pulsecrawl-user-agent",
    },
    {
        "key": "morningstar",
        "name": "Morningstar",
        "seed": "https://www.morningstar.com/markets",
        "hosts": ["morningstar.com"],
        "url_patterns": ["/markets/*", "/stocks/*"],
        "sample_url": "https://www.morningstar.com/markets/stock-markets-resume-their-rise-risks-persist-key-trends-q2-2026",
        "authored": False,
        "research_status": "http_202_empty_response",
        "robots": "allowed",
    },
    {
        "key": "the_street",
        "name": "TheStreet",
        "seed": "https://www.thestreet.com/investing/stocks",
        "hosts": ["thestreet.com"],
        "url_patterns": ["/stock-market-today/*", "/investing/*"],
        "sample_url": "https://www.thestreet.com/stock-market-today/stock-market-today-dow-jones-sp-500-nasdaq-updates-aug-20-2026",
        "authored": False,
        "research_status": "http_403",
        "robots": "path-allowed-but-server-denied",
    },
    {
        "key": "seeking_alpha",
        "name": "Seeking Alpha",
        "seed": "https://seekingalpha.com/market-news",
        "hosts": ["seekingalpha.com"],
        "url_patterns": ["/news/[0-9]*-*", "/article/[0-9]*-*"],
        "sample_url": "https://seekingalpha.com/news/4636000-nasdaq-ends-positive-on-broader-rally-but-tech-stocks-lead-weekly-losses",
        "authored": False,
        "research_status": "access_denied_challenge",
        "robots": "article-paths-not-generally-disallowed",
    },
    {
        "key": "benzinga",
        "name": "Benzinga",
        "seed": "https://www.benzinga.com/markets",
        "hosts": ["benzinga.com"],
        "url_patterns": [
            "/markets/*/??/??/[0-9]*/*",
            "/trading-ideas/*/??/??/[0-9]*/*",
            "/news/*/??/??/[0-9]*/*",
        ],
        "sample_url": "https://www.benzinga.com/markets/equities/26/08/61370247/mrna-spcx-mstr-and-more-5-stocks-investors-couldnt-stop-buzzing-about-this-week",
        "body_selectors": ("#article-body",),
        "robots": "robots-http-403",
    },
    {
        "key": "stocktwits",
        "name": "Stocktwits",
        "seed": "https://stocktwits.com/news-articles",
        "hosts": ["stocktwits.com"],
        "url_patterns": ["/news-articles/markets/equity/*/*"],
        "sample_url": "https://stocktwits.com/news-articles/markets/equity/apple-reportedly-shifts-focus-to-ai-and-smart-glasses/cZY9ORKRJVW",
        "body_selectors": ("[class*='NewsArticle_body__']",),
        "robots": "allowed-for-pulsecrawl-user-agent",
    },
    {
        "key": "tradingview",
        "name": "TradingView",
        "seed": "https://www.tradingview.com/news/",
        "hosts": ["tradingview.com"],
        "url_patterns": ["/news/*:*"],
        "sample_url": "https://www.tradingview.com/news/tradingview:01ecac2f6094b:0-s-p-500-slips-as-bond-yields-break-the-vibe-futures-lower-ahead-of-fed-update/",
        "body_selectors": ("article",),
        "robots": "allowed-for-pulsecrawl-user-agent",
    },
    {
        "key": "barchart",
        "name": "Barchart",
        "seed": "https://www.barchart.com/news",
        "hosts": ["barchart.com"],
        "url_patterns": ["/story/news/[0-9]*/*"],
        "sample_url": "https://www.barchart.com/story/news/3971020/walmart-wmt-suffers-multiple-price-target-cuts-after-q2-earnings",
        "body_selectors": (".article-content-text",),
        "robots": "allowed",
    },
    {
        "key": "tipranks",
        "name": "TipRanks",
        "seed": "https://www.tipranks.com/news",
        "hosts": ["tipranks.com"],
        "url_patterns": ["/news/*-*"],
        "sample_url": "https://www.tipranks.com/news/market-wrap-u-s-stocks-post-losing-week-despite-friday-rally",
        "body_selectors": ("article",),
        "robots": "allowed",
    },
    {
        "key": "cnbc",
        "name": "CNBC",
        "seed": "https://www.cnbc.com/markets/",
        "hosts": ["cnbc.com"],
        "url_patterns": ["/20??/??/??/*.html"],
        "sample_url": "https://www.cnbc.com/2026/08/20/stock-market-today-live-updates.html",
        "jsonld_kind": "live_blog",
        "body_selectors": (
            "[id^='LiveStory-SpecialReport-LiveBlogBody']",
            ".ArticleBody-articleBody",
        ),
        "robots": "allowed-for-pulsecrawl-user-agent",
    },
    {
        "key": "marketbeat",
        "name": "MarketBeat",
        "seed": "https://www.marketbeat.com/originals/",
        "hosts": ["marketbeat.com"],
        "url_patterns": ["/articles/*/"],
        "sample_url": "https://www.marketbeat.com/articles/albemarles-blowout-quarter-shows-why-lithium-still-matters/",
        "body_selectors": ("#articlecontent",),
        "robots": "allowed",
    },
    {
        "key": "fxstreet",
        "name": "FXStreet",
        "seed": "https://www.fxstreet.com/news",
        "hosts": ["fxstreet.com"],
        "url_patterns": [
            "/news/*-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]"
        ],
        "sample_url": "https://www.fxstreet.com/news/tech-rout-weighs-on-us-stocks-as-the-usd-clocks-a-fresh-2026-high-202606240735",
        "body_selectors": ("#post-content",),
        "robots": "allowed",
    },
    {
        "key": "gurufocus",
        "name": "GuruFocus",
        "seed": "https://www.gurufocus.com/news",
        "hosts": ["gurufocus.com"],
        "url_patterns": ["/news/[0-9]*/*"],
        "sample_url": "https://www.gurufocus.com/news/9048268/youdao-inc-dao-shares-surge-88-what-gf-score-of-66-tells-investors",
        "body_selectors": ("[id^='article-body-']",),
        "robots": "allowed",
    },
    {
        "key": "etf_com",
        "name": "ETF.com",
        "seed": "https://www.etf.com/sections/news",
        "hosts": ["etf.com"],
        "url_patterns": [
            "/sections/features/*",
            "/sections/news/*",
            "/sections/etf-industry-perspective/*",
        ],
        "sample_url": "https://www.etf.com/sections/features/modernas-177-surge-powers-broad-biotech-rally",
        "body_selectors": (".node__content",),
        "robots": "robots-http-403",
    },
    {
        "key": "investorplace",
        "name": "InvestorPlace",
        "seed": "https://investorplace.com/",
        "hosts": ["investorplace.com"],
        "url_patterns": ["/20??/??/*/"],
        "sample_url": "https://investorplace.com/2026/08/will-higher-bond-yields-break-the-ai-bull-market/",
        "body_selectors": (".entry-content.story",),
        "robots": "allowed",
    },
    {
        "key": "reuters",
        "name": "Reuters",
        "seed": "https://www.reuters.com/markets/",
        "hosts": ["reuters.com"],
        "url_patterns": ["/markets/*"],
        "sample_url": "https://www.reuters.com/markets/",
        "authored": False,
        "research_status": "http_401",
        "robots": "market-paths-allowed-but-server-denied",
    },
)


def build_publishers(field_ids: Mapping[str, str]) -> list[dict[str, Any]]:
    """Build the 20 publication records with concrete scoped templates."""
    required = {name for name, _type, _description in CUSTOM_FIELDS}
    missing = sorted(required.difference(field_ids))
    if missing:
        raise ValueError(f"missing custom field IDs: {', '.join(missing)}")

    publishers: list[dict[str, Any]] = []
    for spec in PUBLISHER_SPECS:
        publisher = dict(spec)
        templates: list[dict[str, Any]] = []
        if spec.get("authored", True):
            if spec.get("jsonld_kind") == "live_blog":
                templates.append(
                    {
                        "name": f"tmpl: {spec['name']} · live-blog-jsonld",
                        **live_blog_jsonld(field_ids),
                    }
                )
            templates.append(
                {
                    "name": f"tmpl: {spec['name']} · article-jsonld",
                    **article_jsonld(field_ids),
                }
            )
            templates.append(
                {
                    "name": f"tmpl: {spec['name']} · article-meta",
                    **article_meta(field_ids, spec["name"]),
                }
            )
            if spec.get("body_selectors"):
                templates.append(
                    {
                        "name": f"tmpl: {spec['name']} · body-css",
                        **css_body(field_ids, spec["body_selectors"]),
                    }
                )
        publisher["templates"] = templates
        publishers.append(publisher)
    return publishers


def build_stack_entries(
    publishers: list[dict[str, Any]],
    template_ids_by_name: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Build ordered Python SDK stack entries from registered template names."""
    entries: list[dict[str, Any]] = []
    for publisher in publishers:
        for template in publisher["templates"]:
            entries.append(
                {
                    "template_id": template_ids_by_name[template["name"]],
                    "hosts": list(publisher["hosts"]),
                    "url_patterns": list(publisher["url_patterns"]),
                }
            )
    return entries


def seeds() -> list[str]:
    """Return every source, including fallback-only diagnostic cases."""
    return [spec["seed"] for spec in PUBLISHER_SPECS]
