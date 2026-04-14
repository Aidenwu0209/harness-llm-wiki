"""Tests for US-006: Resolve primary and fallback parsers through registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.pipeline.orchestrator import PipelineOrchestrator
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import RouteDecision


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


class TestParserResolution:
    """US-006: Primary and fallback parsers resolved through registry."""

    def test_primary_parser_resolved(self, tmp_path: Path) -> None:
        """Primary parser is resolved from registry."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        assert registry.get("stdlib_pdf") is not None
        assert registry.get("basic_text_fallback") is not None

    def test_fallback_parser_resolved(self, tmp_path: Path) -> None:
        """Fallback parser is resolved from registry."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=["basic_text"],
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
        assert result.success
        assert result.final_parser == "stdlib_pdf"

    def test_unresolved_parser_fails_clearly(self, tmp_path: Path) -> None:
        """Unresolved parser name produces a clear failure."""
        registry = ParserRegistry()
        # Don't register any parser

        decision = RouteDecision(
            selected_route="test",
            primary_parser="nonexistent_parser",
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
        assert "nonexistent_parser" in result.failure_reason or "nonexistent_parser" in str(result.parser_unavailable)

    def test_primary_fails_fallback_succeeds(self, tmp_path: Path) -> None:
        """When primary fails, fallback parser is used."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        # Route to a non-existent primary so fallback kicks in
        decision = RouteDecision(
            selected_route="test",
            primary_parser="nonexistent_parser",
            fallback_parsers=["basic_text_fallback"],
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
        assert result.success
        assert result.fallback_used
        assert result.final_parser == "basic_text_fallback"

    def test_registry_lists_registered_parsers(self) -> None:
        """Registry can list all registered parser names."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())
        names = registry.list_parsers()
        assert "stdlib_pdf" in names
        assert "basic_text_fallback" in names
