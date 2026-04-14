"""US-027: Add real E2E source fixtures.

Verifies that:
- simple_text.pdf fixture exists and is a valid PDF
- complex_layout.pdf (dual_column_or_formula) fixture exists and is a valid PDF
- table_formula.pdf or ocr_like.pdf fixture exists for OCR/table coverage
- Fixtures are valid PDFs that parse successfully
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.build_fixtures import (
    _build_dual_column_pdf,
    _build_ocr_like_pdf,
    _build_simple_pdf,
    _build_table_formula_pdf,
    get_all_fixtures,
    get_fixture,
)


class TestSimpleTextFixture:
    """Test the simple_text.pdf fixture."""

    def test_simple_text_fixture_exists(self, tmp_path: Path) -> None:
        """simple_text.pdf can be built and is a valid PDF."""
        path = tmp_path / "simple_text.pdf"
        path.write_bytes(_build_simple_pdf())
        assert path.exists()
        assert path.stat().st_size > 0
        raw = path.read_bytes()
        assert raw.startswith(b"%PDF")

    def test_simple_text_fixture_has_text_content(self) -> None:
        """Simple fixture contains meaningful text content."""
        raw = _build_simple_pdf()
        assert b"Introduction" in raw
        assert b"pipeline" in raw
        assert b"parsing" in raw

    def test_simple_text_fixture_parses_successfully(self, tmp_path: Path) -> None:
        """simple_text.pdf can be processed by SignalExtractor."""
        from docos.pipeline.signal_extractor import SignalExtractor

        path = tmp_path / "simple_text.pdf"
        path.write_bytes(_build_simple_pdf())
        extractor = SignalExtractor()
        signals = extractor.extract(path)
        assert signals.file_type == "application/pdf"
        assert signals.page_count >= 1


class TestComplexLayoutFixture:
    """Test the dual_column_or_formula.pdf fixture (complex_layout)."""

    def test_complex_layout_fixture_exists(self, tmp_path: Path) -> None:
        """dual_column_or_formula.pdf can be built and is a valid PDF."""
        path = tmp_path / "complex_layout.pdf"
        path.write_bytes(_build_dual_column_pdf())
        assert path.exists()
        assert path.stat().st_size > 0
        raw = path.read_bytes()
        assert raw.startswith(b"%PDF")

    def test_complex_layout_fixture_has_two_columns(self) -> None:
        """Dual-column fixture has text at both left and right x-coordinates."""
        raw = _build_dual_column_pdf()
        assert b"Left Column" in raw
        assert b"Right Column" in raw
        assert b"320" in raw  # right column x offset

    def test_complex_layout_fixture_parses_successfully(self, tmp_path: Path) -> None:
        """dual_column fixture can be processed by SignalExtractor."""
        from docos.pipeline.signal_extractor import SignalExtractor

        path = tmp_path / "dual_column_or_formula.pdf"
        path.write_bytes(_build_dual_column_pdf())
        extractor = SignalExtractor()
        signals = extractor.extract(path)
        assert signals.file_type == "application/pdf"
        assert signals.page_count >= 1


class TestOCRLikeFixture:
    """Test the ocr_like.pdf fixture."""

    def test_ocr_like_fixture_exists(self, tmp_path: Path) -> None:
        """ocr_like.pdf can be built and is a valid PDF."""
        path = tmp_path / "ocr_like.pdf"
        path.write_bytes(_build_ocr_like_pdf())
        assert path.exists()
        assert path.stat().st_size > 0
        raw = path.read_bytes()
        assert raw.startswith(b"%PDF")

    def test_ocr_like_fixture_is_image_heavy(self) -> None:
        """OCR-like fixture has many image streams."""
        raw = _build_ocr_like_pdf()
        assert raw.count(b"/Subtype /Image") >= 5
        assert b"Page 1" in raw

    def test_ocr_like_fixture_parses_successfully(self, tmp_path: Path) -> None:
        """ocr_like.pdf can be processed by SignalExtractor."""
        from docos.pipeline.signal_extractor import SignalExtractor

        path = tmp_path / "ocr_like.pdf"
        path.write_bytes(_build_ocr_like_pdf())
        extractor = SignalExtractor()
        signals = extractor.extract(path)
        assert signals.file_type == "application/pdf"
        assert signals.page_count >= 1


class TestTableFormulaFixture:
    """Test the table_formula.pdf fixture."""

    def test_table_formula_fixture_exists(self, tmp_path: Path) -> None:
        """table_formula.pdf can be built and is a valid PDF."""
        path = tmp_path / "table_formula.pdf"
        path.write_bytes(_build_table_formula_pdf())
        assert path.exists()
        assert path.stat().st_size > 0
        raw = path.read_bytes()
        assert raw.startswith(b"%PDF")

    def test_table_formula_fixture_has_table_content(self) -> None:
        """Table fixture has table-like structured content."""
        raw = _build_table_formula_pdf()
        assert b"Accuracy" in raw
        assert b"Dataset" in raw
        assert b"99.2%" in raw

    def test_table_formula_fixture_has_formula_content(self) -> None:
        """Table fixture has formula-like content."""
        raw = _build_table_formula_pdf()
        assert b"softmax" in raw
        assert b"gradient" in raw

    def test_table_formula_fixture_parses_successfully(self, tmp_path: Path) -> None:
        """table_formula.pdf can be processed by SignalExtractor."""
        from docos.pipeline.signal_extractor import SignalExtractor

        path = tmp_path / "table_formula.pdf"
        path.write_bytes(_build_table_formula_pdf())
        extractor = SignalExtractor()
        signals = extractor.extract(path)
        assert signals.file_type == "application/pdf"
        assert signals.page_count >= 1


class TestFixtureRegistry:
    """Test the fixture registry functions."""

    def test_get_all_fixtures_returns_four(self, tmp_path: Path) -> None:
        """get_all_fixtures() returns all four fixture types."""
        import tests.fixtures.build_fixtures as bf

        original_dir = bf.FIXTURES_DIR
        bf.FIXTURES_DIR = tmp_path
        try:
            fixtures = get_all_fixtures()
            assert len(fixtures) == 4
            assert "simple_text" in fixtures
            assert "dual_column_or_formula" in fixtures
            assert "ocr_like" in fixtures
            assert "table_formula" in fixtures
            for name, path in fixtures.items():
                assert path.exists(), f"Fixture {name} does not exist at {path}"
        finally:
            bf.FIXTURES_DIR = original_dir

    def test_all_fixtures_are_valid_pdfs(self, tmp_path: Path) -> None:
        """All fixtures start with %PDF header."""
        builders = {
            "simple_text": _build_simple_pdf,
            "dual_column_or_formula": _build_dual_column_pdf,
            "ocr_like": _build_ocr_like_pdf,
            "table_formula": _build_table_formula_pdf,
        }
        for name, builder in builders.items():
            raw = builder()
            assert raw.startswith(b"%PDF"), f"{name} should start with %PDF header"
            assert b"%%EOF" in raw, f"{name} should end with %%EOF marker"
