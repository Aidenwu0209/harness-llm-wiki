"""Tests for US-011: persist failed parser attempts and unavailable states."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.debug_store import DebugAssetStore
from docos.pipeline.orchestrator import PipelineOrchestrator
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import RouteDecision


def _write_encrypted_pdf(path: Path) -> Path:
    pdf = (
        b"%PDF-1.4\n"
        b"/Encrypt\n"
        b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


class TestFailedAttemptPersistence:
    def test_primary_failure_writes_log(self, tmp_path: Path) -> None:
        """A failed primary parser writes a parse log with name and failure reason."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_encrypted_pdf(tmp_path / "enc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=["basic_text_fallback"],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_fail",
            source_id="src_fail",
            file_path=pdf_path,
            route_decision=decision,
        )

        # Fallback should succeed
        assert result.success
        assert result.fallback_used is True

        # Failed attempt log should be persisted
        assert len(result.failed_attempt_paths) >= 1
        fail_log_path = Path(result.failed_attempt_paths[0])
        assert fail_log_path.exists()

        log_data = json.loads(fail_log_path.read_text(encoding="utf-8"))
        assert log_data["parser_name"] == "stdlib_pdf"
        assert log_data["success"] is False
        assert log_data["error"] is not None
        assert "encrypted" in log_data["error"].lower()

    def test_fallback_retains_reference_to_failed_primary(self, tmp_path: Path) -> None:
        """Fallback attempts retain references to the failed primary attempt artifacts."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_encrypted_pdf(tmp_path / "enc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=["basic_text_fallback"],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_ref",
            source_id="src_ref",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success
        # The failed primary log path should be in failed_attempt_paths
        assert len(result.failed_attempt_paths) >= 1
        primary_fail_path = result.failed_attempt_paths[0]
        assert "stdlib_pdf" in primary_fail_path

    def test_parser_unavailable_has_own_status(self, tmp_path: Path) -> None:
        """A parser-unavailable condition has its own status, not merged into generic failure."""
        registry = ParserRegistry()
        # Only register fallback, not the "primary"
        registry.register(BasicTextFallbackParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_encrypted_pdf(tmp_path / "enc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="nonexistent_parser",
            fallback_parsers=["basic_text_fallback"],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_unavail",
            source_id="src_unavail",
            file_path=pdf_path,
            route_decision=decision,
        )

        # Should succeed via fallback
        assert result.success

        # parser_unavailable should record the missing parser
        assert "nonexistent_parser" in result.parser_unavailable

        # The unavailable log should be persisted
        assert len(result.failed_attempt_paths) >= 1
        unavail_log = Path(result.failed_attempt_paths[0])
        assert unavail_log.exists()
        log_data = json.loads(unavail_log.read_text(encoding="utf-8"))
        assert log_data["parser_name"] == "nonexistent_parser"
        assert log_data["success"] is False
        assert "not registered" in log_data["error"] or "not available" in log_data["error"]

    def test_all_parsers_fail_still_persists_logs(self, tmp_path: Path) -> None:
        """When all parsers fail, all attempt logs are still persisted."""
        registry = ParserRegistry()
        # Register a parser that will fail on this input
        registry.register(StdlibPDFParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_encrypted_pdf(tmp_path / "enc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_all_fail",
            source_id="src_allfail",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert not result.success
        assert len(result.failed_attempt_paths) >= 1
        # The log should exist on disk
        fail_log = Path(result.failed_attempt_paths[0])
        assert fail_log.exists()
