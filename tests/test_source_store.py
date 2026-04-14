"""Tests for immutable raw source storage."""

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from docos.models.source import SourceRecord
from docos.source_store import RawStorage


@pytest.fixture
def tmp_storage(tmp_path: Path) -> RawStorage:
    return RawStorage(tmp_path / "raw")


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.pdf"
    f.write_bytes(b"Sample PDF content for testing")
    return f


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestRawStorage:
    def test_store_and_read(self, tmp_storage: RawStorage, sample_file: Path) -> None:
        h = _file_hash(sample_file)
        source = SourceRecord(
            source_id="src_001",
            source_hash=h,
            file_name="sample.pdf",
            mime_type="application/pdf",
            byte_size=sample_file.stat().st_size,
        )

        stored_path = tmp_storage.store(source, sample_file)
        assert stored_path.exists()

        # Read metadata
        meta = tmp_storage.read_metadata("src_001")
        assert meta["source_id"] == "src_001"
        assert meta["file_name"] == "sample.pdf"
        assert meta["source_hash"] == h

    def test_prevent_overwrite(self, tmp_storage: RawStorage, sample_file: Path) -> None:
        h = _file_hash(sample_file)
        source = SourceRecord(
            source_id="src_002",
            source_hash=h,
            file_name="sample.pdf",
            byte_size=100,
        )
        tmp_storage.store(source, sample_file)

        with pytest.raises(FileExistsError, match="already exists"):
            tmp_storage.store(source, sample_file)

    def test_source_file_not_found(self, tmp_storage: RawStorage) -> None:
        source = SourceRecord(
            source_id="src_003",
            source_hash="abc",
            file_name="missing.pdf",
            byte_size=100,
        )
        with pytest.raises(FileNotFoundError, match="not found"):
            tmp_storage.store(source, Path("/nonexistent/file.pdf"))

    def test_hash_mismatch(self, tmp_storage: RawStorage, sample_file: Path) -> None:
        source = SourceRecord(
            source_id="src_004",
            source_hash="wrong_hash",
            file_name="sample.pdf",
            byte_size=100,
        )
        with pytest.raises(ValueError, match="Hash mismatch"):
            tmp_storage.store(source, sample_file)

    def test_exists(self, tmp_storage: RawStorage, sample_file: Path) -> None:
        assert not tmp_storage.exists("src_005")
        h = _file_hash(sample_file)
        source = SourceRecord(
            source_id="src_005",
            source_hash=h,
            file_name="sample.pdf",
            byte_size=100,
        )
        tmp_storage.store(source, sample_file)
        assert tmp_storage.exists("src_005")

    def test_metadata_not_found(self, tmp_storage: RawStorage) -> None:
        with pytest.raises(FileNotFoundError, match="No metadata"):
            tmp_storage.read_metadata("nonexistent")

    def test_compute_hash(self, sample_file: Path) -> None:
        h = RawStorage.compute_hash(sample_file)
        assert h == _file_hash(sample_file)
        assert len(h) == 64  # SHA-256 hex digest length
