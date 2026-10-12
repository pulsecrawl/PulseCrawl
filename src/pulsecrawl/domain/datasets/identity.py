"""Conservative dataset URL identity; deliberately distinct from crawl URL normalization."""

import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

_PERCENT_ESCAPE = re.compile(r"%([0-9a-fA-F]{2})")
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def normalize_url_identity(value: object) -> str | None:
    """Conservative HTTP URL identity shared with hosted dataset semantics."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlsplit(value.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https") or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        port = parsed.port
        if ":" in host:
            host = f"[{host}]"
        if port is not None and not (
            (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        ):
            host = f"{host}:{port}"

        def percent(match: re.Match[str]) -> str:
            char = chr(int(match.group(1), 16))
            return char if char in _UNRESERVED else f"%{match.group(1).upper()}"

        path = _PERCENT_ESCAPE.sub(percent, parsed.path or "/")
        pairs = sorted(parse_qsl(parsed.query, keep_blank_values=True))
        query = _PERCENT_ESCAPE.sub(
            percent, urlencode(pairs, doseq=True, quote_via=quote)
        )
        return urlunsplit((scheme, host, path, query, ""))
    except (UnicodeError, ValueError):
        return None
