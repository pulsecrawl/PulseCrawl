from datetime import datetime, timezone

import pytest
from pulsecrawl import RepresentativePage, Workspace, inspect_page, validate_template_stack
from pulsecrawl.core.model import FetchResult


FIELDS = [
    {"fieldId": "fld_title", "name": "title", "type": "string"},
    {"fieldId": "fld_url", "name": "canonical", "type": "url"},
]


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def fetch(self, url, *, user_agent):
        self.calls.append(url)
        body = self.pages.get(url)
        return FetchResult(
            url=url,
            final_url=url,
            status=200 if body else 404,
            headers={"content-type": "text/html"},
            body=body,
            error=None if body else "HTTP 404",
            fetched_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
            body_bytes=len(body.encode()) if body else 0,
        )


@pytest.fixture
def workspace(tmp_path):
    value = Workspace.init(tmp_path / "authoring")
    for field in FIELDS:
        value.fields.create(field["name"], field["type"], field_id=field["fieldId"])
    value.schemas.create("article", [item["fieldId"] for item in FIELDS], schema_id="schema_article")
    dataset = value.datasets.create("authoring", schema_id="schema_article")
    job = value.jobs.create(
        "authoring",
        seeds=["https://news.example/"],
        dataset_id=dataset["datasetId"],
        templates=[{
            "template_id": "bootstrap-authoring",
            "engine": "meta",
            "mappings": {"fld_title": "og:title"},
        }],
        politeness={"respectRobotsTxt": False, "requestsPerSecond": 1000},
    )
    value.test_authoring_job_id = job["jobId"]
    yield value
    value.close()


def page(url, html, *, role="positive", truncated=False, expected=()):
    return RepresentativePage(
        url=url,
        body=html,
        role=role,
        body_truncated=truncated,
        body_bytes=len(html.encode()),
        expected_records=tuple(expected),
    )


def test_inspection_reports_machine_readable_markup_and_untrusted_boundary():
    report = inspect_page(page(
        "https://news.example/story/1",
        """
        <html><head><title>Story</title><meta property="og:title" content="Story">
        <script type="application/ld+json">
        {"@type":"NewsArticle","headline":"Story","author":{"name":"A"}}
        </script></head><body><main><h1 id="headline">Story</h1>
        <ul><li class="card">A</li><li class="card">B</li></ul></main></body></html>
        """,
        truncated=True,
    ), include_content_samples=True).to_dict()
    assert report["final_url"] == "https://news.example/story/1"
    assert report["meta_fields"]["og:title"] == "Story"
    assert report["jsonld_entities"][0]["types"] == ["NewsArticle"]
    assert "author.name" in report["jsonld_entities"][0]["paths"]
    assert any(item["selector"] == "#headline" for item in report["selector_candidates"])
    assert any(item["selector"] == "li" for item in report["repeated_structures"])
    assert report["body_truncated"] is True
    assert report["security"]["contentIsUntrusted"] is True
    redacted = inspect_page({
        "url": "https://news.example/", "body": '<meta name="secret" content="value">'
    }).to_dict()
    assert redacted["meta_fields"]["secret"] == "[present]"
    with pytest.raises(ValueError, match="byte limit"):
        inspect_page({"url": "https://news.example/", "body": "1234"}, max_body_bytes=3)


