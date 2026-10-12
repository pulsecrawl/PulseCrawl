import json
from datetime import datetime, timezone

import pytest

from pulsecrawl.core.model import FetchResult

from pulsecrawl import crawl


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    async def fetch(self, url: str, *, user_agent: str) -> FetchResult:
        fetched_at = datetime(2026, 8, 21, tzinfo=timezone.utc)
        body = self.pages.get(url)
        if body is None:
            return FetchResult(url=url, final_url=url, status=404, headers={}, body=None,
                               error="HTTP 404", fetched_at=fetched_at)
        return FetchResult(url=url, final_url=url, status=200,
                           headers={"Content-Type": "text/html"}, body=body,
                           error=None, fetched_at=fetched_at)


FIELDS = [
    {"fieldId": "fld_title", "name": "title", "type": "string"},
    {"fieldId": "fld_price", "name": "price", "type": "number"},
]


class TestLocalCrawl:
    def test_sync_crawl_returns_typed_records(self):
        fetcher = FakeFetcher({
            "https://x.example/": '<h1>A</h1><i class="p">$3.50</i><a href="/b">b</a>',
            "https://x.example/b": '<h1>B</h1><i class="p">$4.00</i>',
        })
        result = crawl(
            ["https://x.example/"],
            engine="css",
            mappings={"fld_title": "h1", "fld_price": ".p"},
            fields=FIELDS,
            politeness={"requestsPerSecond": 1000, "respectRobotsTxt": False},
            fetcher=fetcher,
        )
        assert result.stats["pagesFetched"] == 2
        assert {r["title"] for r in result.records} == {"A", "B"}
        assert {r["price"] for r in result.records} == {3.5, 4.0}
        assert all("_source_url" in r and "_crawled_at" in r for r in result.records)

    def test_to_jsonl_writes_rows(self, tmp_path):
        fetcher = FakeFetcher({"https://x.example/": "<h1>Only</h1>"})
        result = crawl(
            ["https://x.example/"],
            engine="css",
            mappings={"fld_title": "h1"},
            fields=FIELDS[:1],
            politeness={"requestsPerSecond": 1000, "respectRobotsTxt": False},
            fetcher=fetcher,
        )
        path = tmp_path / "out.jsonl"
        assert result.to_jsonl(str(path)) == 1
        row = json.loads(path.read_text().splitlines()[0])
        assert row["title"] == "Only"

    def test_persistent_crawl_can_disable_in_memory_record_collection(self, tmp_path):
        result = crawl(
            ["https://x.example/"],
            engine="css",
            mappings={"fld_title": "h1"},
            fields=FIELDS[:1],
            dataset=str(tmp_path / "bounded"),
            collect_records=False,
            politeness={"requestsPerSecond": 1000, "respectRobotsTxt": False},
            fetcher=FakeFetcher({"https://x.example/": "<h1>Persisted</h1>"}),
        )
        assert result.records == []
        assert result.stats["recordsExtracted"] == 1
        rows = result.sql("SELECT title FROM records")
        assert rows == [{"title": "Persisted"}]

    def test_scoped_stack_then_system_fallback(self):
        fetcher = FakeFetcher({
            "https://a.example/story": '<h1>A</h1><meta property="og:title" content="Generic A">',
            "https://b.example/story": '<meta property="og:title" content="Generic B">',
        })
        result = crawl(
            ["https://a.example/story", "https://b.example/story"],
            templates=[{
                "template_id": "a-specific",
                "engine": "css",
                "mappings": {"fld_title": "h1"},
                "hosts": ["a.example"],
                "url_patterns": ["/story*"],
            }],
            system_templates=[{
                "template_id": "system-og",
                "engine": "meta",
                "mappings": {"fld_title": "og:title"},
            }],
            fields=FIELDS[:1],
            scope={"sameDomainOnly": False},
            politeness={"requestsPerSecond": 1000, "respectRobotsTxt": False},
            fetcher=fetcher,
        )
        by_url = {row["_source_url"]: row for row in result.records}
        assert by_url["https://a.example/story"]["title"] == "A"
        assert by_url["https://a.example/story"]["_match_tier"] == "scoped"
        assert by_url["https://b.example/story"]["title"] == "Generic B"
        assert by_url["https://b.example/story"]["_template_origin"] == "system"
        assert result.stats["templateCoverage"]["b.example"]["needsTemplate"] is True

    def test_rejects_mixed_legacy_and_stack_inputs(self):
        try:
            crawl(
                ["https://x.example/"],
                engine="css",
                mappings={"fld_title": "h1"},
                templates=[{"engine": "css", "mappings": {"fld_title": "h1"}}],
                fields=FIELDS[:1],
            )
        except ValueError as exc:
            assert "not both" in str(exc)
        else:
            raise AssertionError("expected a ValueError")


