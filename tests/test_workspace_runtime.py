import asyncio
import json
from datetime import datetime, timezone

import pytest
from pulsecrawl.core.model import FetchResult, FrontierUrl, Record, RobotsCacheEntry, VisitedRow
from pulsecrawl.core.urls import url_hash

from pulsecrawl import Workspace
from pulsecrawl.cli import main
from pulsecrawl.local_dataset import LocalDatasetReader, normalize_url_identity
from pulsecrawl.local_dataset import LocalDatasetWriter
from pulsecrawl.local_scheduler import recover_incomplete, validate_cron
from pulsecrawl.sqlite_state import (
    EpochClock,
    SQLiteFrontier,
    SQLiteHostGate,
    SQLiteRobotsCache,
    SQLiteVisitedStore,
)


FIELDS = [
    {"fieldId": "fld_title", "name": "title", "type": "string"},
    {"fieldId": "fld_url", "name": "canonical", "type": "url"},
]


class FakeFetcher:
    def __init__(self, pages, *, fetched_at=None):
        self.pages = pages
        self.calls = []
        self.fetched_at = fetched_at or datetime(2026, 8, 25, 6, 10, tzinfo=timezone.utc)

    async def fetch(self, url, *, user_agent):
        self.calls.append((url, user_agent))
        body = self.pages.get(url)
        return FetchResult(
            url=url,
            final_url=url,
            status=200 if body is not None else 404,
            headers={},
            body=body,
            error=None if body is not None else "HTTP 404",
            fetched_at=self.fetched_at,
        )


class BlockingFetcher:
    def __init__(self):
        self.started = asyncio.Event()

    async def fetch(self, url, *, user_agent):
        self.started.set()
        await asyncio.Event().wait()


@pytest.fixture
def workspace(tmp_path):
    value = Workspace.init(tmp_path / "workspace", name="tests")
    yield value
    value.close()


def make_dataset(workspace, *, mode="append_all"):
    return workspace.datasets.create("articles", fields=FIELDS, mode=mode)


def make_job(workspace, dataset, *, raw=False, max_total=100, system=()):
    return workspace.jobs.create(
        "news",
        seeds=["https://a.example/"],
        dataset_id=dataset["datasetId"],
        templates=[{
            "template_id": "specific",
            "engine": "css",
            "mappings": {"fld_title": "h1", "fld_url": "link[rel=canonical]@href"},
            "hosts": ["a.example"],
        }],
        system_templates=system,
        scope={"maxDepth": 1, "maxUrlsPerExecution": 10, "maxUrlsTotal": max_total},
        politeness={"respectRobotsTxt": False, "requestsPerSecond": 1000},
        store_raw_pages=raw,
    )


def test_workspace_init_create_and_validate(tmp_path):
    root = tmp_path / "portable"
    with Workspace.init(root, name="portable") as workspace:
        assert json.loads((root / "pulsecrawl.json").read_text())["name"] == "portable"
        dataset = make_dataset(workspace)
        job = make_job(workspace, dataset)
        assert workspace.datasets.get(dataset["datasetId"])["name"] == "articles"
        assert workspace.jobs.get(job["jobId"])["scope"]["maxDepth"] == 1
        assert workspace.validate() == {
            "valid": True, "errors": [], "jobs": 1, "datasets": 1, "executions": 0
        }
    with Workspace(root) as reopened:
        assert len(reopened.jobs.list()) == len(reopened.datasets.list()) == 1


def test_workspace_rejects_bad_definitions(workspace):
    with pytest.raises(ValueError, match="mode"):
        workspace.datasets.create("bad", fields=FIELDS, mode="overwrite")
    with pytest.raises(ValueError, match="url field"):
        workspace.datasets.create(
            "bad-identity", fields=FIELDS, identity_field="fld_title"
        )
    with pytest.raises(ValueError, match="unsupported field"):
        workspace.datasets.create(
            "bad-type",
            fields=[{"fieldId": "bad", "name": "bad", "type": "object"}],
        )
    with pytest.raises(ValueError, match="unique"):
        workspace.datasets.create(
            "duplicate-fields",
            fields=[FIELDS[0], {**FIELDS[1], "name": "TITLE"}],
        )


