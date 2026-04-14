"""Tests for US-026: Add raw fixtures for simple, complex, and OCR-like inputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.build_fixtures import (
    FIXTURES_DIR,
    _build_dual_column_pdf,
    _build_ocr_like_pdf,
    _build_simple_pdf,
    get_all_fixtures,
    get_fixture,
)


class TestRawFixtures:
    """Verify that all three fixture categories exist and are valid PDFs."""

    def test_simple_text_fixture_exists(self, tmp_path: Path) -> None:
        """simple_text.pdf fixture can be built and exists."""
        path = tmp_path / "simple_text.pdf"
        path.write_bytes(_build_simple_pdf())
        assert path.exists()
        assert path.stat().st_size > 0
        raw = path.read_bytes()
        assert raw.startswith(b"%PDF")

    def test_dual_column_fixture_exists(self, tmp_path: Path) -> None:
        """dual_column_or_formula.pdf fixture can be built and exists."""
        path = tmp_path / "dual_column_or_formula.pdf"
        path.write_bytes(_build_dual_column_pdf())
        assert path.exists()
        assert path.stat().st_size > 0
        raw = path.read_bytes()
        assert raw.startswith(b"%PDF")

    def test_ocr_like_fixture_exists(self, tmp_path: Path) -> None:
        """ocr_like.pdf fixture can be built and exists."""
        path = tmp_path / "ocr_like.pdf"
        path.write_bytes(_build_ocr_like_pdf())
        assert path.exists()
        assert path.stat().st_size > 0
        raw = path.read_bytes()
        assert raw.startswith(b"%PDF")

    def test_simple_fixture_has_text_content(self, tmp_path: Path) -> None:
        """Simple fixture contains meaningful text content."""
        raw = _build_simple_pdf()
        # Verify text is present in the content stream
        assert b"Introduction" in raw
        assert b"pipeline" in raw

    def test_dual_column_fixture_has_two_columns(self, tmp_path: Path) -> None:
        """Dual-column fixture has text at both left and right x-coordinates."""
        raw = _build_dual_column_pdf()
        # Left column text near x=72
        assert b"Left Column" in raw
        # Right column text near x=320
        assert b"Right Column" in raw
        # Multiple Td positioning commands for dual-column layout
        assert b"320" in raw  # right column x offset

    def test_ocr_like_fixture_is_image_heavy(self, tmp_path: Path) -> None:
        """OCR-like fixture has many image streams."""
        raw = _build_ocr_like_pdf()
        # Should have 5 image streams
        assert raw.count(b"/Subtype /Image") >= 5
        # Minimal text
        assert b"Page 1" in raw

    def test_get_fixture_builds_and_returns_path(self, tmp_path: Path) -> None:
        """get_fixture() creates the file on first call and returns it."""
        import tests.fixtures.build_fixtures as bf

        # Override fixtures dir to tmp_path for isolation
        original_dir = bf.FIXTURES_DIR
        bf.FIXTURES_DIR = tmp_path
        try:
            path = get_fixture("simple_text")
            assert path.exists()
            assert path.name == "simple_text.pdf"

            # Second call returns same path (already exists)
            path2 = get_fixture("simple_text")
            assert path2 == path
        finally:
            bf.FIXTURES_DIR = original_dir

    def test_get_all_fixtures_returns_three(self, tmp_path: Path) -> None:
        """get_all_fixtures() returns all three fixture types."""
        import tests.fixtures.build_fixtures as bf

        original_dir = bf.FIXTURES_DIR
        bf.FIXTURES_DIR = tmp_path
        try:
            fixtures = get_all_fixtures()
            assert len(fixtures) == 3
            assert "simple_text" in fixtures
            assert "dual_column_or_formula" in fixtures
            assert "ocr_like" in fixtures
            for name, path in fixtures.items():
                assert path.exists(), f"Fixture {name} does not exist at {path}"
        finally:
            bf.FIXTURES_DIR = original_dir

    def test_get_fixture_unknown_raises(self, tmp_path: Path) -> None:
        """get_fixture() raises ValueError for unknown fixture name."""
        with pytest.raises(ValueError, match="Unknown fixture"):
            get_fixture("nonexistent")

    def test_fixtures_valid_for_signal_extraction(self, tmp_path: Path) -> None:
        """All fixtures can be processed by SignalExtractor without errors."""
        from docos.pipeline.signal_extractor import SignalExtractor

        extractor = SignalExtractor()

        for name, builder in [
            ("simple_text", _build_simple_pdf),
            ("dual_column_or_formula", _build_dual_column_pdf),
            ("ocr_like", _build_ocr_like_pdf),
        ]:
            path = tmp_path / f"{name}.pdf"
            path.write_bytes(builder())
            signals = extractor.extract(path)
            assert signals.file_type == "application/pdf", f"{name} should be detected as PDF"
            assert signals.page_count >= 1, f"{name} should have at least 1 page"
