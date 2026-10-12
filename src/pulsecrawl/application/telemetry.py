"""Small structured logging helpers with conservative secret and URL redaction."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit


_SENSITIVE = ("authorization", "cookie", "password", "secret", "token", "api_key")


def _redact(value: Any, *, key: str = "") -> Any:
    lowered = key.lower()
    if any(part in lowered for part in _SENSITIVE):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item): _redact(nested, key=str(item)) for item, nested in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = urlsplit(value)
            if parsed.scheme in ("http", "https") and parsed.hostname:
                host = parsed.hostname
                if ":" in host and not host.startswith("["):
                    host = f"[{host}]"
                netloc = host + (f":{parsed.port}" if parsed.port else "")
                value = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
        except ValueError:
            pass
        return value if len(value) <= 1000 else value[:997] + "..."
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def event(
    logger: logging.Logger, name: str, *, level: int = logging.INFO, **fields: Any
) -> None:
    payload = {"event": name, **_redact(fields)}
    logger.log(level, json.dumps(payload, sort_keys=True, separators=(",", ":")))
