"""Untrusted artifact paths and concurrent writers cannot escape or clobber."""

import os
from pathlib import Path

import httpx
import pytest

from pulsecrawl.adapters.outbound.http.artifacts import ArtifactDownloader


def artifact(name="nested/part.parquet", **extra):
    return {
        "name": name,
        "url": "https://artifacts.example/part",
        "sizeBytes": 3,
        **extra,
    }


def download(files, root, handler=None, **options):
    with httpx.Client(
        transport=httpx.MockTransport(
            handler or (lambda _: httpx.Response(200, content=b"new"))
        )
    ) as http:
        return ArtifactDownloader(http).download(files, root, **options)


@pytest.mark.parametrize("kind", ["file", "directory", "symlink"])
def test_competing_target_created_during_download_is_preserved(tmp_path, kind):
    target = tmp_path / "nested/part.parquet"
    if kind == "symlink":
        probe = tmp_path / "probe"
        try:
            probe.symlink_to(tmp_path / "missing")
        except OSError:
            pytest.skip("symlink creation requires platform privileges")
        probe.unlink()

    def handler(_):
        if kind == "file":
            target.write_bytes(b"original")
        elif kind == "directory":
            target.mkdir()
        else:
            target.symlink_to(tmp_path / "missing")
        return httpx.Response(200, content=b"new")

    with pytest.raises(OSError):
        download([artifact()], tmp_path, handler)
    if kind == "file":
        assert target.read_bytes() == b"original"
    elif kind == "directory":
        assert target.is_dir()
    else:
        assert target.is_symlink()
        assert not (tmp_path / "missing").exists()
    assert not list(tmp_path.rglob(".pulsecrawl-download-*"))


def test_explicit_overwrite_replaces_regular_file(tmp_path):
    target = tmp_path / "nested/part.parquet"
    target.parent.mkdir()
    target.write_bytes(b"original")
    assert download([artifact()], tmp_path, overwrite=True) == [target]
    assert target.read_bytes() == b"new"


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_overwrite_rejects_nonregular_existing_targets(tmp_path, kind):
    target = tmp_path / "part.parquet"
    if kind == "directory":
        target.mkdir()
    else:
        try:
            target.symlink_to(tmp_path / "missing")
        except OSError:
            pytest.skip("symlink creation requires platform privileges")
    with pytest.raises(ValueError, match="not a regular file"):
        download([artifact(target.name)], tmp_path, overwrite=True)


def test_nested_symlink_escape_creates_nothing_outside_destination(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires platform privileges")

    def unexpected_request(_):
        pytest.fail("unsafe path must be rejected before HTTP")

    with pytest.raises(ValueError, match="escapes destination"):
        download([artifact("linked/unexpected/part.parquet")], root, unexpected_request)
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="Windows locks parents against rename")
def test_parent_swap_cannot_redirect_staging_or_publication(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    outside.mkdir()

    def handler(_):
        (root / "nested").rename(root / "pinned")
        (root / "nested").symlink_to(outside, target_is_directory=True)
        return httpx.Response(200, content=b"new")

    download([artifact()], root, handler)
    assert list(outside.iterdir()) == []
    assert (root / "pinned/part.parquet").read_bytes() == b"new"
    assert not list(root.rglob(".pulsecrawl-download-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_windows_parent_is_locked_during_download(tmp_path):
    def handler(_):
        with pytest.raises(OSError):
            (tmp_path / "nested").rename(tmp_path / "moved")
        # Reparse mutation uses a write handle, not necessarily DELETE access.
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create.restype = wintypes.HANDLE
        handle = create(
            str(tmp_path / "nested"), 0x40000000, 7, None, 3, 0x02200000, None
        )
        error = ctypes.get_last_error()
        if handle != ctypes.c_void_p(-1).value:
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close(handle)
            pytest.fail("a pinned parent must deny reparse/write access")
        assert error == 32  # ERROR_SHARING_VIOLATION
        return httpx.Response(200, content=b"new")

    download([artifact()], tmp_path, handler)
    assert (tmp_path / "nested/part.parquet").read_bytes() == b"new"


@pytest.mark.parametrize(
    "name",
    [
        "",
        "/part.parquet",
        "../part.parquet",
        "nested/../part.parquet",
        "nested/./part.parquet",
        "nested//part.parquet",
        "C:/part.parquet",
        "nested\\part.parquet",
        "nested/part:stream.parquet",
        "NUL.parquet",
        "COM¹.parquet",
        "LPT².parquet",
        "CONIN$.parquet",
        "CON .parquet",
        "COM1/part.parquet",
        "nested /part.parquet",
        "nested./part.parquet",
        "nested/\0part.parquet",
        "part.txt",
    ],
)
def test_unsafe_manifest_rejected_before_creating_destination(tmp_path, name):
    root = tmp_path / "not-created"
    with pytest.raises(ValueError, match="unsafe artifact path"):
        download([artifact(name)], root)
    assert not root.exists()


@pytest.mark.parametrize("other", ["nested/part.parquet", "NESTED/part.parquet"])
def test_duplicate_manifest_rejected_before_writing(tmp_path, other):
    root = tmp_path / "not-created"
    with pytest.raises(ValueError, match="duplicate artifact paths"):
        download([artifact(), artifact(other)], root)
    assert not root.exists()


@pytest.mark.parametrize(
    "options,response,match",
    [
        ({}, httpx.Response(500), "500"),
        ({}, httpx.Response(200, content=b"wrong-size"), "size mismatch"),
        (
            {"max_total_bytes": 4},
            httpx.Response(200, content=b"too-large"),
            "max_total_bytes",
        ),
    ],
)
def test_failed_download_keeps_original_and_cleans_only_staging(
    tmp_path, options, response, match
):
    target = tmp_path / "nested/part.parquet"
    target.parent.mkdir()
    target.write_bytes(b"original")
    with pytest.raises((httpx.HTTPStatusError, OSError, ValueError), match=match):
        download([artifact()], tmp_path, lambda _: response, overwrite=True, **options)
    assert target.read_bytes() == b"original"
    assert list(target.parent.iterdir()) == [target]


def test_negative_size_cannot_bypass_manifest_byte_limit(tmp_path):
    with pytest.raises(ValueError, match="negative artifact size"):
        download([artifact(sizeBytes=-100)], tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


def test_iterable_manifest_is_not_consumed_by_preflight(tmp_path):
    assert download(iter([artifact()]), tmp_path) == [tmp_path / "nested/part.parquet"]
