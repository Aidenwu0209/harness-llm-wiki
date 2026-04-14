"""Tests for US-014: Align parser extras and install errors with runtime strategy."""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.pipeline.orchestrator import PipelineOrchestrator, _missing_parser_message
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.router import RouteDecision


# ---------------------------------------------------------------------------
# PDF helper
# ---------------------------------------------------------------------------

def _write_simple_pdf(path: Path) -> Path:
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 80 >>\nstream\n"
        b"BT /F1 12 Tf 100 700 Td (Introduction) Tj ET\n"
        b"BT /F1 10 Tf 100 680 Td (This is a test document body.) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMissingParserInstallMessage:
    """US-014: Missing-parser error names the parser and install path."""

    def test_known_parser_name_includes_install_hint(self) -> None:
        """Known external parser names get a pip install hint."""
        msg = _missing_parser_message("pymupdf")
        assert "pymupdf" in msg
        assert "pip install docos[parser]" in msg

    def test_ocr_parser_includes_ocr_extra(self) -> None:
        msg = _missing_parser_message("paddleocr")
        assert "paddleocr" in msg
        assert "pip install docos[ocr]" in msg

    def test_unknown_parser_includes_generic_hint(self) -> None:
        msg = _missing_parser_message("totally_unknown")
        assert "totally_unknown" in msg
        assert "pyproject.toml" in msg

    def test_orchestrator_failure_message_includes_parser_name(self, tmp_path: Path) -> None:
        """When primary parser is missing, failure_reason names the parser."""
        registry = ParserRegistry()  # empty
        decision = RouteDecision(
            selected_route="test",
            primary_parser="pymupdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )
        orchestrator = PipelineOrchestrator(parser_registry=registry)
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        result = orchestrator.execute(
            run_id="test_run",
            source_id="src_test",
            file_path=pdf_path,
            route_decision=decision,
        )
        assert not result.success
        assert result.failure_reason is not None
        assert "pymupdf" in result.failure_reason
        assert "pip install docos[parser]" in result.failure_reason

    def test_orchestrator_with_unknown_parser_generic_message(self, tmp_path: Path) -> None:
        """Unknown parser names get a generic pyproject.toml hint."""
        registry = ParserRegistry()  # empty
        decision = RouteDecision(
            selected_route="test",
            primary_parser="custom_magic_parser",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )
        orchestrator = PipelineOrchestrator(parser_registry=registry)
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        result = orchestrator.execute(
            run_id="test_run",
            source_id="src_test",
            file_path=pdf_path,
            route_decision=decision,
        )
        assert not result.success
        assert result.failure_reason is not None
        assert "custom_magic_parser" in result.failure_reason
        assert "pyproject.toml" in result.failure_reason
