from types import SimpleNamespace
import pytest

from pulsecrawl.application.datasets.publication import DatasetPublicationService
from pulsecrawl.application.time import readiness_time
from pulsecrawl.application.templates.resolution import TemplateResolver
from pulsecrawl.domain.crawling.model import TemplateSpec


def test_publication_makes_manifest_visible_only_after_file_durability():
    events = []
    item = {"path": "data/a.parquet"}

    def write(**kwargs):
        events.append("file_durable")
        return item

    def add_file(value, *, change_id):
        assert events == ["file_durable"]
        assert value == item and change_id == "execution-a"
        events.append("manifest_visible")

    service = DatasetPublicationService(
        SimpleNamespace(write=write), SimpleNamespace(add_file=add_file)
    )
    assert service.publish(change_id="execution-a") == item
    assert events == ["file_durable", "manifest_visible"]


def test_no_records_means_no_manifest_change():
    service = DatasetPublicationService(
        SimpleNamespace(write=lambda **kw: None), object()
    )
    assert service.publish(change_id="empty") is None


def test_file_failure_cannot_publish_manifest():
    def fail(**kwargs):
        raise OSError("disk full")

    service = DatasetPublicationService(SimpleNamespace(write=fail), object())
    with pytest.raises(OSError):
        service.publish(change_id="failed")


def test_manifest_failure_retries_with_same_publication_identity():
    calls = []

    def add_file(item, *, change_id):
        calls.append(change_id)
        if len(calls) == 1:
            raise OSError("manifest unavailable")

    service = DatasetPublicationService(
        SimpleNamespace(write=lambda **kw: {"path": "same"}),
        SimpleNamespace(add_file=add_file),
    )
    with pytest.raises(OSError):
        service.publish(change_id="e")
    assert service.publish(change_id="e") == {"path": "same"}
    assert calls == ["e", "e"]


def test_readiness_clock_supports_new_and_legacy_adapters():
    assert (
        readiness_time(
            SimpleNamespace(readiness_time=lambda: 42, monotonic=lambda: 100)
        )
        == 42
    )
    assert readiness_time(SimpleNamespace(monotonic=lambda: 100)) == 100


def test_resolver_uses_supplied_strategies_without_mutating_their_results():
    first = TemplateSpec("first", "css", {"a": ("x",)})
    second = TemplateSpec("second", "meta", {"a": ("x",), "b": ("y",)})
    raw = [{"a": "winner"}]
    result = TemplateResolver().resolve(
        [(first, lambda *_: raw), (second, lambda *_: [{"a": "other", "b": "fill"}])],
        [],
        "body",
        "https://example.com",
    )
    assert result.records == [{"a": "winner", "b": "fill"}]
    assert result.field_provenance == [{"a": "first", "b": "second"}]
    assert result.conflicts[0]["fieldId"] == "a"
    assert raw == [{"a": "winner"}]
