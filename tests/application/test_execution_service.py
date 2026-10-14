"""Lifecycle orchestration tested with ports, without SQL, HTML or Parquet."""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest

from pulsecrawl.application.executions.service import ExecutionService
from pulsecrawl.domain.crawling.model import Completed, CrawlStats


def fixture(*, fail_run=False, fail_open=False):
    events = []
    row = {
        "executionId": "e",
        "jobId": "j",
        "datasetId": "d",
        "status": "queued",
        "startedAt": None,
    }

    class Repository:
        def get(self, execution_id):
            return dict(row)

        def start(self, execution_id, started):
            row["status"] = "running"

        def cancellation_requested(self, execution_id):
            return False

        def finish(self, execution_id, **options):
            events.append("terminal:" + options["status"])
            row.update(status=options["status"], stats=options["stats"])

        def prepare(self, job_id, **options):
            return dict(row)

        def list(self, job_id):
            return [dict(row)]

        def abandoned(self, status):
            return ["e"] if status == "queued" else []

    class Lease:
        @contextmanager
        def hold(self, *args):
            events.append("lease_claimed")
            try:
                yield
            finally:
                events.append("lease_released")

    class Engine:
        async def seed(self, intent):
            events.append("seed")

        async def run(self, intent):
            if fail_run:
                raise RuntimeError("fetch failed")
            return Completed(CrawlStats(pages_fetched=1))

    def finalize(**options):
        events.append("output_published")
        return {"rows": 1}

    class Runtime:
        @asynccontextmanager
        async def open(self, *args, **kwargs):
            if fail_open:
                raise RuntimeError("cannot open runtime")
            try:
                yield SimpleNamespace(
                    intent=object(),
                    writer=SimpleNamespace(finalize=finalize),
                    engine=Engine(),
                    admitted=0,
                    pending_urls=SimpleNamespace(pending_count=lambda: 0),
                )
            finally:
                events.append("resources_closed")

    tasks = SimpleNamespace(
        register=lambda *a: events.append("task_registered"),
        unregister=lambda *a: events.append("task_unregistered"),
    )
    snapshots = SimpleNamespace(write=lambda *a: events.append("snapshot"))
    service = ExecutionService(
        repository=Repository(),
        leases=Lease(),
        runtime=Runtime(),
        datasets=object(),
        readers=object(),
        snapshots=snapshots,
        now=lambda: "now",
        id_factory=lambda _: "owner",
        tasks=tasks,
    )
    return service, row, events


async def test_output_publication_precedes_terminal_settlement_and_cleanup():
    service, row, events = fixture()
    result = await service.execute("e")
    assert result["status"] == "succeeded"
    assert events.index("output_published") < events.index("terminal:succeeded")
    assert events.index("resources_closed") < events.index("lease_released")
    assert events[-2:] == ["task_unregistered", "lease_released"]


async def test_failed_crawl_settles_failure_and_releases_resources():
    service, row, events = fixture(fail_run=True)
    with pytest.raises(RuntimeError, match="fetch failed"):
        await service.execute("e")
    assert row["status"] == "failed"
    assert "output_published" not in events
    assert events[-2:] == ["task_unregistered", "lease_released"]


async def test_partial_runtime_setup_still_releases_runner_and_task():
    service, row, events = fixture(fail_open=True)
    with pytest.raises(RuntimeError, match="cannot open runtime"):
        await service.execute("e")
    assert events[-2:] == ["task_unregistered", "lease_released"]


def test_prepare_and_queries_use_repository_and_snapshot_ports():
    service, _, events = fixture()
    assert service.prepare("j")["executionId"] == "e"
    assert events == ["snapshot"]
    assert service.list()[0]["executionId"] == "e"
    assert service.recoverable() == ["e"]
