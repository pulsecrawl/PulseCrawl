import json

import httpx
import pytest

from pulsecrawl import ExecutionTimeout, PulseCrawl, PulseCrawlError

BASE = "https://api.test/v1"


class Recorder:
    def __init__(self, responses: dict[tuple[str, str], tuple[int, dict | None]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, str(request.url), body))
        status, payload = self.responses.get(key, (404, {"error": {"code": "NOT_FOUND", "message": "?"}}))
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=payload)


def make_client(responses) -> tuple[PulseCrawl, Recorder]:
    recorder = Recorder(responses)
    client = PulseCrawl(
        api_key="pk_live_x", base_url=BASE, transport=httpx.MockTransport(recorder.handler)
    )
    return client, recorder


class TestAuthAndErrors:
    def test_hosted_mode_accepts_key_from_environment(self, monkeypatch):
        monkeypatch.setenv("PULSECRAWL_API_KEY", "pk_live_env")
        with PulseCrawl(
            base_url=BASE,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
        ) as client:
            assert client._http.headers["Authorization"] == "Bearer pk_live_env"

    def test_hosted_mode_requires_a_key(self, monkeypatch):
        monkeypatch.delenv("PULSECRAWL_API_KEY", raising=False)
        with pytest.raises(ValueError, match="requires api_key"):
            PulseCrawl(base_url=BASE)

    def test_hosted_mode_requires_an_explicit_endpoint(self, monkeypatch):
        monkeypatch.delenv("PULSECRAWL_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="requires base_url"):
            PulseCrawl(api_key="pk_live_secret")

    def test_hosted_mode_accepts_endpoint_from_environment(self, monkeypatch):
        monkeypatch.setenv("PULSECRAWL_BASE_URL", BASE)
        with PulseCrawl(
            api_key="pk_live_secret",
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
        ) as client:
            assert str(client._http.base_url) == f"{BASE}/"

    def test_sends_bearer_key(self):
        recorder = Recorder({("GET", "/v1/fields"): (200, {"fields": []})})
        with PulseCrawl(
            api_key="pk_live_secret", base_url=BASE,
            transport=httpx.MockTransport(recorder.handler),
        ) as pc:
            pc.fields.list()

    def test_error_envelope_maps_to_exception(self):
        pc, _ = make_client({("POST", "/v1/datasets"): (422, {"error": {"code": "SCHEMA_MISMATCH", "message": "no"}})})
        with pytest.raises(PulseCrawlError) as excinfo:
            pc.datasets.create("x", schema_id="schema_x")
        assert excinfo.value.code == "SCHEMA_MISMATCH"
        assert excinfo.value.http_status == 422

    def test_non_json_error_still_raises(self):
        def handler(request):
            return httpx.Response(500, text="boom")

        pc = PulseCrawl(api_key="pk", base_url=BASE, transport=httpx.MockTransport(handler))
        with pytest.raises(PulseCrawlError) as excinfo:
            pc.fields.list()
        assert excinfo.value.code == "INTERNAL"

    def test_rejects_plain_http_except_localhost(self):
        with pytest.raises(ValueError, match="require HTTPS"):
            PulseCrawl(api_key="pk", base_url="http://api.example/v1")
        with PulseCrawl(
            api_key="pk",
            base_url="http://localhost:8080/v1",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        ):
            pass

    def test_retries_safe_requests_and_honors_retry_after(self):
        attempts = 0
        sleeps = []

        def handler(request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(503, headers={"Retry-After": "0"}, json={"error": {}})
            return httpx.Response(200, json={"fields": []})

        with PulseCrawl(
            api_key="pk",
            base_url=BASE,
            retry_sleep=sleeps.append,
            transport=httpx.MockTransport(handler),
        ) as client:
            assert client.fields.list() == []
        assert attempts == 2
        assert sleeps == [0]

    def test_retries_idempotent_mutations_and_exposes_request_id(self):
        attempts = 0
        keys = []

        def handler(request):
            nonlocal attempts
            attempts += 1
            keys.append(request.headers["Idempotency-Key"])
            return httpx.Response(
                503,
                headers={"X-Request-Id": "request-123"},
                json={"error": {"code": "INTERNAL", "message": "later"}},
            )

        client = PulseCrawl(
            api_key="pk",
            base_url=BASE,
            transport=httpx.MockTransport(handler),
            retry_sleep=lambda _seconds: None,
        )
        with pytest.raises(PulseCrawlError) as excinfo:
            client.fields.create("x", "string")
        assert attempts == 4
        assert len(set(keys)) == 1
        assert excinfo.value.request_id == "request-123"
        assert excinfo.value.retryable is True

    def test_retries_an_idempotency_request_that_is_still_in_progress(self):
        attempts = 0
        keys = []

        def handler(request):
            nonlocal attempts
            attempts += 1
            keys.append(request.headers["Idempotency-Key"])
            if attempts == 1:
                return httpx.Response(
                    409,
                    headers={"Retry-After": "0"},
                    json={"error": {"code": "IDEMPOTENCY_IN_PROGRESS", "message": "busy"}},
                )
            return httpx.Response(201, json={"fieldId": "fld_1"})

        with PulseCrawl(
            api_key="pk",
            base_url=BASE,
            transport=httpx.MockTransport(handler),
            retry_sleep=lambda _seconds: None,
        ) as client:
            assert client.fields.create("x", "string")["fieldId"] == "fld_1"
        assert attempts == 2
        assert len(set(keys)) == 1

    def test_whoami(self):
        client, _ = make_client({
            ("GET", "/v1/auth/whoami"): (
                200,
                {"kind": "apiKey", "orgId": "org_1", "keyId": "key_1", "scopes": []},
            ),
        })
        assert client.whoami()["orgId"] == "org_1"


class TestResources:
    def test_organizations(self):
        pc, recorder = make_client({
            ("GET", "/v1/organizations/org_1"): (200, {"orgId": "org_1"}),
            ("PATCH", "/v1/organizations/org_1"): (
                200,
                {"orgId": "org_1", "rateLimits": {"requestsPerSecondPerWebsite": 0.5}},
            ),
        })
        assert pc.organizations.get("org_1")["orgId"] == "org_1"
        updated = pc.organizations.update("org_1", requests_per_second_per_website=0.5)
        assert updated["rateLimits"]["requestsPerSecondPerWebsite"] == 0.5
        assert recorder.calls[-1][2] == {
            "rateLimits": {"requestsPerSecondPerWebsite": 0.5}
        }
        with pytest.raises(ValueError):
            pc.organizations.update("org_1", requests_per_second_per_website=0)
        with pytest.raises(ValueError):
            pc.organizations.update("org_1")

    def test_fields(self):
        pc, recorder = make_client({
            ("POST", "/v1/fields"): (201, {"fieldId": "fld_1"}),
            ("GET", "/v1/fields"): (200, {"fields": [{"fieldId": "fld_1"}]}),
            ("GET", "/v1/fields/fld_1"): (200, {"fieldId": "fld_1"}),
        })
        assert pc.fields.create("price", "number", description="d")["fieldId"] == "fld_1"
        assert pc.fields.list(origin="system") == [{"fieldId": "fld_1"}]
        assert pc.fields.get("fld_1")["fieldId"] == "fld_1"
        assert recorder.calls[0][2] == {"name": "price", "type": "number", "description": "d"}
        assert "origin=system" in recorder.calls[1][1]

    def test_schemas(self):
        pc, recorder = make_client({
            ("POST", "/v1/schemas"): (201, {"schemaId": "schema_1"}),
            ("GET", "/v1/schemas"): (200, {"schemas": []}),
            ("GET", "/v1/schemas/schema_1"): (200, {"schemaId": "schema_1"}),
            ("POST", "/v1/schemas/schema_1:clone"): (201, {"schemaId": "schema_2"}),
        })
        assert pc.schemas.create("P", ["fld_1"])["schemaId"] == "schema_1"
        assert pc.schemas.list() == []
        assert pc.schemas.get("schema_1")["schemaId"] == "schema_1"
        assert pc.schemas.clone("schema_1")["schemaId"] == "schema_2"
        assert recorder.calls[0][2] == {"name": "P", "fieldIds": ["fld_1"]}

    def test_templates(self):
        pc, recorder = make_client({
            ("POST", "/v1/templates"): (201, {"templateId": "tmpl_1"}),
            ("GET", "/v1/templates"): (200, {"templates": []}),
            ("GET", "/v1/templates/tmpl_1"): (200, {"templateId": "tmpl_1"}),
            ("POST", "/v1/templates/tmpl_1:clone"): (201, {"templateId": "tmpl_2"}),
            ("DELETE", "/v1/templates/tmpl_1"): (204, None),
        })
        created = pc.templates.create(
            "T", output_schema_id="schema_1", engine="css", mappings={"fld_1": ".p"}
        )
        assert created["templateId"] == "tmpl_1"
        assert pc.templates.list(origin="org") == []
        assert pc.templates.get("tmpl_1")["templateId"] == "tmpl_1"
        assert pc.templates.clone("tmpl_1")["templateId"] == "tmpl_2"
        assert pc.templates.delete("tmpl_1") is None
        assert recorder.calls[0][2]["outputSchemaId"] == "schema_1"

    def test_datasets_jobs_executions(self):
        pc, recorder = make_client({
            ("POST", "/v1/datasets"): (201, {"datasetId": "ds_1"}),
            ("GET", "/v1/datasets"): (200, {"datasets": []}),
            ("GET", "/v1/datasets/ds_1"): (200, {"datasetId": "ds_1"}),
            ("GET", "/v1/datasets/ds_1/files"): (200, {"files": [{"name": "part-0.parquet"}]}),
            ("POST", "/v1/jobs"): (201, {"jobId": "job_1"}),
            ("GET", "/v1/jobs"): (200, {"jobs": []}),
            ("GET", "/v1/jobs/job_1"): (200, {"jobId": "job_1"}),
            ("POST", "/v1/jobs/job_1/executions"): (201, {"executionId": "exec_1", "status": "queued"}),
            ("GET", "/v1/jobs/job_1/executions"): (200, {"executions": []}),
            ("DELETE", "/v1/jobs/job_1"): (204, None),
            ("POST", "/v1/executions/exec_1:cancel"): (200, {"status": "cancelled"}),
        })
        assert pc.datasets.create(
            "d",
            schema_id="schema_1",
            mode="new_urls_only",
            identity_field="fld_url",
        )["datasetId"] == "ds_1"
        assert pc.datasets.list() == []
        assert pc.datasets.get("ds_1")["datasetId"] == "ds_1"
        assert pc.datasets.files("ds_1")[0]["name"] == "part-0.parquet"
        job = pc.jobs.create(
            "j", seeds=["https://x/"], template_id="tmpl_1", dataset_id="ds_1",
            scope={"maxPages": 5}, politeness={"requestsPerSecond": 2},
        )
        assert job["jobId"] == "job_1"
        assert pc.jobs.list() == []
        assert pc.jobs.get("job_1")["jobId"] == "job_1"
        assert pc.jobs.run("job_1")["executionId"] == "exec_1"
        assert pc.executions.list("job_1") == []
        assert pc.executions.cancel("exec_1")["status"] == "cancelled"
        assert pc.jobs.archive("job_1") is None
        job_body = next(b for (_m, _u, b) in recorder.calls if b and b.get("name") == "j")
        assert job_body["scope"] == {"maxUrlsPerExecution": 5}
        dataset_body = next(b for (_m, u, b) in recorder.calls if u.endswith("/datasets") and b)
        assert dataset_body == {
            "name": "d",
            "schemaId": "schema_1",
            "mode": "new_urls_only",
            "identityField": "fld_url",
        }

    def test_dataset_policy_validation(self):
        pc, _ = make_client({})
        with pytest.raises(ValueError, match="mode"):
            pc.datasets.create("d", schema_id="schema_1", mode="replace")
        with pytest.raises(ValueError, match="identity_field"):
            pc.datasets.create("d", schema_id="schema_1", identity_field="")

    def test_downloads_dataset_files_atomically_without_leaking_api_key(self, tmp_path):
        content = b"PAR1test"

        def handler(request):
            if request.url.host == "api.test":
                return httpx.Response(200, json={"files": [{
                    "name": "data/ingest_date=2026-01-01/part.parquet",
                    "url": "https://blob.example/file?signed=yes",
                    "sizeBytes": len(content),
                    "expiresAt": "2027-01-01T00:00:00Z",
                }]})
            assert request.url.host == "blob.example"
            assert "Authorization" not in request.headers
            return httpx.Response(200, content=content)

        with PulseCrawl(
            api_key="pk_secret",
            base_url=BASE,
            transport=httpx.MockTransport(handler),
        ) as client:
            paths = client.datasets.download_files("ds_1", tmp_path)
            assert paths[0].read_bytes() == content
            with pytest.raises(FileExistsError):
                client.datasets.download_files("ds_1", tmp_path)

    def test_rejects_unsafe_or_oversized_dataset_downloads(self, tmp_path):
        responses = iter([
            {"files": [{
                "name": "../escape.parquet",
                "url": "https://blob.example/file",
                "sizeBytes": 1,
                "expiresAt": "2027-01-01T00:00:00Z",
            }]},
            {"files": [{
                "name": "part.parquet",
                "url": "https://blob.example/file",
                "sizeBytes": 100,
                "expiresAt": "2027-01-01T00:00:00Z",
            }]},
        ])

        def handler(_request):
            return httpx.Response(200, json=next(responses))

        with PulseCrawl(api_key="pk", base_url=BASE, transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="unsafe"):
                client.datasets.download_files("ds_1", tmp_path)
            with pytest.raises(ValueError, match="max_total_bytes"):
                client.datasets.download_files("ds_1", tmp_path, max_total_bytes=10)

    def test_dataset_download_rejects_symlink_parent_escape(self, tmp_path):
        destination = tmp_path / "download"
        destination.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        try:
            (destination / "linked").symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("directory symlinks are unavailable on this platform")

        def handler(request):
            assert request.url.host == "api.test"
            return httpx.Response(200, json={"files": [{
                "name": "linked/part.parquet",
                "url": "https://blob.example/file",
                "sizeBytes": 1,
                "expiresAt": "2027-01-01T00:00:00Z",
            }]})

        with PulseCrawl(
            api_key="pk",
            base_url=BASE,
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(ValueError, match="escapes destination"):
                client.datasets.download_files("ds_1", destination)
        assert list(outside.iterdir()) == []

    def test_scope_aliases_and_conflicts(self):
        pc, recorder = make_client({("POST", "/v1/jobs"): (201, {"jobId": "job_1"})})
        pc.jobs.create(
            "j", seeds=["https://x/"], template_id="tmpl_1", dataset_id="ds_1",
            scope={"max_pages": 1000, "max_urls_total": 1_000_000, "max_depth": 6},
        )
        body = recorder.calls[-1][2]
        assert body["scope"] == {
            "maxUrlsPerExecution": 1000, "maxUrlsTotal": 1_000_000, "maxDepth": 6,
        }
        with pytest.raises(ValueError, match="must match"):
            pc.jobs.create(
                "bad", seeds=["https://x/"], template_id="tmpl_1", dataset_id="ds_1",
                scope={"maxPages": 1, "maxUrlsPerExecution": 2},
            )

    def test_scoped_template_stack(self):
        pc, recorder = make_client({
            ("POST", "/v1/jobs"): (201, {"jobId": "job_scoped"}),
        })
        job = pc.jobs.create(
            "multi-domain",
            seeds=["https://one.example/", "https://two.example/"],
            template_stack=[
                {
                    "template_id": "tmpl_one_path",
                    "hosts": ["one.example"],
                    "url_patterns": ["https://one.example/news/*"],
                },
                {"template_id": "tmpl_two", "scope": {"hosts": ["two.example"]}},
                {"template_id": "tmpl_generic"},
            ],
            dataset_id="ds_1",
        )
        assert job["jobId"] == "job_scoped"
        body = recorder.calls[0][2]
        assert body["templateStack"] == [
            {
                "templateId": "tmpl_one_path",
                "scope": {
                    "hosts": ["one.example"],
                    "urlPatterns": ["https://one.example/news/*"],
                },
            },
            {"templateId": "tmpl_two", "scope": {"hosts": ["two.example"]}},
            {"templateId": "tmpl_generic"},
        ]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {},
            {"template_ids": []},
            {"template_stack": []},
            {"template_id": "tmpl_1", "template_ids": ["tmpl_1"]},
            {"template_stack": [{}]},
        ],
    )
    def test_job_rejects_invalid_template_inputs(self, kwargs):
        pc, _ = make_client({})
        with pytest.raises(ValueError):
            pc.jobs.create("bad", seeds=["https://x/"], dataset_id="ds_1", **kwargs)


class TestWait:
    def test_wait_polls_until_terminal(self):
        statuses = iter(["queued", "running", "succeeded"])

        def handler(request):
            return httpx.Response(200, json={"executionId": "exec_1", "status": next(statuses)})

        pc = PulseCrawl(api_key="pk", base_url=BASE, transport=httpx.MockTransport(handler))
        sleeps: list[float] = []
        final = pc.executions.wait("exec_1", poll_interval_s=1, sleep=sleeps.append)
        assert final["status"] == "succeeded"
        assert sleeps == [1, 1]

    def test_wait_times_out(self):
        def handler(request):
            return httpx.Response(200, json={"executionId": "exec_1", "status": "running"})

        pc = PulseCrawl(api_key="pk", base_url=BASE, transport=httpx.MockTransport(handler))
        with pytest.raises(ExecutionTimeout):
            pc.executions.wait("exec_1", timeout_s=0, sleep=lambda _s: None)


class TestSchedules:
    def test_schedule_lifecycle(self):
        schedule = {
            "cron": "0 9 * * *",
            "timezone": "America/Denver",
            "status": "active",
            "nextRunAt": "2026-08-22T15:00:00Z",
        }
        pc, recorder = make_client({
            ("PUT", "/v1/jobs/job_1/schedule"): (200, schedule),
            ("GET", "/v1/jobs/job_1/schedule"): (200, schedule),
            ("POST", "/v1/jobs/job_1/schedule:pause"): (200, {**schedule, "status": "paused"}),
            ("POST", "/v1/jobs/job_1/schedule:resume"): (200, schedule),
            ("DELETE", "/v1/jobs/job_1/schedule"): (204, None),
        })
        assert pc.schedules.set("job_1", "0 9 * * *", timezone="America/Denver") == schedule
        assert recorder.calls[0][2] == {"cron": "0 9 * * *", "timezone": "America/Denver"}
        assert pc.schedules.get("job_1") == schedule
        assert pc.schedules.pause("job_1")["status"] == "paused"
        assert pc.schedules.resume("job_1")["status"] == "active"
        assert pc.schedules.delete("job_1") is None


class TestRecords:
    def test_pages_and_iterates(self):
        pages = {
            None: {"records": [{"t": 1}, {"t": 2}], "nextCursor": "0:2"},
            "0:2": {"records": [{"t": 3}]},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            cursor = request.url.params.get("cursor")
            return httpx.Response(200, json=pages[cursor])

        pc = PulseCrawl(api_key="pk", base_url=BASE, transport=httpx.MockTransport(handler))
        first = pc.executions.records("exec_1", limit=2)
        assert [r["t"] for r in first["records"]] == [1, 2]
        assert [r["t"] for r in pc.executions.iter_records("exec_1", page_size=2)] == [1, 2, 3]


class TestUrls:
    @pytest.mark.parametrize("resource", ["datasets", "executions"])
    def test_pages_and_iterates_with_filters(self, resource):
        pages = {
            None: {"urls": [{"urlIdentity": "a"}], "nextCursor": "next"},
            "next": {"urls": [{"urlIdentity": "b"}]},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["newness"] == "repeat"
            assert request.url.params["host"] == "example.com"
            assert request.url.params["urlContains"] == "/news/"
            return httpx.Response(200, json=pages[request.url.params.get("cursor")])

        pc = PulseCrawl(api_key="pk", base_url=BASE, transport=httpx.MockTransport(handler))
        api = getattr(pc, resource)
        rows = list(api.iter_urls(
            "ds_1" if resource == "datasets" else "exec_1",
            page_size=1,
            newness="repeat",
            host="example.com",
            url_contains="/news/",
        ))
        assert [row["urlIdentity"] for row in rows] == ["a", "b"]

    def test_validates_page_options(self):
        pc, _ = make_client({})
        with pytest.raises(ValueError, match="limit"):
            pc.datasets.urls("ds_1", limit=0)
        with pytest.raises(ValueError, match="newness"):
            pc.executions.urls("exec_1", newness="sometimes")


class TestQuery:
    def test_posts_sql(self):
        pc, recorder = make_client({
            ("POST", "/v1/datasets/ds_1/query"): (200, {"columns": ["t"], "rows": [["A"]], "truncated": False}),
        })
        result = pc.datasets.query("ds_1", "SELECT t FROM dataset")
        assert result["rows"] == [["A"]]
        assert recorder.calls[0][2] == {"sql": "SELECT t FROM dataset"}