def test_validation_reports_fallback_provenance_ambiguity_and_contamination():
    templates = [
        {
            "templateId": "specific",
            "engine": "css",
            "mappings": {"fld_title": "h1", "fld_url": "link[rel=canonical]@href"},
            "scope": {"hosts": ["news.example"], "urlPatterns": ["/story/*"]},
        },
        {
            "templateId": "enrichment",
            "engine": "meta",
            "mappings": {"fld_url": "og:url"},
            "scope": {"hosts": ["news.example"]},
        },
    ]
    pages = [
        page(
            "https://news.example/story/1",
            '<h1>One</h1><meta property="og:url" content="https://news.example/story/1">',
        ),
        page("https://news.example/about", "<p>About</p>", role="negative"),
        page("https://foreign.example/story/2", "<h1>Foreign</h1>", role="negative"),
    ]
    report = validate_template_stack(
        templates,
        pages,
        system_templates=[{
            "templateId": "system-meta",
            "engine": "meta",
            "mappings": {"fld_title": "og:title"},
        }],
        required_field_ids=["fld_title", "fld_url"],
    )
    assert report["passed"] is True
    first = report["pages"][0]
    assert first["matchTier"] == "scoped"
    assert first["fieldProvenance"][0] == {
        "fld_title": "specific",
        "fld_url": "enrichment",
    }
    assert report["summary"]["scopeContainmentSignals"] == 1
    assert report["crossScopeContaminationSignals"][0]["url"] == "https://foreign.example/story/2"
    assert report["summary"]["unmatchedPages"] == 2

    failed = validate_template_stack(
        [{"templateId": "generic", "engine": "css", "mappings": {"fld_title": "h1"}}],
        [page("https://news.example/about", "<h1>About</h1>", role="negative")],
    )
    assert failed["passed"] is False
    assert failed["negativeMatchUrls"] == ["https://news.example/about"]


def test_validation_reports_system_fallback_and_multi_entity_ambiguity():
    html = """
    <script type="application/ld+json">
    [{"@type":"NewsArticle","headline":"One"},
     {"@type":"NewsArticle","headline":"Two"}]
    </script>
    """
    report = validate_template_stack(
        [{
            "templateId": "different-host",
            "engine": "css",
            "mappings": {"fld_title": "h1"},
            "scope": {"hosts": ["other.example"]},
        }],
        [page("https://news.example/story/1", html)],
        system_templates=[{
            "templateId": "system-jsonld",
            "engine": "jsonld",
            "mappings": {"fld_title": "Article.headline"},
        }],
        required_field_ids=["fld_title"],
    )
    assert report["passed"] is False
    assert report["summary"]["systemFallbackMatches"] == 1
    result = report["pages"][0]
    assert result["matchTier"] == "system_fallback"
    assert result["matchedTemplateIds"] == ["system-jsonld"]
    assert result["entityCount"] == 2 and result["multiEntity"] is True
    assert result["ambiguous"] is False
    assert result["fieldProvenance"] == [
        {"fld_title": "system-jsonld"}, {"fld_title": "system-jsonld"}
    ]


def test_draft_requires_validation_and_explicit_approval_before_promotion(workspace):
    draft = workspace.authoring.create_draft(
        "News article",
        output_schema_id="schema_article",
        source_job_id=workspace.test_authoring_job_id,
        templates=[{
            "engine": "css",
            "mappings": {
                "fld_title": "h1",
                "fld_url": "link[rel=canonical]@href",
            },
            "hosts": ["news.example"],
            "url_patterns": ["/story/*"],
        }],
    )
    assert draft.version == 1 and draft.status == "draft"
    with pytest.raises(ValueError, match="approved"):
        workspace.authoring.promote(draft.draft_id)
    report = workspace.authoring.validate(
        draft.draft_id,
        [page(
            "https://news.example/story/1",
            '<h1>One</h1><link rel="canonical" href="https://news.example/story/1">',
        ), page("https://news.example/about", "<p>About</p>", role="negative")],
    )
    assert report["passed"] is True
    with pytest.raises(ValueError, match="latest validation"):
        workspace.authoring.approve(
            draft.draft_id, validation_id="wrong", approved_by="reviewer@example.test"
        )
    approved = workspace.authoring.approve(
        draft.draft_id,
        validation_id=report["validationId"],
        approved_by="reviewer@example.test",
    )
    assert approved.status == "approved"
    promoted = workspace.authoring.promote(draft.draft_id)
    assert promoted["draft"].status == "promoted"
    assert promoted["draft"].approved_by == "reviewer@example.test"
    assert promoted["templates"][0]["createdAt"].endswith("+00:00")
    assert promoted["templateStack"][0]["scope"] == {
        "hosts": ["news.example"], "urlPatterns": ["/story/*"]
    }
    assert len(workspace.jobs.list()) == 1
    assert workspace.validate()["valid"] is True
    assert workspace.authoring.promote(draft.draft_id)["templateStack"] == promoted["templateStack"]
    with pytest.raises(ValueError, match="immutable"):
        workspace.authoring.validate(
            draft.draft_id,
            [
                page("https://news.example/story/1", "<h1>One</h1>"),
                page("https://news.example/about", "<p>About</p>", role="negative"),
            ],
        )
    with pytest.raises(ValueError, match="validated"):
        workspace.authoring.approve(
            draft.draft_id,
            validation_id=report["validationId"],
            approved_by="reviewer@example.test",
        )


