"""Tests for Source Registry service (duplicate detection + ingest history)."""

import hashlib
from pathlib import Path

import pytest

from docos.models.source import SourceStatus
from docos.registry import SourceRegistry
from docos.source_store import RawStorage


@pytest.fixture
def registry(tmp_path: Path) -> SourceRegistry:
    raw = RawStorage(tmp_path / "raw")
    return SourceRegistry(tmp_path / "registry", raw)


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    f = tmp_path / "test.pdf"
    f.write_bytes(b"Test PDF content with some data")
    return f


@pytest.fixture
def pdf_hash(pdf_file: Path) -> str:
    return hashlib.sha256(pdf_file.read_bytes()).hexdigest()


class TestDuplicateDetection:
    def test_register_new_source(self, registry: SourceRegistry, pdf_file: Path, pdf_hash: str) -> None:
        record = registry.register(pdf_file, tags=["academic"])
        assert record.source_id.startswith("src_")
        assert record.source_hash == pdf_hash
        assert record.tags == ["academic"]
        assert record.status == SourceStatus.UPLOADED

    def test_register_duplicate_returns_existing(
        self, registry: SourceRegistry, pdf_file: Path
    ) -> None:
        r1 = registry.register(pdf_file, origin="first_upload")
        r2 = registry.register(pdf_file, origin="second_upload")
        assert r1.source_id == r2.source_id
        assert r2.origin == "first_upload"  # NOT overwritten

    def test_find_by_hash(self, registry: SourceRegistry, pdf_file: Path, pdf_hash: str) -> None:
        registry.register(pdf_file)
        found = registry.find_by_hash(pdf_hash)
        assert found is not None
        assert found.source_hash == pdf_hash

    def test_find_by_hash_not_found(self, registry: SourceRegistry) -> None:
        assert registry.find_by_hash("nonexistent") is None


class TestIngestHistory:
    def test_record_successful_ingest(
        self, registry: SourceRegistry, pdf_file: Path
    ) -> None:
        record = registry.register(pdf_file)
        updated = registry.record_ingest(
            source_id=record.source_id,
            run_id="run_001",
            parser="marker",
            parser_version="1.0.0",
            docir_id="doc_001",
        )
        assert updated.ingest_count == 1
        assert updated.latest_run_id == "run_001"
        assert updated.latest_docir_id == "doc_001"
        assert updated.status == SourceStatus.COMPLETED

    def test_record_multiple_ingests(
        self, registry: SourceRegistry, pdf_file: Path
    ) -> None:
        record = registry.register(pdf_file)

        registry.record_ingest(
            source_id=record.source_id,
            run_id="run_001",
            parser="marker",
            docir_id="doc_v1",
        )
        updated = registry.record_ingest(
            source_id=record.source_id,
            run_id="run_002",
            parser="marker",
            parser_version="1.1.0",
            docir_id="doc_v2",
        )
        assert updated.ingest_count == 2
        assert updated.latest_docir_id == "doc_v2"
        assert updated.ingest_history[-1].parser_version == "1.1.0"

    def test_record_failed_ingest(
        self, registry: SourceRegistry, pdf_file: Path
    ) -> None:
        record = registry.register(pdf_file)
        updated = registry.record_ingest(
            source_id=record.source_id,
            run_id="run_001",
            status="failed",
            error_detail="Parser timeout",
        )
        assert updated.status == SourceStatus.FAILED

    def test_record_ingest_unknown_source(self, registry: SourceRegistry) -> None:
        with pytest.raises(ValueError, match="Source not found"):
            registry.record_ingest(
                source_id="nonexistent",
                run_id="run_001",
            )


class TestRegistryQueries:
    def test_get_source(self, registry: SourceRegistry, pdf_file: Path) -> None:
        record = registry.register(pdf_file)
        fetched = registry.get(record.source_id)
        assert fetched is not None
        assert fetched.source_id == record.source_id

    def test_get_nonexistent(self, registry: SourceRegistry) -> None:
        assert registry.get("nonexistent") is None

    def test_list_sources(self, registry: SourceRegistry, tmp_path: Path) -> None:
        f1 = tmp_path / "doc1.pdf"
        f1.write_bytes(b"Document one content")
        f2 = tmp_path / "doc2.pdf"
        f2.write_bytes(b"Document two content")

        registry.register(f1)
        registry.register(f2)

        sources = registry.list_sources()
        assert len(sources) == 2