def test_directory_catalog_can_define_schema_template_and_job(workspace):
    title = workspace.fields.create("headline", "string", field_id="fld_headline")
    canonical = workspace.fields.create("canonical", "url", field_id="fld_canonical")
    schema = workspace.schemas.create(
        "article", [title["fieldId"], canonical["fieldId"]], schema_id="schema_article"
    )
    template = workspace.templates.create(
        "article meta",
        output_schema_id=schema["schemaId"],
        engine="meta",
        mappings={"fld_headline": ["og:title", "<title>"]},
        template_id="tmpl_article",
    )
    dataset = workspace.datasets.create(
        "catalog dataset", schema_id=schema["schemaId"], identity_field="fld_canonical"
    )
    job = workspace.jobs.create(
        "catalog job",
        seeds=["https://catalog.example/"],
        dataset_id=dataset["datasetId"],
        templates=[{"template_id": template["templateId"], "hosts": ["catalog.example"]}],
        politeness={"respectRobotsTxt": False, "requestsPerSecond": 1000},
    )
    assert job["templates"][0]["engine"] == "meta"
    assert job["templates"][0]["scope"]["hosts"] == ["catalog.example"]
    assert (workspace.path / "fields" / "fld_headline.json").exists()
    assert (workspace.path / "schemas" / "schema_article.json").exists()
    assert (workspace.path / "templates" / "custom" / "tmpl_article.json").exists()
    with pytest.raises(ValueError, match="unsupported field"):
        workspace.fields.create("bad", "object")
    with pytest.raises(ValueError, match="unsupported template"):
        workspace.templates.create(
            "bad", output_schema_id=schema["schemaId"], engine="xpath", mappings={}
        )
    dataset = workspace.datasets.create(
        "custom", fields=FIELDS, identity_field="fld_url"
    )
    assert dataset["identityColumn"] == "canonical"
    with pytest.raises(ValueError, match="at least one seed"):
        workspace.jobs.create(
            "bad", seeds=[], dataset_id=dataset["datasetId"], templates=[{
                "engine": "css", "mappings": {"fld_title": "h1"}
            }]
        )
    with pytest.raises(ValueError, match="absolute HTTP"):
        workspace.jobs.create(
            "bad-seed", seeds=["not a url"], dataset_id=dataset["datasetId"],
            templates=[{"engine": "css", "mappings": {"fld_title": "h1"}}],
        )
    with pytest.raises(ValueError, match="outside the dataset"):
        workspace.jobs.create(
            "bad-mapping", seeds=["https://x.test"], dataset_id=dataset["datasetId"],
            templates=[{"engine": "css", "mappings": {"fld_missing": "h1"}}],
        )
    with pytest.raises(ValueError, match="maxUrlsTotal"):
        workspace.jobs.create(
            "bad-budget", seeds=["https://x.test"], dataset_id=dataset["datasetId"],
            templates=[{"engine": "css", "mappings": {"fld_title": "h1"}}],
            scope={"maxUrlsPerExecution": 10, "maxUrlsTotal": 9},
        )
    upper_bound = workspace.jobs.create(
        "ten-million-budget", seeds=["https://x.test"], dataset_id=dataset["datasetId"],
        templates=[{"engine": "css", "mappings": {"fld_title": "h1"}}],
        scope={"maxUrlsPerExecution": 1_000_000, "maxUrlsTotal": 10_000_000},
    )
    assert upper_bound["scope"]["maxUrlsTotal"] == 10_000_000
    with pytest.raises(ValueError, match="maxUrlsTotal"):
        workspace.jobs.create(
            "over-budget", seeds=["https://x.test"], dataset_id=dataset["datasetId"],
            templates=[{"engine": "css", "mappings": {"fld_title": "h1"}}],
            scope={"maxUrlsPerExecution": 1_000_000, "maxUrlsTotal": 10_000_001},
        )


