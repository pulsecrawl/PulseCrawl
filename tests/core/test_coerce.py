import pytest

from pulsecrawl.core.coerce import CoercionError, coerce


class TestString:
    def test_strips(self):
        assert coerce("  hi  ", "string") == "hi"

    def test_empty_raises(self):
        with pytest.raises(CoercionError):
            coerce("   ", "string")


class TestNumber:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("9.99", 9.99),
            ("$1,299.00", 1299.0),
            ("1.299,00 €", 1299.0),
            ("1,299", 1299.0),
            ("12,5", 12.5),
            ("-4.5", -4.5),
            ("42", 42.0),
        ],
    )
    def test_parses_currency_formats(self, raw, expected):
        assert coerce(raw, "number") == expected

    def test_garbage_raises(self):
        with pytest.raises(CoercionError):
            coerce("free!", "number")


class TestBoolean:
    def test_truthy_falsy_words(self):
        assert coerce("Yes", "boolean") is True
        assert coerce("false", "boolean") is False
        assert coerce("1", "boolean") is True
        assert coerce("off", "boolean") is False

    def test_garbage_raises(self):
        with pytest.raises(CoercionError):
            coerce("maybe", "boolean")


class TestDatetime:
    def test_iso_with_z(self):
        assert coerce("2026-08-21T12:00:00Z", "datetime") == "2026-08-21T12:00:00+00:00"

    def test_naive_becomes_utc(self):
        assert coerce("2026-08-21T12:00:00", "datetime") == "2026-08-21T12:00:00+00:00"

    def test_garbage_raises(self):
        with pytest.raises(CoercionError):
            coerce("yesterday", "datetime")


class TestUrl:
    def test_normalizes(self):
        assert coerce("HTTPS://X.Example/img.png", "url") == "https://x.example/img.png"

    def test_resolves_relative_value_against_page_url(self):
        assert coerce(
            "../canonical", "url", base_url="https://x.example/articles/story"
        ) == "https://x.example/canonical"

    def test_garbage_raises(self):
        with pytest.raises(CoercionError):
            coerce("not a url", "url")


def test_unknown_type_raises():
    with pytest.raises(CoercionError):
        coerce("x", "blob")  # type: ignore[arg-type]
