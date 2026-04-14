"""Test fixtures — raw PDF inputs for integration tests.

Three fixture categories exercise the main route families:

- simple_text.pdf: Text-heavy, single-column, simple layout → fast_text_route
- dual_column_or_formula.pdf: Two-column layout with text → complex_pdf_route
- ocr_like.pdf: Image-heavy, minimal text → ocr_heavy_route
"""

from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def _build_simple_pdf() -> bytes:
    """Create a minimal valid PDF with single-column text content."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 200 >>\nstream\n"
        b"BT /F1 18 Tf 100 700 Td (Introduction to Document Processing) Tj ET\n"
        b"BT /F1 12 Tf 100 670 Td (This document describes the DocOS pipeline for parsing documents.) Tj ET\n"
        b"BT /F1 12 Tf 100 650 Td (The pipeline handles routing, parsing, normalization, and extraction.) Tj ET\n"
        b"BT /F1 12 Tf 100 630 Td (Each stage produces durable artifacts for audit and traceability.) Tj ET\n"
        b"BT /F1 12 Tf 100 610 Td (Quality is enforced through lint checks and harness evaluation.) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )


def _build_dual_column_pdf() -> bytes:
    """Create a PDF with two columns of text (dual-column layout signals)."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 600 >>\nstream\n"
        # Left column text
        b"BT /F1 14 Tf 72 700 Td (Left Column Title) Tj ET\n"
        b"BT /F1 10 Tf 72 680 Td (First paragraph in the left column.) Tj ET\n"
        b"BT /F1 10 Tf 72 660 Td (Second paragraph in the left column.) Tj ET\n"
        b"BT /F1 10 Tf 72 640 Td (Third paragraph in the left column.) Tj ET\n"
        b"BT /F1 10 Tf 72 620 Td (Fourth paragraph in the left column.) Tj ET\n"
        # Right column text (x offset ~320)
        b"BT /F1 14 Tf 320 700 Td (Right Column Title) Tj ET\n"
        b"BT /F1 10 Tf 320 680 Td (First paragraph in the right column.) Tj ET\n"
        b"BT /F1 10 Tf 320 660 Td (Second paragraph in the right column.) Tj ET\n"
        b"BT /F1 10 Tf 320 640 Td (Third paragraph in the right column.) Tj ET\n"
        b"BT /F1 10 Tf 320 620 Td (Fourth paragraph in the right column.) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )


def _build_ocr_like_pdf() -> bytes:
    """Create an image-heavy PDF with minimal text (OCR-priority signals)."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R\n"
        b"   /Resources << /XObject << /Im1 5 0 R /Im2 6 0 R /Im3 7 0 R /Im4 8 0 R /Im5 9 0 R >> >> >>\n"
        b"endobj\n"
        b"4 0 obj\n<< /Length 120 >>\nstream\n"
        b"BT /F1 10 Tf 100 750 Td (Page 1) Tj ET\n"
        b"/Im1 Do\n"
        b"/Im2 Do\n"
        b"/Im3 Do\n"
        b"/Im4 Do\n"
        b"/Im5 Do\n"
        b"endstream\nendobj\n"
        # Image objects (minimal valid image streams)
        b"5 0 obj\n<< /Type /XObject /Subtype /Image /Width 100 /Height 100 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 30000 >>\nstream\n"
        + b"\x00" * 30000 +
        b"\nendstream\nendobj\n"
        b"6 0 obj\n<< /Type /XObject /Subtype /Image /Width 100 /Height 100 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 30000 >>\nstream\n"
        + b"\x00" * 30000 +
        b"\nendstream\nendobj\n"
        b"7 0 obj\n<< /Type /XObject /Subtype /Image /Width 100 /Height 100 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 30000 >>\nstream\n"
        + b"\x00" * 30000 +
        b"\nendstream\nendobj\n"
        b"8 0 obj\n<< /Type /XObject /Subtype /Image /Width 100 /Height 100 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 30000 >>\nstream\n"
        + b"\x00" * 30000 +
        b"\nendstream\nendobj\n"
        b"9 0 obj\n<< /Type /XObject /Subtype /Image /Width 100 /Height 100 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 30000 >>\nstream\n"
        + b"\x00" * 30000 +
        b"\nendstream\nendobj\n"
        b"trailer\n<< /Size 10 /Root 1 0 R >>\n%%EOF"
    )


def _build_table_formula_pdf() -> bytes:
    """Create a PDF with table and formula content (table/formula-heavy signals)."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 500 >>\nstream\n"
        b"BT /F1 18 Tf 100 700 Td (Benchmark Results for Alpha Model) Tj ET\n"
        b"BT /F1 12 Tf 100 670 Td (Table 1: Performance comparison across datasets) Tj ET\n"
        # Table-like content
        b"BT /F1 10 Tf 72 640 Td (Dataset     Accuracy   F1-Score   Latency) Tj ET\n"
        b"BT /F1 10 Tf 72 620 Td (MNIST        99.2%      0.991      12ms) Tj ET\n"
        b"BT /F1 10 Tf 72 600 Td (CIFAR-10     95.7%      0.956      45ms) Tj ET\n"
        b"BT /F1 10 Tf 72 580 Td (ImageNet     82.3%      0.821      120ms) Tj ET\n"
        # Formula-like content
        b"BT /F1 12 Tf 100 540 Td (The loss function is: L = -sum(y_i * log(p_i))) Tj ET\n"
        b"BT /F1 12 Tf 100 510 Td (Gradient update: theta = theta - alpha * gradient) Tj ET\n"
        b"BT /F1 12 Tf 100 480 Td (The attention mechanism uses softmax(QK^T / sqrt(d))) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )


def get_fixture(name: str) -> Path:
    """Get a fixture file path, building it if necessary.

    Supported names: simple_text, dual_column_or_formula, ocr_like
    """
    builders = {
        "simple_text": _build_simple_pdf,
        "dual_column_or_formula": _build_dual_column_pdf,
        "ocr_like": _build_ocr_like_pdf,
        "table_formula": _build_table_formula_pdf,
    }
    if name not in builders:
        msg = f"Unknown fixture: {name}. Available: {list(builders.keys())}"
        raise ValueError(msg)

    path = FIXTURES_DIR / f"{name}.pdf"
    if not path.exists():
        path.write_bytes(builders[name]())
    return path


def get_all_fixtures() -> dict[str, Path]:
    """Get all fixture file paths, building them if necessary."""
    return {name: get_fixture(name) for name in ["simple_text", "dual_column_or_formula", "ocr_like", "table_formula"]}