class TestLocalDataset:
    def test_dataset_folder_mirrors_cloud_layout(self, tmp_path):
        import json as _json

        fetcher = FakeFetcher({"https://x.example/": "<h1>One</h1>"})
        dataset = tmp_path / "pages"
        result = crawl(
            seeds=["https://x.example/"],
            engine="css",
            mappings={"fld_title": "h1"},
            fields=FIELDS[:1],
            dataset=str(dataset),
            store_raw_pages=True,
            politeness={"requestsPerSecond": 1000, "respectRobotsTxt": False},
            fetcher=fetcher,
        )
        execution_dir = dataset / "executions" / result.execution_id
        assert (execution_dir / "_manifest.json").exists()
        assert (execution_dir / "records-000.jsonl").exists()
        assert len(list((execution_dir / "pages").glob("*.json"))) == 1
        row = _json.loads((execution_dir / "records-000.jsonl").read_text().splitlines()[0])
        assert row["title"] == "One" and row["_execution_id"] == result.execution_id
        manifest = _json.loads((execution_dir / "_manifest.json").read_text())
        assert manifest["recordChunks"] == 1 and manifest["stats"]["pagesFetched"] == 1

    def test_runs_accumulate_under_one_dataset(self, tmp_path):
        fetcher = FakeFetcher({"https://x.example/": "<h1>Run</h1>"})
        dataset = tmp_path / "pages"
        kwargs = dict(
            seeds=["https://x.example/"], engine="css", mappings={"fld_title": "h1"},
            fields=FIELDS[:1], dataset=str(dataset),
            politeness={"requestsPerSecond": 1000, "respectRobotsTxt": False}, fetcher=fetcher,
        )
        first = crawl(**kwargs)
        second = crawl(**kwargs)
        assert first.execution_id != second.execution_id
        assert len(list((dataset / "executions").iterdir())) == 2


class TestLocalSql:
    def test_sql_over_in_memory_records(self):
        fetcher = FakeFetcher({
            "https://x.example/": '<h1>A</h1><i class="p">$5</i><a href="/b">b</a>',
            "https://x.example/b": '<h1>B</h1><i class="p">$7</i>',
        })
        result = crawl(
            seeds=["https://x.example/"], engine="css",
            mappings={"fld_title": "h1", "fld_price": ".p"}, fields=FIELDS,
            politeness={"requestsPerSecond": 1000, "respectRobotsTxt": False}, fetcher=fetcher,
        )
        rows = result.sql("SELECT title, price FROM records ORDER BY price DESC")
        assert rows[0]["title"] == "B" and rows[0]["price"] == 7.0
        with pytest.raises(Exception, match="external|permission|allowed|disabled"):
            result.sql("SELECT * FROM read_csv_auto('/etc/passwd')")
        with pytest.raises(ValueError, match="row_cap"):
            result.sql("SELECT * FROM records", row_cap=1)

    def test_sql_over_dataset_folder_spans_runs(self, tmp_path):
        fetcher = FakeFetcher({"https://x.example/": "<h1>Run</h1>"})
        kwargs = dict(
            seeds=["https://x.example/"], engine="css", mappings={"fld_title": "h1"},
            fields=FIELDS[:1], dataset=str(tmp_path / "d"),
            politeness={"requestsPerSecond": 1000, "respectRobotsTxt": False}, fetcher=fetcher,
        )
        crawl(**kwargs)
        second = crawl(**kwargs)
        rows = second.sql("SELECT count(*) AS n, count(DISTINCT _execution_id) AS runs FROM records")
        assert rows == [{"n": 2, "runs": 2}]
