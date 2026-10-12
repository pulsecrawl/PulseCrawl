"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import unicodedata

import httpx

from pulsecrawl.adapters.outbound.filesystem.downloads import stage_artifact


def _artifact_parts(name: str) -> tuple[str, ...]:
    """Reject ambiguous or platform-specific names before path normalization."""
    parts = tuple(name.split("/"))
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
        *(f"COM{i}" for i in "¹²³"),
        *(f"LPT{i}" for i in "¹²³"),
    }
    if (
        any(part in ("", ".", "..") for part in parts)
        or any(char in name for char in '\\:*?"<>|')
        or any(ord(char) < 32 for char in name)
        or any(
            part.endswith((".", " "))
            or part.split(".")[0].rstrip(" ").upper() in reserved
            for part in parts
        )
        or PurePosixPath(name).suffix != ".parquet"
    ):
        raise ValueError("dataset API returned an unsafe artifact path")
    return parts


class ArtifactDownloader:
    def __init__(self, http):
        self._http = http

    def download(
        self,
        files,
        destination: str | Path,
        *,
        overwrite: bool = False,
        max_total_bytes: int = 100 * 1024 * 1024 * 1024,
    ) -> list[Path]:
        """Download every active Parquet file through its short-lived URL.

        Writes are atomic, relative artifact paths are preserved, and the API
        key is deliberately omitted from signed-URL requests.
        """
        files = list(files)
        sizes = [int(item.get("sizeBytes", 0)) for item in files]
        expected_total = sum(sizes)
        if any(size < 0 for size in sizes):
            raise ValueError("dataset API returned a negative artifact size")
        if max_total_bytes < 1 or expected_total > max_total_bytes:
            raise ValueError("dataset download exceeds max_total_bytes")
        root = Path(destination).expanduser()
        targets: list[tuple[dict, tuple[str, ...]]] = []
        seen: set[str] = set()
        for item in files:
            parts = _artifact_parts(str(item.get("name", "")))
            key = unicodedata.normalize("NFC", "/".join(parts)).casefold()
            if key in seen:
                raise ValueError("dataset API returned duplicate artifact paths")
            seen.add(key)
            url = httpx.URL(str(item.get("url", "")))
            if url.scheme != "https" or not url.host:
                raise ValueError("dataset API returned a non-HTTPS artifact URL")
            targets.append((item, parts))

        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve(strict=True)

        downloaded: list[Path] = []
        transferred = 0
        for item, parts in targets:
            target = root.joinpath(*parts)
            with stage_artifact(root, parts, overwrite=overwrite) as handle:
                written = 0
                with self._http.stream("GET", str(item["url"])) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        written += len(chunk)
                        transferred += len(chunk)
                        if transferred > max_total_bytes:
                            raise ValueError("dataset download exceeds max_total_bytes")
                        handle.write(chunk)
                expected = int(item.get("sizeBytes", 0))
                if expected and written != expected:
                    raise IOError(
                        f"artifact size mismatch for {item['name']}: expected {expected}, got {written}"
                    )
            downloaded.append(target)
        return downloaded
