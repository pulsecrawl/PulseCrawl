import pytest

from pulsecrawl.core.extraction import get_engine
from pulsecrawl.core.extraction.css import extract_css
from pulsecrawl.core.extraction.jsonld import extract_jsonld
from pulsecrawl.core.extraction.meta import extract_meta


def m(**kwargs):
    """mappings shorthand: value may be str or tuple."""
    return {k: (v,) if isinstance(v, str) else tuple(v) for k, v in kwargs.items()}


class TestCss:
    HTML = """
    <html><head><meta property="og:title" content="OG Name"></head>
    <body><h1>  Page Name </h1><span class="price">$9.99</span></body></html>
    """

    def test_text_and_attr_selection(self):
        records = extract_css(self.HTML, m(fld_title="h1", fld_price=".price"))
        assert records == [{"fld_title": "Page Name", "fld_price": "$9.99"}]

    def test_attr_convention(self):
        records = extract_css(self.HTML, m(fld_title="meta[property='og:title']@content"))
        assert records == [{"fld_title": "OG Name"}]

    def test_fallback_chain_tries_in_order(self):
        records = extract_css(
            self.HTML, m(fld_title=["h2", "meta[property='og:title']@content", "h1"])
        )
        assert records == [{"fld_title": "OG Name"}]

    def test_no_matches_yields_no_records(self):
        assert extract_css("<p>nothing</p>", m(fld_title="h1")) == []

    def test_missing_attr_and_empty_expr_are_skipped(self):
        assert extract_css(self.HTML, m(fld_title="h1@missing")) == []
        assert extract_css(self.HTML, m(fld_title="@content")) == []


class TestJsonLd:
    LISTING = """
    <script type="application/ld+json">
    {"@context": "https://schema.org", "@graph": [
      {"@type": "Product", "name": "A", "offers": {"price": "10.00", "priceCurrency": "EUR"}},
      {"@type": "Product", "name": "B", "offers": [{"price": "20.00"}]},
      {"@type": "BreadcrumbList", "name": "crumbs"}
    ]}
    </script>
    """

    def test_one_record_per_matching_entity(self):
        records = extract_jsonld(
            self.LISTING, m(fld_title="Product.name", fld_price="Product.offers.price")
        )
        assert {r["fld_title"] for r in records} == {"A", "B"}
        assert all("fld_price" in r for r in records)

    def test_type_may_be_a_list_and_is_case_insensitive(self):
        html = """<script type="application/ld+json">
        {"@type": ["Article", "NewsArticle"], "headline": "H"}</script>"""
        assert extract_jsonld(html, m(fld_title="article.headline")) == [{"fld_title": "H"}]

    def test_ignores_broken_json_and_missing_paths(self):
        html = '<script type="application/ld+json">{not json}</script>' + self.LISTING
        records = extract_jsonld(html, m(fld_title="Product.name", fld_x="Product.nope.deep"))
        assert len(records) == 2
        assert all("fld_x" not in r for r in records)

    def test_no_jsonld_yields_nothing(self):
        assert extract_jsonld("<p>plain</p>", m(fld_title="Product.name")) == []

    def test_subtypes_match_their_parent_type(self):
        # Real pages declare subtypes (NewsArticle, BlogPosting): a mapping
        # written against the parent (Article) must still match them.
        html = """<script type="application/ld+json">
        [{"@type": "NewsArticle", "headline": "N", "author": {"@type": "Person", "name": "Ana"}},
         {"@type": "BlogPosting", "headline": "B"},
         {"@type": "WebSite", "headline": "ignored"}]</script>"""
        records = extract_jsonld(html, m(fld_title="Article.headline", fld_author="Article.author.name"))
        assert sorted(records, key=lambda r: r["fld_title"]) == [
            {"fld_title": "B"},
            {"fld_title": "N", "fld_author": "Ana"},
        ]


class TestMeta:
    HTML = """
    <html><head>
      <title>Doc Title</title>
      <meta property="og:title" content="OG Title">
      <meta name="description" content="A description">
      <meta property="og:title" content="dup ignored">
    </head><body></body></html>
    """

    def test_property_and_name_lookup(self):
        records = extract_meta(self.HTML, m(fld_title="og:title", fld_desc="description"))
        assert records == [{"fld_title": "OG Title", "fld_desc": "A description"}]

    def test_title_expression_and_fallback(self):
        records = extract_meta(self.HTML, m(fld_title=["og:missing", "<title>"]))
        assert records == [{"fld_title": "Doc Title"}]

    def test_no_matches_yields_no_records(self):
        assert extract_meta("<html><head></head></html>", m(fld_title="og:title")) == []


def test_get_engine_dispatch():
    assert get_engine("css") is extract_css
    assert get_engine("jsonld") is extract_jsonld
    assert get_engine("meta") is extract_meta
    with pytest.raises(ValueError):
        get_engine("xpath")  # type: ignore[arg-type]


class TestDeepExtraction:
    """The features real newspapers forced: joins, literals, body text."""

    def test_css_all_suffix_joins_every_match(self):
        html = "<div class='body'><p>One.</p><p>Two.</p></div><p>outside</p>"
        assert extract_css(html, m(fld_body="div.body p::all")) == [{"fld_body": "One.\n\nTwo."}]

    def test_css_literal_expression(self):
        records = extract_css("<h1>T</h1>", m(fld_title="h1", fld_city="literal:Cd. Juárez"))
        assert records == [{"fld_title": "T", "fld_city": "Cd. Juárez"}]

    def test_meta_literal_fills_but_never_creates_a_record(self):
        html = '<meta property="og:title" content="H">'
        records = extract_meta(html, m(fld_title="og:title", fld_city="literal:Parral"))
        assert records == [{"fld_title": "H", "fld_city": "Parral"}]
        # a page matching nothing real yields nothing, literals or not
        assert extract_meta("<p>x</p>", m(fld_city="literal:Parral")) == []

    def test_jsonld_scalar_lists_join(self):
        html = """<script type="application/ld+json">
        {"@type": "NewsArticle", "headline": "H", "keywords": ["a", "b"]}</script>"""
        records = extract_jsonld(html, m(fld_title="Article.headline", fld_tags="Article.keywords"))
        assert records == [{"fld_title": "H", "fld_tags": "a, b"}]
