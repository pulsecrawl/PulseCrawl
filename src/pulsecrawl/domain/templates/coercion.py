"""Field-type coercion from raw extracted strings to typed values."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pulsecrawl.domain.crawling.model import FieldType
from pulsecrawl.domain.crawling.urls import normalize_url

_TRUE = {"true", "yes", "1", "on"}
_FALSE = {"false", "no", "0", "off"}
_NUMBER_JUNK = re.compile(r"[^\d.,\-]")


class CoercionError(ValueError):
    pass


def coerce(raw: str, field_type: FieldType, *, base_url: str | None = None) -> object:
    value = raw.strip()
    if not value:
        raise CoercionError("empty value")

    if field_type == "string":
        return value

    if field_type == "number":
        cleaned = _NUMBER_JUNK.sub("", value)
        # "1.299,00" (EU) vs "1,299.00" (US): the last separator is the decimal.
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            head, _, tail = cleaned.rpartition(",")
            cleaned = (
                f"{head.replace(',', '')}.{tail}"
                if len(tail) != 3
                else cleaned.replace(",", "")
            )
        try:
            return float(cleaned)
        except ValueError as e:
            raise CoercionError(f"not a number: {raw!r}") from e

    if field_type == "boolean":
        lowered = value.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise CoercionError(f"not a boolean: {raw!r}")

    if field_type == "datetime":
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as e:
            raise CoercionError(f"not an ISO datetime: {raw!r}") from e
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()

    if field_type == "url":
        normalized = normalize_url(value, base=base_url)
        if normalized is None:
            raise CoercionError(f"not a URL: {raw!r}")
        return normalized

    raise CoercionError(f"unknown field type: {field_type}")
