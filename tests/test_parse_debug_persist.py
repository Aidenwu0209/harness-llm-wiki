"""Tests for US-010: persist successful parser attempts and debug assets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.debug_store import DebugAssetStore
from docos.models.run import RunManifest, StageStatus
from docos.pipeline.orchestrator import PipelineOrchestrator
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import RouteDecision
from docos.run_store import RunStore


def _write_text_pdf(path: Path) -> Path:
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\n"
        b"endobj\n"
        b"4 0 obj\n"
        b"<< /Length 44 >>\n"
        b"stream\n"
        b"BT /F1 12 Tf 100 700 Td (Hello World) Tj ET\n"
        b"endstream\n"
        b"endobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


class TestSuccessfulParsePersistence:
    def test_parse_log_written_on_success(self, tmp_path: Path) -> None:
        """Successful parse writes a parse log with parser name, timestamps, and status."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_001",
            source_id="src_test",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success
        assert result.parse_log_path is not None

        # Verify parse log content on disk
        log_path = Path(result.parse_log_path)
        assert log_path.exists()
        log_data = json.loads(log_path.read_text(encoding="utf-8"))
        assert log_data["parser_name"] == "stdlib_pdf"
        assert log_data["success"] is True
        assert "elapsed_seconds" in log_data
        assert "logged_at" in log_data

    def test_debug_assets_under_correct_path(self, tmp_path: Path) -> None:
        """Debug assets written under source_id/run_id/parser path."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_002",
            source_id="src_abc",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success
        assert result.debug_assets_dir is not None

        # Verify directory structure
        debug_dir = Path(result.debug_assets_dir)
        assert debug_dir.exists()
        assert "src_abc" in str(debug_dir)
        assert "run_002" in str(debug_dir)
        assert "stdlib_pdf" in str(debug_dir)

    def test_run_manifest_links_to_assets(self, tmp_path: Path) -> None:
        """Run manifest links to the successful attempt log and debug asset paths."""
        # Setup run store
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_test",
            source_hash="a" * 64,
            source_file_path=str(tmp_path / "doc.pdf"),
        )

        # Run pipeline
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id=manifest.run_id,
            source_id="src_test",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success

        # Update manifest with asset links
        manifest.ir_artifact_path = result.debug_assets_dir
        run_store.update(manifest)

        # Verify manifest persistence
        loaded = run_store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.ir_artifact_path is not None

    def test_assets_manifest_written(self, tmp_path: Path) -> None:
        """DebugAssetStore writes an assets_index.json manifest."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_idx",
            source_id="src_idx",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success
        assets = debug_store.get_assets("src_idx", "run_idx", "stdlib_pdf")
        assert "parse_log" in assets
