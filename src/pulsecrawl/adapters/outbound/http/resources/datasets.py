"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations


from pulsecrawl.adapters.outbound.http.resources.base import _Resource
from pulsecrawl.adapters.outbound.http.constants import *
from pulsecrawl.adapters.outbound.http.resources.urls import _url_params


class _Datasets(_Resource):
    def create(
        self,
        name: str,
        *,
        schema_id: str,
        mode: str = "append_all",
        identity_field: str = "_source_url",
    ) -> dict:
        """Create a dataset with an explicit URL deduplication policy.

        ``identity_field`` is ``_source_url`` or the field ID of a ``url``
        field in the schema. ``new_urls_only`` omits rows whose normalized
        identity URL appeared in an earlier execution.
        """
        if mode not in ("append_all", "new_urls_only"):
            raise ValueError("mode must be 'append_all' or 'new_urls_only'")
        if not identity_field:
            raise ValueError("identity_field must not be empty")
        return self._c._request(
            "POST",
            "/datasets",
            json={
                "name": name,
                "schemaId": schema_id,
                "mode": mode,
                "identityField": identity_field,
            },
        )

    def list(self) -> list[dict]:
        return self._c._request("GET", "/datasets")["datasets"]

    def get(self, dataset_id: str) -> dict:
        return self._c._request("GET", f"/datasets/{dataset_id}")

    def files(self, dataset_id: str) -> list[dict]:
        return self._c._request("GET", f"/datasets/{dataset_id}/files")["files"]

    def download_files(
        self,
        dataset_id,
        destination,
        *,
        overwrite=False,
        max_total_bytes=100 * 1024 * 1024 * 1024,
    ):
        return self._c._downloader.download(
            self.files(dataset_id),
            destination,
            overwrite=overwrite,
            max_total_bytes=max_total_bytes,
        )

    def query(self, dataset_id: str, sql: str) -> dict:
        """Run SQL over the dataset's Parquet. The table is named `dataset`.

        Returns {"columns": [...], "rows": [[...]], "truncated": bool}.
        """
        return self._c._request(
            "POST", f"/datasets/{dataset_id}/query", json={"sql": sql}
        )

    def urls(
        self,
        dataset_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        newness: str = "all",
        host: str | None = None,
        url_contains: str | None = None,
    ) -> dict:
        """Page canonical URL identities and their first/last-seen history."""
        return self._c._request(
            "GET",
            f"/datasets/{dataset_id}/urls",
            params=_url_params(cursor, limit, newness, host, url_contains),
        )

    def iter_urls(
        self,
        dataset_id: str,
        *,
        page_size: int = 100,
        newness: str = "all",
        host: str | None = None,
        url_contains: str | None = None,
    ):
        """Iterate canonical URL identities across every page."""
        cursor: str | None = None
        while True:
            page = self.urls(
                dataset_id,
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
