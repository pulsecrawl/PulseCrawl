"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations


from pulsecrawl.adapters.outbound.http.resources.base import _Resource
from pulsecrawl.adapters.outbound.http.constants import *


class _Schedules(_Resource):
    def set(self, job_id: str, cron: str, *, timezone: str = "UTC") -> dict:
        """Create or replace a five-field cron schedule (minimum cadence: one hour)."""
        return self._c._request(
            "PUT",
            f"/jobs/{job_id}/schedule",
            json={"cron": cron, "timezone": timezone},
        )

    def get(self, job_id: str) -> dict:
        return self._c._request("GET", f"/jobs/{job_id}/schedule")

    def delete(self, job_id: str) -> None:
        self._c._request("DELETE", f"/jobs/{job_id}/schedule")

    def pause(self, job_id: str) -> dict:
        return self._c._request("POST", f"/jobs/{job_id}/schedule:pause")

    def resume(self, job_id: str) -> dict:
        return self._c._request("POST", f"/jobs/{job_id}/schedule:resume")
