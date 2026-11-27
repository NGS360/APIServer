"""
Unit tests for turning a submitted workflow definition into stored gzip bytes.
"""
import gzip
import io
import zipfile

import pytest
from fastapi import HTTPException

from api.project import services

SAMPLE = b"version 1.0\nworkflow demo {}\n"


def make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_plain_text_is_compressed():
    stored = services._gzipped_definition(SAMPLE)
    assert gzip.decompress(stored) == SAMPLE


def test_gzip_is_kept_as_it_is_not_compressed_again():
    already = gzip.compress(SAMPLE)
    assert services._gzipped_definition(already) == already


def test_zip_with_one_file_is_unpacked_and_compressed():
    stored = services._gzipped_definition(make_zip({"main.wdl": SAMPLE}))
    assert gzip.decompress(stored) == SAMPLE


def test_zip_directory_entries_are_ignored():
    zip_bytes = make_zip({"wf/": b"", "wf/main.wdl": SAMPLE})
    assert gzip.decompress(services._gzipped_definition(zip_bytes)) == SAMPLE


def test_zip_with_several_files_is_rejected():
    zip_bytes = make_zip({"a.wdl": SAMPLE, "b.wdl": SAMPLE})
    with pytest.raises(HTTPException) as exc:
        services._gzipped_definition(zip_bytes)
    assert exc.value.status_code == 400


def test_corrupt_gzip_is_rejected():
    corrupt = b"\x1f\x8b" + b"not really gzip"
    with pytest.raises(HTTPException) as exc:
        services._gzipped_definition(corrupt)
    assert exc.value.status_code == 400


def test_corrupt_zip_is_rejected():
    corrupt = b"PK\x03\x04" + b"garbage"
    with pytest.raises(HTTPException) as exc:
        services._gzipped_definition(corrupt)
    assert exc.value.status_code == 400


def test_oversized_content_is_rejected(monkeypatch):
    monkeypatch.setattr(services, "_MAX_WORKFLOW_BYTES", 10)
    with pytest.raises(HTTPException) as exc:
        services._gzipped_definition(b"x" * 11)
    assert exc.value.status_code == 400


def test_zip_bomb_is_stopped_by_the_decompressed_size_limit(monkeypatch):
    monkeypatch.setattr(services, "_MAX_WORKFLOW_BYTES", 1000)
    bomb = make_zip({"big.wdl": b"0" * 100_000})
    with pytest.raises(HTTPException) as exc:
        services._gzipped_definition(bomb)
    assert exc.value.status_code == 400
