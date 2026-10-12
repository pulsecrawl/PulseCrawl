"""Execution identity and budget reservation are one atomic operation."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from threading import Barrier

import pytest

from pulsecrawl import Workspace


@pytest.mark.parametrize("separate_connections", [False, True])
@pytest.mark.parametrize("max_urls_total", [10, 100])
def test_concurrent_prepare_returns_one_execution_and_reserves_budget_once(
    tmp_path, monkeypatch, separate_connections, max_urls_total
):
    with Workspace.init(tmp_path / "workspace") as first:
        dataset = first.datasets.create(
            "pages", fields=[{"fieldId": "title", "name": "title", "type": "string"}]
        )
        job = first.jobs.create(
            "pages",
            seeds=["https://example.com/"],
            dataset_id=dataset["datasetId"],
            templates=[{"engine": "css", "mappings": {"title": "h1"}}],
            scope={"maxUrlsPerExecution": 10, "maxUrlsTotal": max_urls_total},
        )
        with Workspace(first.path) as second:
            callers = [first, second if separate_connections else first]
            barrier = Barrier(2)

            def synchronize_transactions(original):
                @contextmanager
                def transaction(**options):
                    # Pause before BEGIN IMMEDIATE, never while holding a
                    # database lock. The old implementation has already read
                    # "not found" here, making its duplicate-insert race
                    # deterministic rather than dependent on thread timing.
                    barrier.wait(timeout=10)
                    with original(**options) as db:
                        yield db

                return transaction

            execution_id = "exec_concurrent_prepare"
            with monkeypatch.context() as patch:
                for state in {caller.state for caller in callers}:
                    patch.setattr(
                        state,
                        "transaction",
                        synchronize_transactions(state.transaction),
                    )
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(
                            caller.jobs.prepare, job["jobId"], execution_id=execution_id
                        )
                        for caller in callers
                    ]
                    results = [future.result(timeout=20) for future in futures]

            assert results[0] == results[1]
            assert results[0]["executionId"] == execution_id
            assert results[0]["reservedUrls"] == 10
            assert first.executions.list() == [results[0]]
            budget = first.state.execute(
                "SELECT urls_used,urls_reserved FROM jobs WHERE job_id=?",
                (job["jobId"],),
            ).fetchone()
            assert tuple(budget) == (0, 10)
            snapshot = first.path / "executions" / execution_id / "execution.json"
            assert json.loads(snapshot.read_text()) == results[0]
            # Retries return the frozen original intent, even when the first
            # reservation consumed all remaining capacity.
            assert (
                second.jobs.prepare(
                    job["jobId"], execution_id=execution_id, max_urls_per_execution=1
                )
                == results[0]
            )