def test_governed_sampling_uses_execution_budget_and_retained_snapshots(workspace):
    dataset = workspace.datasets.create("articles", schema_id="schema_article")
    job = workspace.jobs.create(
        "sample source",
        seeds=["https://news.example/"],
        dataset_id=dataset["datasetId"],
        templates=[{
            "template_id": "sample-template",
            "engine": "css",
            "mappings": {"fld_title": "h1", "fld_url": "link[rel=canonical]@href"},
        }],
        scope={"maxDepth": 5, "maxUrlsPerExecution": 50, "maxUrlsTotal": 100},
        politeness={"respectRobotsTxt": False, "requestsPerSecond": 1000},
    )
    fetcher = FakeFetcher({
        "https://news.example/": '<h1>Home</h1><link rel="canonical" href="https://news.example/"><a href="/one">1</a><a href="/two">2</a>',
        "https://news.example/one": '<h1>One</h1><link rel="canonical" href="https://news.example/one">',
        "https://news.example/two": '<h1>Two</h1><link rel="canonical" href="https://news.example/two">',
    })
    sampled = workspace.authoring.sample(
        job["jobId"], max_pages=2, max_depth=1, _fetcher=fetcher
    )
    assert sampled["execution"]["intent"]["scope"]["maxUrlsPerExecution"] == 2
    assert sampled["execution"]["intent"]["scope"]["maxDepth"] == 1
    assert sampled["execution"]["intent"]["storeRawPages"] is True
    assert sampled["execution"]["intent"]["publishRecords"] is False
    assert len(fetcher.calls) == len(sampled["pages"]) == 2
    assert workspace.datasets.files(dataset["datasetId"]) == []
    assert all(item["finalUrl"].startswith("https://news.example/") for item in sampled["pages"])
    anchored = workspace.authoring.create_draft(
        "anchored",
        output_schema_id="schema_article",
        source_job_id=job["jobId"],
        templates=[{"engine": "css", "mappings": {"fld_title": "h1"}}],
    )
    assert anchored.templates[0]["scope"]["hosts"] == ["news.example"]
    with pytest.raises(ValueError, match="source job hosts"):
        workspace.authoring.create_draft(
            "wildcard expansion",
            output_schema_id="schema_article",
            source_job_id=job["jobId"],
            templates=[{
                "engine": "css",
                "hosts": ["*.news.example"],
                "mappings": {"fld_title": "h1"},
            }],
        )
    with pytest.raises(ValueError, match="source job hosts"):
        workspace.authoring.create_draft(
            "expanded",
            output_schema_id="schema_article",
            source_job_id=job["jobId"],
            templates=[{
                "engine": "css",
                "hosts": ["foreign.example"],
                "mappings": {"fld_title": "h1"},
            }],
        )
    with pytest.raises(ValueError, match="positive"):
        workspace.authoring.sample(job["jobId"], max_pages=0, _fetcher=fetcher)


