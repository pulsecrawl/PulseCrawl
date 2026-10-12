from pulsecrawl.core import crawl

from .conftest import FakeFetcher

FIELDS = (
    {"fieldId": "fld_title", "name": "title", "type": "string"},
    {"fieldId": "fld_price", "name": "price", "type": "number"},
)


class TestLocalCrawl:
    async def test_end_to_end_with_injected_fetcher(self):
        fetcher = FakeFetcher()
        fetcher.add(
            "https://x.example/",
            '<h1>Item</h1><span class="p">$5.00</span><a href="/2">2</a>',
        )
        fetcher.add("https://x.example/2", '<h1>Two</h1><span class="p">$6.00</span>')

        result = await crawl(
            seeds=["https://x.example/"],
            engine="css",
            mappings={"fld_title": "h1", "fld_price": ".p"},
            fields=FIELDS,
            politeness={"requestsPerSecond": 1000, "respectRobotsTxt": False},
            fetcher=fetcher,
        )

        assert result.stats.pages_fetched == 2
        dicts = result.to_dicts()
        assert {d["title"] for d in dicts} == {"Item", "Two"}
        assert all("_source_url" in d and "_crawled_at" in d for d in dicts)

    async def test_scope_and_mapping_list_passthrough(self):
        fetcher = FakeFetcher()
        fetcher.add("https://x.example/", '<meta property="og:title" content="OG"><a href="/skip">s</a>')

        result = await crawl(
            seeds=["https://x.example/"],
            engine="meta",
            mappings={"fld_title": ["og:missing", "og:title"]},
            fields=FIELDS[:1],
            scope={"maxPages": 1, "maxDepth": 0},
            politeness={"requestsPerSecond": 1000, "respectRobotsTxt": False},
            fetcher=fetcher,
        )

        assert result.stats.pages_fetched == 1
        assert result.to_dicts()[0]["title"] == "OG"
