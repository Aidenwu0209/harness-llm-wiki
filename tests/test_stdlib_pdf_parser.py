"""Tests for US-008: primary PDF parser adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.models.docir import BlockType, DocIR
from docos.pipeline.parser import ParserCapability, ParserRegistry
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser


def _write_text_pdf(path: Path) -> Path:
    """Write a minimal PDF with some text content."""
    # A minimal PDF with text in a content stream
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
        b"xref\n0 5\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000214 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n358\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _write_encrypted_pdf(path: Path) -> Path:
    """Write a minimal encrypted PDF."""
    pdf = (
        b"%PDF-1.4\n"
        b"/Encrypt\n"
        b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _write_invalid_pdf(path: Path) -> Path:
    """Write an invalid file (not a PDF)."""
    path.write_bytes(b"This is not a PDF file")
    return path


class TestStdlibPDFParser:
    def test_parser_name_and_version(self) -> None:
        parser = StdlibPDFParser()
        assert parser.name == "stdlib_pdf"
        assert parser.version == "1.0.0"

    def test_parser_capabilities(self) -> None:
        parser = StdlibPDFParser()
        caps = parser.capabilities()
        assert ParserCapability.TEXT_EXTRACTION in caps
        assert ParserCapability.READING_ORDER in caps

    def test_parser_healthcheck(self) -> None:
        parser = StdlibPDFParser()
        health = parser.healthcheck()
        assert health.healthy is True
        assert health.parser_name == "stdlib_pdf"

    def test_parse_text_pdf(self, tmp_path: Path) -> None:
        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        parser = StdlibPDFParser()
        result = parser.parse(pdf_path)

        assert result.success is True
        assert result.parser_name == "stdlib_pdf"
        assert result.pages_parsed >= 1

    def test_parse_returns_structured_error_for_missing_file(self, tmp_path: Path) -> None:
        parser = StdlibPDFParser()
        result = parser.parse(tmp_path / "nonexistent.pdf")

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower() or "cannot" in result.error.lower()

    def test_parse_returns_error_for_invalid_pdf(self, tmp_path: Path) -> None:
        invalid_path = _write_invalid_pdf(tmp_path / "fake.pdf")
        parser = StdlibPDFParser()
        result = parser.parse(invalid_path)

        assert result.success is False
        assert result.error is not None
        assert "pdf" in result.error.lower()

    def test_parse_returns_error_for_encrypted(self, tmp_path: Path) -> None:
        enc_path = _write_encrypted_pdf(tmp_path / "enc.pdf")
        parser = StdlibPDFParser()
        result = parser.parse(enc_path)

        assert result.success is False
        assert result.error is not None
        assert "encrypted" in result.error.lower()

    def test_normalize_produces_docir(self, tmp_path: Path) -> None:
        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        parser = StdlibPDFParser()
        result = parser.parse(pdf_path)
        assert result.success

        docir = parser.normalize(result)
        assert isinstance(docir, DocIR)
        assert docir.parser == "stdlib_pdf"
        assert docir.page_count >= 1
        assert len(docir.pages) >= 1

    def test_normalize_raises_for_failed_parse(self, tmp_path: Path) -> None:
        enc_path = _write_encrypted_pdf(tmp_path / "enc.pdf")
        parser = StdlibPDFParser()
        result = parser.parse(enc_path)
        assert not result.success

        with pytest.raises(ValueError, match="Cannot normalize"):
            parser.normalize(result)


class TestParserRegistry:
    def test_registry_lists_pdf_parser(self) -> None:
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        names = registry.list_parsers()
        assert "stdlib_pdf" in names

    def test_registry_get_parser(self) -> None:
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        parser = registry.get("stdlib_pdf")
        assert parser is not None
        assert parser.name == "stdlib_pdf"

    def test_registry_all_healthy(self) -> None:
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        health = registry.all_healthy()
        assert "stdlib_pdf" in health
        assert health["stdlib_pdf"].healthy is True