def test_drift_and_repair_create_new_draft_without_mutating_catalog(workspace):
    template = workspace.templates.create(
        "active article",
        output_schema_id="schema_article",
        engine="css",
        mappings={"fld_title": "h1", "fld_url": "link[rel=canonical]@href"},
        template_id="tmpl_active",
    )
    baseline = [page(
        "https://news.example/story/1",
        '<h1>One</h1><link rel="canonical" href="https://news.example/story/1">',
    )]
    current = [page("https://news.example/story/1", '<div class="headline">One</div>')]
    drift = workspace.authoring.diagnose_drift(template["templateId"], baseline, current)
    assert drift["matchRateDelta"] == -1
    assert drift["regressionUrls"] == ["https://news.example/story/1"]
    assert drift["fieldCoverage"]["fld_title"] == {
        "baseline": 1.0, "current": 0.0, "delta": -1.0
    }
    repair = workspace.authoring.repair_draft(
        template["templateId"], source_job_id=workspace.test_authoring_job_id
    )
    assert repair.status == "draft"
    assert repair.based_on_template_id == template["templateId"]
    assert workspace.templates.get(template["templateId"])["mappings"]["fld_title"] == ["h1"]


def test_draft_rejects_unknown_fields_and_failed_validation_cannot_be_approved(workspace):
    with pytest.raises(ValueError, match="schema fields"):
        workspace.authoring.create_draft(
            "bad",
            output_schema_id="schema_article",
            source_job_id=workspace.test_authoring_job_id,
            templates=[{"engine": "css", "mappings": {"fld_unknown": "h1"}}],
        )
    with pytest.raises(ValueError, match="non-empty strings"):
        workspace.authoring.create_draft(
            "bad expression",
            output_schema_id="schema_article",
            source_job_id=workspace.test_authoring_job_id,
            templates=[{"engine": "css", "mappings": {"fld_title": [""]}}],
        )
    with pytest.raises(ValueError, match="sequences"):
        workspace.authoring.create_draft(
            "bad hosts",
            output_schema_id="schema_article",
            source_job_id=workspace.test_authoring_job_id,
            templates=[{
                "engine": "css", "hosts": "news.example",
                "mappings": {"fld_title": "h1"},
            }],
        )
    with pytest.raises(ValueError, match="unique"):
        workspace.authoring.create_draft(
            "duplicates",
            output_schema_id="schema_article",
            source_job_id=workspace.test_authoring_job_id,
            templates=[
                {"templateId": "same", "engine": "css", "mappings": {"fld_title": "h1"}},
                {"templateId": "same", "engine": "meta", "mappings": {"fld_title": "og:title"}},
            ],
        )
    draft = workspace.authoring.create_draft(
        "miss",
        output_schema_id="schema_article",
        source_job_id=workspace.test_authoring_job_id,
        templates=[{"engine": "css", "mappings": {"fld_title": "h1", "fld_url": "a@href"}}],
    )
    report = workspace.authoring.validate(
        draft.draft_id,
        [page("https://news.example/story", "<p>none</p>")],
    )
    assert report["passed"] is False
    with pytest.raises(ValueError, match="validated"):
        workspace.authoring.approve(
            draft.draft_id,
            validation_id=report["validationId"],
            approved_by="reviewer@example.test",
        )


def test_workspace_validation_rejects_truncated_or_uncoercible_evidence(workspace):
    draft = workspace.authoring.create_draft(
        "typed",
        output_schema_id="schema_article",
        source_job_id=workspace.test_authoring_job_id,
        templates=[{
            "engine": "css",
            "mappings": {"fld_title": "h1", "fld_url": "a@href"},
        }],
    )
    report = workspace.authoring.validate(
        draft.draft_id,
        [
            page("https://news.example/story", '<h1>Story</h1><a href="javascript:void(0)">x</a>', truncated=True),
            page("https://news.example/about", "<p>About</p>", role="negative"),
        ],
    )
    assert report["passed"] is False
    assert report["summary"]["truncatedPages"] == 1
    assert report["coercionFailures"] == [
        {"url": "https://news.example/story", "fieldId": "fld_url"}
    ]


