"""Tests for US-015: Implement real dual-column signal detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.pipeline.signal_extractor import SignalExtractor


# ---------------------------------------------------------------------------
# PDF fixture helpers
# ---------------------------------------------------------------------------

def _write_single_column_pdf(path: Path) -> Path:
    """Write a single-column PDF with text at roughly one x-position."""
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 180 >>\nstream\n"
        b"BT /F1 12 Tf 72 700 Td (Title line one) Tj ET\n"
        b"BT /F1 10 Tf 72 680 Td (This is paragraph text for single column.) Tj ET\n"
        b"BT /F1 10 Tf 72 660 Td (More text at same x-position.) Tj ET\n"
        b"BT /F1 10 Tf 72 640 Td (Another line in the single column layout.) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _write_dual_column_pdf(path: Path) -> Path:
    """Write a dual-column PDF with text at two distinct x-positions."""
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 400 >>\nstream\n"
        # Left column starting at x=72
        b"BT /F1 10 Tf 72 700 Td (Left column paragraph one.) Tj ET\n"
        b"BT /F1 10 Tf 72 680 Td (Left column paragraph two.) Tj ET\n"
        b"BT /F1 10 Tf 72 660 Td (Left column paragraph three.) Tj ET\n"
        # Right column starting at x=320 (large gap from 72)
        b"BT /F1 10 Tf 320 700 Td (Right column paragraph one.) Tj ET\n"
        b"BT /F1 10 Tf 320 680 Td (Right column paragraph two.) Tj ET\n"
        b"BT /F1 10 Tf 320 660 Td (Right column paragraph three.) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _write_minimal_pdf(path: Path) -> Path:
    """Write a minimal PDF without content stream text positioning."""
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDualColumnDetection:
    """US-015: Real dual-column signal detection."""

    def test_dual_column_pdf_detected(self, tmp_path: Path) -> None:
        """PDF with two distinct column positions is detected as dual-column."""
        pdf_path = _write_dual_column_pdf(tmp_path / "dual.pdf")
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)
        assert signals.is_dual_column is True

    def test_single_column_pdf_not_detected(self, tmp_path: Path) -> None:
        """PDF with text at a single x-position is not dual-column."""
        pdf_path = _write_single_column_pdf(tmp_path / "single.pdf")
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)
        assert signals.is_dual_column is False

    def test_minimal_pdf_not_detected(self, tmp_path: Path) -> None:
        """Minimal PDF without content streams is not dual-column."""
        pdf_path = _write_minimal_pdf(tmp_path / "minimal.pdf")
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)
        assert signals.is_dual_column is False

    def test_non_pdf_not_dual_column(self, tmp_path: Path) -> None:
        """Non-PDF files are never dual-column."""
        txt_path = tmp_path / "doc.txt"
        txt_path.write_text("Some text", encoding="utf-8")
        extractor = SignalExtractor()
        signals = extractor.extract(txt_path)
        assert signals.is_dual_column is False

    def test_deterministic_dual_column(self, tmp_path: Path) -> None:
        """Dual-column detection is deterministic across runs."""
        pdf_path = _write_dual_column_pdf(tmp_path / "dual.pdf")
        s1 = SignalExtractor().extract(pdf_path)
        s2 = SignalExtractor().extract(pdf_path)
        assert s1.is_dual_column == s2.is_dual_column
