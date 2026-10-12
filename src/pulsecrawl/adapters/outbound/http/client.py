"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping
from uuid import uuid4

import httpx

from pulsecrawl.domain.errors import PulseCrawlError

from pulsecrawl.adapters.outbound.http.constants import *
from pulsecrawl.adapters.outbound.http.artifacts import ArtifactDownloader
from pulsecrawl.adapters.outbound.http.resources.organizations import _Organizations
from pulsecrawl.adapters.outbound.http.resources.fields import _Fields
from pulsecrawl.adapters.outbound.http.resources.schemas import _Schemas
from pulsecrawl.adapters.outbound.http.resources.templates import _Templates
from pulsecrawl.adapters.outbound.http.resources.datasets import _Datasets
from pulsecrawl.adapters.outbound.http.resources.jobs import _Jobs
from pulsecrawl.adapters.outbound.http.resources.executions import _Executions
from pulsecrawl.adapters.outbound.http.resources.schedules import _Schedules


class PulseCrawl:
    """Entry point for hosted mode.

    >>> pc = PulseCrawl(api_key="pk_live_...", base_url="https://api.example/v1")
    >>> pc.fields.list(origin="system")
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = DEFAULT_BASE_URL,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
        retry_sleep=time.sleep,
    ) -> None:
        resolved_api_key = api_key or os.environ.get(API_KEY_ENV)
        if not resolved_api_key:
            raise ValueError(
                f"hosted mode requires api_key or the {API_KEY_ENV} environment variable"
            )
        resolved_base_url = base_url or os.environ.get(BASE_URL_ENV)
        if not resolved_base_url:
            raise ValueError(
                f"hosted mode requires base_url or the {BASE_URL_ENV} environment variable"
            )
        parsed_base_url = httpx.URL(resolved_base_url)
        if parsed_base_url.scheme not in ("http", "https") or not parsed_base_url.host:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if not isinstance(max_retries, int) or not 0 <= max_retries <= 10:
            raise ValueError("max_retries must be between 0 and 10")
        if parsed_base_url.scheme != "https" and parsed_base_url.host not in (
            "localhost",
            "127.0.0.1",
            "::1",
        ):
            raise ValueError("hosted API keys require HTTPS except for localhost")
        self._http = httpx.Client(
            base_url=resolved_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {resolved_api_key}"},
            timeout=timeout_s,
            transport=transport,
        )
        # Signed artifact URLs must never receive the PulseCrawl bearer key.
        self._artifacts_http = httpx.Client(
            timeout=timeout_s,
            transport=transport,
            follow_redirects=False,
        )
        self._downloader = ArtifactDownloader(self._artifacts_http)
        self._max_retries = max_retries
        self._retry_sleep = retry_sleep
        self.organizations = _Organizations(self)
        self.fields = _Fields(self)
        self.schemas = _Schemas(self)
        self.templates = _Templates(self)
        self.datasets = _Datasets(self)
        self.jobs = _Jobs(self)
        self.executions = _Executions(self)
        self.schedules = _Schedules(self)

    def close(self) -> None:
        self._http.close()
        self._artifacts_http.close()

    def __enter__(self) -> "PulseCrawl":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -- plumbing ------------------------------------------------------------

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            value = response.headers.get("Retry-After")
            if value:
                try:
                    return min(60.0, max(0.0, float(value)))
                except ValueError:
                    try:
                        when = parsedate_to_datetime(value)
                        if when.tzinfo is None:
                            when = when.replace(tzinfo=timezone.utc)
                        return min(
                            60.0,
                            max(
                                0.0, (when - datetime.now(timezone.utc)).total_seconds()
                            ),
                        )
                    except (TypeError, ValueError, OverflowError):
                        pass
        return min(8.0, 0.25 * (2**attempt))

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Mapping | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        method = method.upper()
        request_id = str(uuid4())
        headers = {"X-Request-Id": request_id}
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            headers["Idempotency-Key"] = idempotency_key or str(uuid4())
        may_retry = method in ("GET", "HEAD") or "Idempotency-Key" in headers
        response: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    headers=headers,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
                if not may_retry or attempt >= self._max_retries:
                    raise
                self._retry_sleep(self._retry_delay(None, attempt))
                continue
            idempotency_pending = False
            if response.status_code == 409 and may_retry:
                try:
                    idempotency_pending = (
                        response.json().get("error", {}).get("code")
                        == "IDEMPOTENCY_IN_PROGRESS"
                    )
                except (ValueError, AttributeError):
                    pass
            if (
                may_retry
                and (response.status_code in RETRYABLE_STATUSES or idempotency_pending)
                and attempt < self._max_retries
            ):
                self._retry_sleep(self._retry_delay(response, attempt))
                continue
            break
        assert response is not None
        if response.status_code == 204:
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.is_error:
            error = (body or {}).get("error", {})
            code = error.get("code", "INTERNAL")
            raise PulseCrawlError(
                code,
                error.get("message", f"HTTP {response.status_code}"),
                response.status_code,
                request_id=response.headers.get("X-Request-Id", request_id),
                retryable=(
                    response.status_code in RETRYABLE_STATUSES
                    or code == "IDEMPOTENCY_IN_PROGRESS"
                ),
            )
        return body

    def whoami(self) -> dict:
        return self._request("GET", "/auth/whoami")