def test_workspace_validation_resolves_relative_url_fields(workspace):
    draft = workspace.authoring.create_draft(
        "relative canonical",
        output_schema_id="schema_article",
        source_job_id=workspace.test_authoring_job_id,
        templates=[{
            "engine": "css",
            "mappings": {"fld_title": "h1", "fld_url": "link[rel=canonical]@href"},
        }],
    )
    report = workspace.authoring.validate(
        draft.draft_id,
        [
            page(
                "https://news.example/articles/story",
                '<h1>Story</h1><link rel="canonical" href="../canonical">',
            ),
            page("https://news.example/about", "<p>About</p>", role="negative"),
        ],
    )
    assert report["passed"] is True
    assert report["pages"][0]["coercedRecords"] == [{
        "fld_title": "Story",
        "fld_url": "https://news.example/canonical",
    }]


def test_expected_record_oracle_rejects_a_semantically_wrong_selector():
    report = validate_template_stack(
        [{"templateId": "wrong", "engine": "css", "mappings": {"fld_title": "h2"}}],
        [
            page(
                "https://news.example/story",
                "<h1>Correct title</h1><h2>Navigation title</h2>",
                expected=({"fld_title": "Correct title"},),
            ),
            page("https://news.example/about", "<p>About</p>", role="negative"),
        ],
        required_field_ids=["fld_title"],
    )
    assert report["passed"] is False
    assert report["summary"]["valueOraclePages"] == 1
    assert report["oracleMismatches"] == [{
        "url": "https://news.example/story",
        "expectedRecord": {"fld_title": "Correct title"},
    }]


def test_required_fields_are_checked_per_entity_and_oracle_rejects_extra_entities():
    split_entities = """
    <script type="application/ld+json">
    [{"@type":"NewsArticle","headline":"One"},
     {"@type":"NewsArticle","url":"https://news.example/story"}]
    </script>
    """
    report = validate_template_stack(
        [{
            "templateId": "article",
            "engine": "jsonld",
            "mappings": {
                "fld_title": "Article.headline",
                "fld_url": "Article.url",
            },
        }],
        [
            page("https://news.example/story", split_entities),
            page("https://news.example/about", "<p>About</p>", role="negative"),
        ],
        required_field_ids=["fld_title", "fld_url"],
    )
    assert report["passed"] is False
    assert report["missingRequiredFields"]["https://news.example/story"] == [
        "fld_title", "fld_url"
    ]

    extra = validate_template_stack(
        [{
            "templateId": "article",
            "engine": "jsonld",
            "mappings": {"fld_title": "Article.headline"},
        }],
        [
            page(
                "https://news.example/story",
                '<script type="application/ld+json">'
                '[{"@type":"NewsArticle","headline":"One"},'
                '{"@type":"NewsArticle","headline":"Extra"}]</script>',
                expected=({"fld_title": "One"},),
            ),
            page("https://news.example/about", "<p>About</p>", role="negative"),
        ],
        required_field_ids=["fld_title"],
    )
    assert extra["passed"] is False
    assert extra["oracleUnexpectedRecords"] == [{
        "url": "https://news.example/story",
        "record": {"fld_title": "Extra"},
    }]


def test_positive_evidence_requires_successful_http_status():
    with pytest.raises(ValueError, match="successful HTTP"):
        validate_template_stack(
            [{"engine": "css", "mappings": {"fld_title": "h1"}}],
            [
                RepresentativePage(
                    url="https://news.example/missing",
                    body="<h1>Error page</h1>",
                    status=404,
                ),
                page("https://news.example/about", "<p>About</p>", role="negative"),
            ],
        )


def test_repeated_url_snapshots_keep_their_own_value_oracles():
    report = validate_template_stack(
        [{"templateId": "title", "engine": "css", "mappings": {"fld_title": "h1"}}],
        [
            page(
                "https://news.example/story",
                "<h1>Version one</h1>",
                expected=({"fld_title": "Version one"},),
            ),
            page(
                "https://news.example/story",
                "<h1>Version two</h1>",
                expected=({"fld_title": "Version two"},),
            ),
            page("https://news.example/about", "<p>About</p>", role="negative"),
        ],
        required_field_ids=["fld_title"],
    )
    assert report["passed"] is True
    assert report["summary"]["valueOraclePages"] == 2
