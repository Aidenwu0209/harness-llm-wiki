"""Tests for US-009: fallback PDF parser and registry failover wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.models.docir import DocIR
from docos.pipeline.orchestrator import PipelineOrchestrator
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import RouteDecision


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


def _write_encrypted_pdf(path: Path) -> Path:
    pdf = (
        b"%PDF-1.4\n"
        b"/Encrypt\n"
        b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


class TestBasicTextFallbackParser:
    def test_parser_name(self) -> None:
        parser = BasicTextFallbackParser()
        assert parser.name == "basic_text_fallback"

    def test_parse_text_pdf(self, tmp_path: Path) -> None:
        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        parser = BasicTextFallbackParser()
        result = parser.parse(pdf_path)
        assert result.success is True

    def test_normalize_produces_docir(self, tmp_path: Path) -> None:
        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        parser = BasicTextFallbackParser()
        result = parser.parse(pdf_path)
        assert result.success

        docir = parser.normalize(result)
        assert isinstance(docir, DocIR)
        assert docir.parser == "basic_text_fallback"
        assert docir.confidence == 0.5  # Lower than primary

    def test_healthcheck(self) -> None:
        parser = BasicTextFallbackParser()
        health = parser.healthcheck()
        assert health.healthy is True


class TestParserRegistryFailover:
    def test_registry_contains_fallback_for_pdf(self) -> None:
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())
        names = registry.list_parsers()
        assert "stdlib_pdf" in names
        assert "basic_text_fallback" in names

    def test_primary_succeeds_no_fallback(self, tmp_path: Path) -> None:
        """When primary parser succeeds, no fallback is used."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        orchestrator = PipelineOrchestrator(registry)
        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")

        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=["basic_text_fallback"],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_test",
            source_id="src_test",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success is True
        assert result.final_parser == "stdlib_pdf"
        assert result.fallback_used is False
        assert result.primary_succeeded is True

    def test_primary_fails_fallback_succeeds(self, tmp_path: Path) -> None:
        """When primary parser fails, fallback is invoked and succeeds."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        orchestrator = PipelineOrchestrator(registry)
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
            run_id="run_failover",
            source_id="src_test",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success is True
        assert result.fallback_used is True
        assert result.final_parser == "basic_text_fallback"
        assert result.primary_succeeded is False
        assert result.fallback_parser == "basic_text_fallback"

    def test_result_records_parser_order(self, tmp_path: Path) -> None:
        """Run result records all parser attempts in order."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        orchestrator = PipelineOrchestrator(registry)
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
            run_id="run_order",
            source_id="src_test",
            file_path=pdf_path,
            route_decision=decision,
        )

        # Should have 2 attempts: primary (failed) + fallback (succeeded)
        assert len(result.attempts) == 2
        assert result.attempts[0].parser_name == "stdlib_pdf"
        assert result.attempts[1].parser_name == "basic_text_fallback"
        assert result.attempts[0].success is False
        assert result.attempts[1].success is True

    def test_review_policy_override_on_fallback(self, tmp_path: Path) -> None:
        """Fallback results trigger strict review policy override."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        orchestrator = PipelineOrchestrator(registry)
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
            run_id="run_review",
            source_id="src_test",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.fallback_used is True
        assert result.review_policy_override == "strict"