def test_append_all_runs_publish_hourly_snapshots_and_query_versions(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset, raw=True)
    first = workspace.jobs.run(
        job["jobId"],
        fetcher=FakeFetcher({
            "https://a.example/": '<h1>A</h1><link rel="canonical" href="https://a.example/"><a href="/b">B</a>',
            "https://a.example/b": '<h1>B</h1><link rel="canonical" href="https://a.example/b">',
        }),
    )
    assert first["status"] == "succeeded"
    assert first["stats"]["urls_attempted"] == 2
    assert first["stats"]["materializedRows"] == 2
    files = workspace.datasets.files(dataset["datasetId"])
    assert len(files) == 1
    assert f"/hour={files[0]['ingestHour']:02d}/" in f"/{files[0]['path']}"
    import pyarrow.parquet as pq

    schema = pq.read_schema(
        workspace.path / "datasets" / dataset["datasetId"] / files[0]["path"]
    )
    assert str(schema.field("_scheduled_for").type) == "timestamp[us, tz=UTC]"
    assert str(schema.field("_crawled_at").type) == "timestamp[us, tz=UTC]"
    assert (workspace.path / "executions" / first["executionId"] / "pages").exists()

    second = workspace.jobs.run(
        job["jobId"],
        fetcher=FakeFetcher({"https://a.example/": '<h1>A2</h1><link rel="canonical" href="https://a.example/">'}),
    )
    assert second["stats"]["materializedRows"] == 1
    current = workspace.datasets.query(
        dataset["datasetId"],
        "SELECT count(*) AS n, count(distinct _execution_id) AS runs FROM dataset",
    )
    assert current["rows"] == [[3, 2]]
    recent = workspace.datasets.query(
        dataset["datasetId"],
        "SELECT count(*) AS n FROM dataset WHERE _crawled_at >= TIMESTAMPTZ '2026-08-25 06:00:00+00'",
    )
    assert recent["rows"] == [[3]]
    timestamp_range = workspace.datasets.query(
        dataset["datasetId"],
        "SELECT min(_crawled_at), max(_crawled_at) FROM dataset",
    )
    assert all(value.endswith("+00:00") for value in timestamp_range["rows"][0])
    version_one = workspace.datasets.query(
        dataset["datasetId"], "SELECT count(*) AS n FROM dataset", version=1
    )
    assert version_one["rows"] == [[2]]
    with pytest.raises(ValueError, match="only SELECT"):
        workspace.datasets.query(dataset["datasetId"], "DELETE FROM dataset")
    with pytest.raises(ValueError, match="single statement"):
        workspace.datasets.query(dataset["datasetId"], "SELECT 1; SELECT 2")


def test_new_urls_only_keeps_first_execution_entities_and_tracks_repeats(workspace):
    dataset = make_dataset(workspace, mode="new_urls_only")
    job = make_job(workspace, dataset)
    page = '<h1>A</h1><link rel="canonical" href="https://a.example/">'
    first = workspace.jobs.run(job["jobId"], fetcher=FakeFetcher({"https://a.example/": page}))
    second = workspace.jobs.run(job["jobId"], fetcher=FakeFetcher({"https://a.example/": page}))
    assert first["stats"]["materializedRows"] == 1
    assert second["stats"]["materializedRows"] == 0
    assert len(workspace.datasets.files(dataset["datasetId"])) == 1
    urls = workspace.datasets.urls(dataset["datasetId"], newness="repeat")
    assert urls["urls"][0]["seenCount"] == 2
    assert urls["urls"][0]["executionCount"] == 2
    assert urls["urls"][0]["isNew"] is False
    assert workspace.datasets.urls(dataset["datasetId"], newness="new")["urls"] == []


