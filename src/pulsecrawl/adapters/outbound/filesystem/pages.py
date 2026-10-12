"""Filesystem Parquet datasets, versioned manifests, and local URL history."""

from __future__ import annotations


from pulsecrawl.adapters.outbound.filesystem.atomic import (
    _atomic_json,
    _persistable_headers,
)


class JsonPageSink:
    def __init__(self, execution_dir, store_raw_pages):
        self.execution_dir, self.store_raw_pages = execution_dir, store_raw_pages

    async def save(self, hashed: str, snapshot) -> None:
        if not self.store_raw_pages:
            return
        _atomic_json(
            self.execution_dir / "pages" / f"{hashed}.json",
            {
                "url": snapshot.url,
                "finalUrl": snapshot.final_url,
                "status": snapshot.status,
                "headers": _persistable_headers(snapshot.headers),
                "body": snapshot.body,
                "depth": snapshot.depth,
                "fetchedAt": snapshot.fetched_at.isoformat(),
                "bodyTruncated": snapshot.body_truncated,
                "bodyBytes": snapshot.body_bytes,
            },
        )
