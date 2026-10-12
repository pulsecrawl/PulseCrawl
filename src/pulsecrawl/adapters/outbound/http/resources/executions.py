"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations

import time


from pulsecrawl.domain.errors import ExecutionTimeout

from pulsecrawl.adapters.outbound.http.resources.base import _Resource
from pulsecrawl.adapters.outbound.http.constants import *
from pulsecrawl.adapters.outbound.http.resources.urls import _url_params


class _Executions(_Resource):
    def list(self, job_id: str) -> list[dict]:
        return self._c._request("GET", f"/jobs/{job_id}/executions")["executions"]

    def get(self, execution_id: str) -> dict:
        return self._c._request("GET", f"/executions/{execution_id}")

    def cancel(self, execution_id: str) -> dict:
        return self._c._request("POST", f"/executions/{execution_id}:cancel")

    def records(
        self, execution_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> dict:
        """One page of extracted records: {"records": [...], "nextCursor": ...}.

        Available while the crawl runs and for 7 days after (the durable
        form is the dataset's Parquet).
        """
        params: dict = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._c._request(
            "GET", f"/executions/{execution_id}/records", params=params
        )

    def iter_records(self, execution_id: str, *, page_size: int = 100):
        """Iterate every record across pages."""
        cursor: str | None = None
        while True:
            page = self.records(execution_id, cursor=cursor, limit=page_size)
            yield from page["records"]
            cursor = page.get("nextCursor")
            if not cursor:
                return

    def urls(
        self,
        execution_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        newness: str = "all",
        host: str | None = None,
        url_contains: str | None = None,
    ) -> dict:
        """Page URLs observed by one execution, including new/repeat metadata."""
        return self._c._request(
            "GET",
            f"/executions/{execution_id}/urls",
            params=_url_params(cursor, limit, newness, host, url_contains),
        )

    def iter_urls(
        self,
        execution_id: str,
        *,
        page_size: int = 100,
        newness: str = "all",
        host: str | None = None,
        url_contains: str | None = None,
    ):
        """Iterate all URLs observed by one execution."""
        cursor: str | None = None
        while True:
            page = self.urls(
                execution_id,
                cursor=cursor,
                limit=page_size,
                newness=newness,
                host=host,
                url_contains=url_contains,
            )
            yield from page["urls"]
            cursor = page.get("nextCursor")
            if not cursor:
                return

    def wait(
        self,
        execution_id: str,
        *,
        timeout_s: float = 600.0,
        poll_interval_s: float = 5.0,
        sleep=time.sleep,
    ) -> dict:
        """Poll until the execution reaches a terminal state."""
        deadline = time.monotonic() + timeout_s
        while True:
            execution = self.get(execution_id)
            if execution["status"] in TERMINAL_STATUSES:
                return execution
            if time.monotonic() >= deadline:
                raise ExecutionTimeout(
                    f"{execution_id} still {execution['status']} after {timeout_s}s"
                )
            sleep(poll_interval_s)
