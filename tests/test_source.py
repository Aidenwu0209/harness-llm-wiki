"""Tests for Source Registry."""

from datetime import datetime

import pytest

from docos.models.source import IngestEntry, SourceRecord, SourceStatus


class TestSourceRecord:
    def test_minimal_source(self) -> None:
        s = SourceRecord(
            source_id="src_0001",
            source_hash="abc123",
            file_name="readoc.pdf",
            byte_size=2_000_000,
        )
        assert s.source_id == "src_0001"
        assert s.status == SourceStatus.UPLOADED
        assert s.ingest_count == 0
        assert s.ingest_history == []

    def test_full_source(self) -> None:
        s = SourceRecord(
            source_id="src_0001",
            source_hash="sha256:abcdef",
            file_name="readoc.pdf",
            mime_type="application/pdf",
            byte_size=2_000_000,
            language_hint=["en"],
            origin="upload",
            tags=["academic", "benchmark"],
            owner="alice",
            status=SourceStatus.COMPLETED,
            latest_run_id="run_001",
            latest_docir_id="doc_001",
            wiki_page_path="wiki/sources/src_0001.md",
            review_ids=["rev_001"],
            raw_storage_path="raw/src_0001/original.pdf",
        )
        assert s.wiki_page_path == "wiki/sources/src_0001.md"
        assert len(s.tags) == 2

    def test_add_successful_ingest(self) -> None:
        s = SourceRecord(
            source_id="src_0001",
            source_hash="abc",
            file_name="test.pdf",
            byte_size=100,
        )
        entry = IngestEntry(
            run_id="run_001",
            parser="marker",
            parser_version="1.0.0",
            status="success",
            docir_id="doc_001",
        )
        s.add_ingest(entry)
        assert s.ingest_count == 1
        assert s.latest_run_id == "run_001"
        assert s.latest_docir_id == "doc_001"
        assert s.status == SourceStatus.COMPLETED
        assert s.ingested_at is not None

    def test_add_failed_ingest(self) -> None:
        s = SourceRecord(
            source_id="src_0001",
            source_hash="abc",
            file_name="test.pdf",
            byte_size=100,
        )
        entry = IngestEntry(
            run_id="run_001",
            status="failed",
            error_detail="Parser timeout",
        )
        s.add_ingest(entry)
        assert s.status == SourceStatus.FAILED
        assert s.latest_docir_id is None

    def test_multiple_ingests(self) -> None:
        s = SourceRecord(
            source_id="src_0001",
            source_hash="abc",
            file_name="test.pdf",
            byte_size=100,
        )
        # First ingest: success
        s.add_ingest(IngestEntry(run_id="run_001", status="success", docir_id="doc_v1"))
        # Second ingest: success (parser upgrade)
        s.add_ingest(IngestEntry(run_id="run_002", status="success", docir_id="doc_v2"))

        assert s.ingest_count == 2
        assert s.latest_docir_id == "doc_v2"
        assert s.latest_run_id == "run_002"

    def test_all_statuses(self) -> None:
        for status in SourceStatus:
            s = SourceRecord(
                source_id=f"src_{status.value}",
                source_hash="abc",
                file_name="test.pdf",
                byte_size=100,
                status=status,
            )
            assert s.status == status


class TestIngestEntry:
    def test_minimal_entry(self) -> None:
        e = IngestEntry(run_id="run_001")
        assert e.status == "success"
        assert e.fallback_used is False

    def test_fallback_entry(self) -> None:
        e = IngestEntry(
            run_id="run_001",
            status="success",
            fallback_used=True,
            parser="pdfplumber",
        )
        assert e.fallback_used is True