def test_dataset_url_pagination_filters_and_identity_normalization(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    workspace.jobs.run(
        job["jobId"],
        fetcher=FakeFetcher({
            "https://a.example/": '<h1>A</h1><link rel="canonical" href="https://a.example/"><a href="/b">B</a>',
            "https://a.example/b": '<h1>B</h1><link rel="canonical" href="https://a.example/b">',
        }),
    )
    first = workspace.datasets.urls(dataset["datasetId"], limit=1)
    assert len(first["urls"]) == 1 and first["nextCursor"]
    second = workspace.datasets.urls(
        dataset["datasetId"], cursor=first["nextCursor"], limit=1
    )
    assert first["urls"][0]["url"] != second["urls"][0]["url"]
    assert len(workspace.datasets.urls(dataset["datasetId"], host="a.example")["urls"]) == 2
    assert len(workspace.datasets.urls(dataset["datasetId"], url_contains="/b")["urls"]) == 1
    with pytest.raises(ValueError, match="invalid cursor"):
        workspace.datasets.urls(dataset["datasetId"], cursor="bad")
    assert normalize_url_identity("HTTPS://Exämple.com:443/%7e?q=2&a=1#x") == (
        "https://xn--exmple-cua.com/~?a=1&q=2"
    )
    assert normalize_url_identity("ftp://x.example") is None


def test_execution_url_pages_are_parquet_backed_and_filter_before_paging(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    first = workspace.jobs.run(
        job["jobId"],
        fetcher=FakeFetcher({
            "https://a.example/": '<h1>A</h1><link rel="canonical" href="https://a.example/"><a href="/b">B</a>',
            "https://a.example/b": '<h1>B</h1><link rel="canonical" href="https://a.example/b">',
        }),
    )
    second = workspace.jobs.run(
        job["jobId"],
        fetcher=FakeFetcher({
            "https://a.example/": '<h1>A2</h1><link rel="canonical" href="https://a.example/">'
        }),
    )

    page_one = workspace.executions.urls(first["executionId"], limit=1, newness="new")
    assert len(page_one["urls"]) == 1
    assert page_one["urls"][0]["executionId"] == first["executionId"]
    assert page_one["urls"][0]["isNew"] is True
    assert page_one["nextCursor"]
    page_two = workspace.executions.urls(
        first["executionId"], cursor=page_one["nextCursor"], limit=1,
        newness="new", host="a.example",
    )
    assert len(page_two["urls"]) == 1
    assert page_two["urls"][0]["url"] != page_one["urls"][0]["url"]
    assert workspace.executions.urls(
        first["executionId"], url_contains="/b", newness="new"
    )["urls"][0]["url"].endswith("/b")
    repeated = workspace.executions.urls(second["executionId"], newness="repeat")
    assert len(repeated["urls"]) == 1 and repeated["urls"][0]["isNew"] is False
    assert workspace.executions.urls(second["executionId"], newness="new")["urls"] == []
    with pytest.raises(ValueError, match="limit"):
        workspace.executions.urls(first["executionId"], limit=0)
    with pytest.raises(ValueError, match="newness"):
        workspace.executions.urls(first["executionId"], newness="sometimes")
    with pytest.raises(ValueError, match="cursor"):
        workspace.executions.urls(first["executionId"], cursor="bad")


def test_new_urls_only_execution_page_omits_suppressed_repeats(workspace):
    dataset = make_dataset(workspace, mode="new_urls_only")
    job = make_job(workspace, dataset)
    page = '<h1>A</h1><link rel="canonical" href="https://a.example/">'
    workspace.jobs.run(job["jobId"], fetcher=FakeFetcher({"https://a.example/": page}))
    repeated = workspace.jobs.run(
        job["jobId"], fetcher=FakeFetcher({"https://a.example/": page})
    )
    assert workspace.executions.urls(repeated["executionId"])["urls"] == []


def test_compaction_replaces_active_files_but_preserves_old_snapshot(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    page = '<h1>A</h1><link rel="canonical" href="https://a.example/">'
    workspace.jobs.run(job["jobId"], fetcher=FakeFetcher({"https://a.example/": page}))
    workspace.jobs.run(job["jobId"], fetcher=FakeFetcher({"https://a.example/": page}))
    before = workspace.datasets.query(dataset["datasetId"], "SELECT count(*) n FROM dataset")
    old_paths = {item["path"] for item in workspace.datasets.files(dataset["datasetId"])}
    assert workspace.datasets.compact(dataset["datasetId"]) == 1
    active = workspace.datasets.files(dataset["datasetId"])
    assert len(active) == 1 and active[0]["kind"] == "compact"
    assert workspace.datasets.query(dataset["datasetId"], "SELECT count(*) n FROM dataset") == before
    assert workspace.datasets.query(
        dataset["datasetId"], "SELECT count(*) n FROM dataset", version=2
    ) == before
    assert all((workspace.path / "datasets" / dataset["datasetId"] / p).exists() for p in old_paths)


def test_system_fallback_and_lifetime_budget(workspace):
    dataset = make_dataset(workspace)
    job = make_job(
        workspace,
        dataset,
        max_total=10,
        system=[{"template_id": "system", "engine": "meta", "mappings": {"fld_title": "og:title"}}],
    )
    execution = workspace.jobs.run(
        job["jobId"],
        fetcher=FakeFetcher({"https://a.example/": '<meta property="og:title" content="Generic">'}),
    )
    row = workspace.datasets.query(dataset["datasetId"], "SELECT title,_match_tier FROM dataset")["rows"][0]
    assert row == ["Generic", "system_fallback"]
    budget = workspace.state.execute(
        "SELECT urls_used,urls_reserved FROM jobs WHERE job_id=?", (job["jobId"],)
    ).fetchone()
    assert tuple(budget) == (1, 0)
    assert workspace.executions.get(execution["executionId"])["intent"]["scope"]["maxUrlsPerExecution"] == 10


def test_resume_reconciles_crash_between_admission_and_frontier(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    execution = workspace.jobs.prepare(job["jobId"])
    hashed = url_hash("https://a.example/")
    workspace.state.execute(
        "UPDATE executions SET status='running',started_at=? WHERE execution_id=?",
        (datetime.now(timezone.utc).isoformat(), execution["executionId"]),
    )
    visited = SQLiteVisitedStore(workspace.state)
    import asyncio

    asyncio.run(
        visited.add(
            execution["executionId"],
            [VisitedRow(hashed, "https://a.example/", "queued", 0)],
        )
    )
    result = workspace.executions.resume(
        execution["executionId"],
        fetcher=FakeFetcher({"https://a.example/": "<h1>Recovered</h1>"}),
    )
    assert result["status"] == "succeeded"
    assert result["stats"]["urls_attempted"] == 1
    assert workspace.state.execute(
        "SELECT count(*) n FROM frontier WHERE execution_id=?", (execution["executionId"],)
    ).fetchone()["n"] == 0


@pytest.mark.asyncio
async def test_staged_record_and_url_observation_are_idempotent(workspace):
    dataset = make_dataset(workspace, mode="new_urls_only")
    job = make_job(workspace, dataset)
    execution = workspace.jobs.prepare(job["jobId"])
    writer = LocalDatasetWriter(
        state=workspace.state,
        workspace=workspace.path,
        dataset=dataset,
        execution_id=execution["executionId"],
        job_id=job["jobId"],
        schema_id=dataset["schemaId"],
        started_at=execution["createdAt"],
        scheduled_for=None,
        store_raw_pages=False,
    )
    record = Record(
        fields={"title": "A", "canonical": "https://a.example/"},
        source_url="https://a.example/",
        fetched_at=datetime(2026, 8, 25, 6, 10, tzinfo=timezone.utc),
        template_id="specific",
        template_origin="org",
        match_tier="scoped",
    )
    replay = Record(
        fields={"title": "changed during replay", "canonical": "https://a.example/"},
        source_url=record.source_url,
        fetched_at=datetime(2026, 8, 25, 6, 11, tzinfo=timezone.utc),
        template_id=record.template_id,
        template_origin=record.template_origin,
        match_tier=record.match_tier,
    )
    await writer.emit([record])
    # The durable identity deliberately excludes response content and fetch
    # time. A replay after a hard loss keeps the already staged first output.
    await writer.emit([replay])
    await writer.emit([record])
    assert workspace.state.execute(
        "SELECT count(*) n FROM staged_records WHERE execution_id=?",
        (execution["executionId"],),
    ).fetchone()["n"] == 1
    ledger = workspace.state.execute(
        "SELECT seen_count,execution_count FROM url_ledger WHERE dataset_id=?",
        (dataset["datasetId"],),
    ).fetchone()
    assert tuple(ledger) == (1, 1)


@pytest.mark.parametrize("boundary", ["interruption", "terminal_failure", "committed"])
def test_new_url_publication_failure_boundaries(workspace, monkeypatch, boundary):
    """Characterize staging versus publication; do not imply cross-store atomicity."""
    dataset = make_dataset(workspace, mode="new_urls_only")
    job = make_job(workspace, dataset)
    pages = {"https://a.example/": "<h1>First observation</h1>"}
    original_finalize = LocalDatasetWriter.finalize
    original_finish = workspace.executions._finish

    def interrupt_finalize(self, **kwargs):
        if boundary == "terminal_failure":
            raise RuntimeError("injected before publication")
        raise asyncio.CancelledError

    def interrupt_finish(execution_id, **kwargs):
        if kwargs["status"] == "succeeded":
            raise asyncio.CancelledError
        return original_finish(execution_id, **kwargs)

    if boundary == "committed":
        monkeypatch.setattr(workspace.executions, "_finish", interrupt_finish)
    else:
        monkeypatch.setattr(LocalDatasetWriter, "finalize", interrupt_finalize)
    error = RuntimeError if boundary == "terminal_failure" else asyncio.CancelledError
    with pytest.raises(error):
        workspace.jobs.run(job["jobId"], fetcher=FakeFetcher(pages))
    execution = workspace.executions.list(job_id=job["jobId"])[0]
    execution_id = execution["executionId"]
    assert workspace.state.execute(
        "SELECT count(*) n FROM staged_records WHERE execution_id=?", (execution_id,)
    ).fetchone()["n"] == 1
    monkeypatch.setattr(LocalDatasetWriter, "finalize", original_finalize)
    monkeypatch.setattr(workspace.executions, "_finish", original_finish)

    if boundary == "terminal_failure":
        from pulsecrawl.errors import WorkspaceError
        assert execution["status"] == "failed"
        with pytest.raises(WorkspaceError, match="queued or running"):
            workspace.executions.resume(execution_id, fetcher=FakeFetcher(pages))
        later = workspace.jobs.run(job["jobId"], fetcher=FakeFetcher(pages))
        # First-observed does not mean first-published. A later execution
        # suppresses the identity even though the failed execution published none.
        assert later["stats"]["materializedRows"] == 0
        assert workspace.datasets.query(dataset["datasetId"], "SELECT * FROM dataset")["rows"] == []
    else:
        assert execution["status"] == "running"
        fetcher = FakeFetcher(pages)
        resumed = workspace.executions.resume(execution_id, fetcher=fetcher)
        assert resumed["status"] == "succeeded"
        assert fetcher.calls == []
        assert len(workspace.datasets.query(dataset["datasetId"], "SELECT * FROM dataset")["rows"]) == 1
        manifests = workspace.path / "datasets" / dataset["datasetId"] / "manifests"
        assert json.loads((manifests / "current.json").read_text())["version"] == 1
        assert len(list((manifests / "versions").glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_force_cancel_after_staging_preserves_observed_identity(workspace, monkeypatch):
    dataset = make_dataset(workspace, mode="new_urls_only")
    job = make_job(workspace, dataset)
    original_emit = LocalDatasetWriter.emit
    staged = asyncio.Event()

    async def pause_after_staging(self, records):
        await original_emit(self, records)
        staged.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(LocalDatasetWriter, "emit", pause_after_staging)
    execution = workspace.jobs.prepare(job["jobId"])
    execution_id = execution["executionId"]
    pages = {"https://a.example/": "<h1>First observation</h1>"}
    task = asyncio.create_task(workspace.executions._execute(
        execution_id, fetcher=FakeFetcher(pages)
    ))
    await asyncio.wait_for(staged.wait(), timeout=10)
    workspace.executions.cancel(execution_id, force=True)
    result = await asyncio.wait_for(task, timeout=10)
    assert result["status"] == "cancelled"
    assert workspace.state.execute(
        "SELECT count(*) n FROM staged_records WHERE execution_id=?", (execution_id,)
    ).fetchone()["n"] == 0
    monkeypatch.setattr(LocalDatasetWriter, "emit", original_emit)
    later_execution = workspace.jobs.prepare(job["jobId"])
    later = await workspace.executions._execute(
        later_execution["executionId"], fetcher=FakeFetcher(pages)
    )
    assert later["stats"]["materializedRows"] == 0
    assert workspace.datasets.query(dataset["datasetId"], "SELECT * FROM dataset")["rows"] == []


@pytest.mark.asyncio
async def test_sqlite_adapters_are_durable_and_shared(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    execution_id = "exec_ports"
    intent = {"seeds": [], "datasetId": dataset["datasetId"], "templateStack": job["templates"],
              "systemTemplates": [], "schema": job["schema"], "scope": job["scope"],
              "politeness": job["politeness"], "storeRawPages": False}
    workspace.state.execute(
        "INSERT INTO executions(execution_id,job_id,dataset_id,status,trigger,intent_json,reserved_urls,created_at) VALUES(?,?,?,'running','manual',?,0,?)",
        (execution_id, job["jobId"], dataset["datasetId"], json.dumps(intent), datetime.now(timezone.utc).isoformat()),
    )
    visited = SQLiteVisitedStore(workspace.state)
    hashed = url_hash("https://x/")
    await visited.add(execution_id, [VisitedRow(hashed, "https://x/", "queued", 0)])
    assert await visited.admitted(execution_id, hashed) and not await visited.seen(execution_id, hashed)
    frontier = SQLiteFrontier(workspace.state, execution_id, lease_seconds=0)
    await frontier.push([FrontierUrl("https://x/", 0)])
    assert (await frontier.pop_ready(datetime.now().timestamp())).url == "https://x/"
    assert (await frontier.pop_ready(datetime.now().timestamp())).url == "https://x/"
    await visited.add(execution_id, [VisitedRow(hashed, "https://x/", "fetched", 0)])
    assert await visited.seen(execution_id, hashed) and frontier.pending_count() == 0

    robots = SQLiteRobotsCache(workspace.state)
    entry = RobotsCacheEntry("User-agent: *", 123.0, False)
    await robots.put("https://x", entry)
    assert await SQLiteRobotsCache(workspace.state).get("https://x") == entry

    clock = EpochClock()
    gate_a = SQLiteHostGate(workspace.state, clock, platform_requests_per_second=5)
    gate_b = SQLiteHostGate(workspace.state, clock, platform_requests_per_second=5)
    assert await gate_a.reserve("local", "https://x", 1, 0) == 0
    assert await gate_b.reserve("local", "https://x", 1, 0) > 0


def test_scheduler_hourly_validation_and_due_execution(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    schedule = workspace.schedules.set(job["jobId"], "4 * * * *", timezone_name="UTC")
    assert schedule["status"] == "active"
    with pytest.raises(ValueError, match="at least one hour"):
        validate_cron("*/30 * * * *")
    with pytest.raises(ValueError, match="five-field"):
        validate_cron("0 * * * * *")
    workspace.state.execute(
        "UPDATE schedules SET next_run_at=? WHERE job_id=?",
        ("2026-01-01T00:04:00+00:00", job["jobId"]),
    )
    results = workspace.schedules.run_due(
        fetcher=FakeFetcher({"https://a.example/": "<h1>Scheduled</h1>"})
    )
    assert len(results) == 1 and results[0]["trigger"] == "schedule"
    assert workspace.schedules.pause(job["jobId"])["status"] == "paused"
    saved = json.loads(
        (workspace.path / "schedules" / f"{job['jobId']}.json").read_text()
    )
    assert saved["status"] == "paused"
    assert workspace.schedules.resume(job["jobId"])["status"] == "active"


def test_scheduler_recovers_queued_execution_after_restart(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    prepared = workspace.jobs.prepare(job["jobId"])

    recovered = recover_incomplete(
        workspace,
        fetcher=FakeFetcher({"https://a.example/": "<h1>Recovered</h1>"}),
    )

    assert [item["executionId"] for item in recovered] == [prepared["executionId"]]
    assert recovered[0]["status"] == "succeeded"


def test_scheduler_reclaims_only_expired_execution_lease(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    prepared = workspace.jobs.prepare(job["jobId"])
    execution_id = prepared["executionId"]
    workspace.state.execute(
        "UPDATE executions SET status='running' WHERE execution_id=?", (execution_id,)
    )
    workspace.state.execute(
        "INSERT INTO execution_leases VALUES(?,?,?,?)",
        (execution_id, "dead-runner", 0.0, 0.0),
    )
    workspace.state.execute(
        """
        INSERT INTO visited(execution_id,url_hash,url,status,depth,updated_at)
        VALUES(?,?,?,?,?,?)
        """,
        (execution_id, url_hash("https://a.example/"), "https://a.example/", "queued", 0, 0.0),
    )
    workspace.state.execute(
        """
        INSERT INTO frontier(
          execution_id,url_hash,url,depth,not_before,rate_scheduled,
          rate_slot_expires_at,rate_interval_s,state,lease_until
        ) VALUES(?,?,?,?,0,0,0,0,'leased',99999999999)
        """,
        (execution_id, url_hash("https://a.example/"), "https://a.example/", 0),
    )

    recovered = recover_incomplete(
        workspace,
        fetcher=FakeFetcher({"https://a.example/": "<h1>Reclaimed</h1>"}),
    )
    assert recovered[0]["status"] == "succeeded"
    assert workspace.state.execute(
        "SELECT 1 FROM execution_leases WHERE execution_id=?", (execution_id,)
    ).fetchone() is None

    active = workspace.jobs.prepare(job["jobId"])
    workspace.state.execute(
        "INSERT INTO execution_leases VALUES(?,?,?,?)",
        (active["executionId"], "live-runner", 99999999999.0, 1.0),
    )
    assert active["executionId"] not in workspace.executions.recoverable()
    assert recover_incomplete(workspace, fetcher=FakeFetcher({})) == []


@pytest.mark.asyncio
async def test_graceful_execution_cancellation_remains_recoverable(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    prepared = workspace.jobs.prepare(job["jobId"])
    fetcher = BlockingFetcher()
    task = asyncio.create_task(
        workspace.executions._execute(prepared["executionId"], fetcher=fetcher)
    )
    await fetcher.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    interrupted = workspace.executions.get(prepared["executionId"])
    assert interrupted["status"] == "running"
    assert interrupted["reservedUrls"] == 10
    assert prepared["executionId"] in workspace.executions.recoverable()
    assert workspace.state.execute(
        "SELECT 1 FROM execution_leases WHERE execution_id=?",
        (prepared["executionId"],),
    ).fetchone() is None
    resumed = await workspace.executions._execute(
        prepared["executionId"],
        fetcher=FakeFetcher({"https://a.example/": "<h1>Recovered now</h1>"}),
    )
    assert resumed["status"] == "succeeded"
    assert resumed["stats"]["urls_attempted"] == 1


def test_cli_init_validate_and_lists(tmp_path, capsys):
    root = tmp_path / "cli"
    assert main(["init", str(root), "--name", "cli"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert main(["--workspace", str(root), "validate"]) == 0
    capsys.readouterr()
    assert main(["--workspace", str(root), "job", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["--workspace", str(root), "dataset", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cli_dataset_execution_and_schedule_commands(workspace, capsys):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    execution = workspace.jobs.run(
        job["jobId"], fetcher=FakeFetcher({"https://a.example/": "<h1>A</h1>"})
    )
    workspace.schedules.set(job["jobId"], "4 * * * *")
    prefix = ["--workspace", str(workspace.path)]
    commands = [
        ["execution", "list", "--job-id", job["jobId"]],
        ["execution", "urls", execution["executionId"], "--limit", "1"],
        ["dataset", "files", dataset["datasetId"]],
        ["dataset", "query", dataset["datasetId"], "SELECT count(*) n FROM dataset"],
        ["dataset", "urls", dataset["datasetId"], "--limit", "1"],
        ["dataset", "compact", dataset["datasetId"], "--minimum-files", "3"],
        ["schedule", "list"],
        ["schedule", "pause", job["jobId"]],
        ["schedule", "resume", job["jobId"]],
        ["schedule", "run-due"],
    ]
    for command in commands:
        assert main(prefix + command) == 0
        assert capsys.readouterr().out.strip()


def test_workspace_missing_and_unknown_resources(tmp_path, workspace):
    with pytest.raises(FileNotFoundError, match="Workspace.init"):
        Workspace(tmp_path / "missing")
    with pytest.raises(KeyError, match="unknown dataset"):
        workspace.datasets.get("ds_missing")
    with pytest.raises(KeyError, match="unknown job"):
        workspace.jobs.get("job_missing")
    with pytest.raises(KeyError, match="unknown execution"):
        workspace.executions.get("exec_missing")
    with pytest.raises(KeyError, match="has no schedule"):
        workspace.schedules.pause("job_missing")


def test_validate_reports_missing_active_file(workspace):
    dataset = make_dataset(workspace)
    job = make_job(workspace, dataset)
    workspace.jobs.run(job["jobId"], fetcher=FakeFetcher({"https://a.example/": "<h1>A</h1>"}))
    item = workspace.datasets.files(dataset["datasetId"])[0]
    (workspace.path / "datasets" / dataset["datasetId"] / item["path"]).unlink()
    result = workspace.validate()
    assert result["valid"] is False and "missing" in result["errors"][0]
    reader = LocalDatasetReader(workspace.state, workspace.path, dataset)
    with pytest.raises(RuntimeError, match="missing"):
        reader.query("SELECT * FROM dataset")
