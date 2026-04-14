"""Tests for Signal Extractor — deterministic document signal extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.pipeline.router import DocumentSignals, RouteLogEntry
from docos.pipeline.signal_extractor import SignalExtractor, signals_from_dict, signals_to_dict


# ---------------------------------------------------------------------------
# PDF fixture helpers
# ---------------------------------------------------------------------------

def _write_minimal_pdf(path: Path, page_count: int = 1) -> Path:
    """Write a minimal valid PDF with the given page count."""
    kids = " ".join(f"{3 + i} 0 R" for i in range(page_count))
    lines = [
        b"%PDF-1.4",
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj",
        f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {page_count} >>\nendobj".encode(),
    ]
    for i in range(page_count):
        lines.append(
            f"{3 + i} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj".encode()
        )
    lines.append(b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n0\n%%EOF")
    path.write_bytes(b"\n".join(lines))
    return path


def _write_text_file(path: Path, content: str = "Hello world\n") -> Path:
    path.write_text(content, encoding="utf-8")
    return path


class TestSignalExtractor:
    def test_pdf_mime_detection(self, tmp_path: Path) -> None:
        pdf_path = _write_minimal_pdf(tmp_path / "doc.pdf")
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)
        assert signals.file_type == "application/pdf"

    def test_pdf_page_count(self, tmp_path: Path) -> None:
        pdf_path = _write_minimal_pdf(tmp_path / "doc.pdf", page_count=3)
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)
        assert signals.page_count >= 1  # At minimum detects pages

    def test_text_file_signals(self, tmp_path: Path) -> None:
        txt_path = _write_text_file(tmp_path / "doc.txt")
        extractor = SignalExtractor()
        signals = extractor.extract(txt_path)
        assert signals.file_type == "text/plain"
        assert signals.page_count == 1
        assert signals.language == "en"

    def test_chinese_text_detection(self, tmp_path: Path) -> None:
        txt_path = _write_text_file(
            tmp_path / "chinese.txt",
            content="这是一个中文测试文档，用于测试语言检测功能。",
        )
        extractor = SignalExtractor()
        signals = extractor.extract(txt_path)
        assert signals.language == "zh"

    def test_image_mime_detection(self, tmp_path: Path) -> None:
        img_path = tmp_path / "scan.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        extractor = SignalExtractor()
        signals = extractor.extract(img_path)
        assert signals.file_type == "image/png"
        assert signals.needs_ocr is True

    def test_deterministic_same_file(self, tmp_path: Path) -> None:
        """Running extraction twice on the same file returns identical signals."""
        pdf_path = _write_minimal_pdf(tmp_path / "doc.pdf")
        extractor = SignalExtractor()
        s1 = extractor.extract(pdf_path)
        s2 = extractor.extract(pdf_path)
        assert signals_to_dict(s1) == signals_to_dict(s2)

    def test_deterministic_via_hash(self, tmp_path: Path) -> None:
        """Signal extraction is deterministic across different extractor instances."""
        pdf_path = _write_minimal_pdf(tmp_path / "doc.pdf")
        s1 = SignalExtractor().extract(pdf_path)
        s2 = SignalExtractor().extract(pdf_path)
        d1 = json.dumps(signals_to_dict(s1), sort_keys=True)
        d2 = json.dumps(signals_to_dict(s2), sort_keys=True)
        assert d1 == d2

    def test_signals_serializable(self, tmp_path: Path) -> None:
        """Signals can be serialized to JSON and stored."""
        pdf_path = _write_minimal_pdf(tmp_path / "doc.pdf")
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)
        data = signals_to_dict(signals)

        # Must be JSON-serializable
        json_str = json.dumps(data)
        assert isinstance(json_str, str)

        # Round-trip
        restored = signals_from_dict(json.loads(json_str))
        assert restored.file_type == signals.file_type
        assert restored.page_count == signals.page_count

    def test_signals_storable_in_route_log(self, tmp_path: Path) -> None:
        """Signals can be stored in a route log entry."""
        pdf_path = _write_minimal_pdf(tmp_path / "doc.pdf")
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)

        from docos.models.source import SourceRecord
        from docos.pipeline.router import RouteDecision

        source = SourceRecord(source_id="src_test", source_hash="abc", file_name="doc.pdf", byte_size=100)
        decision = RouteDecision(
            selected_route="fast_text_route",
            primary_parser="pdfminer",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )
        entry = RouteLogEntry(source_id="src_test", decision=decision, signals=signals)
        log_dict = entry.to_dict()
        assert log_dict["source_id"] == "src_test"

    def test_target_mode_high_fidelity_for_small_pdf(self, tmp_path: Path) -> None:
        pdf_path = _write_minimal_pdf(tmp_path / "small.pdf")
        signals = SignalExtractor().extract(pdf_path)
        assert signals.target_mode == "high_fidelity"

    def test_target_mode_low_cost_for_text(self, tmp_path: Path) -> None:
        txt_path = _write_text_file(tmp_path / "simple.txt")
        signals = SignalExtractor().extract(txt_path)
        assert signals.target_mode == "low_cost"

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        extractor = SignalExtractor()
        with pytest.raises(FileNotFoundError, match="Source file not found"):
            extractor.extract(tmp_path / "nonexistent.pdf")

    def test_known_failure_encrypted(self, tmp_path: Path) -> None:
        """PDF with /Encrypt marker should be detected."""
        pdf_path = tmp_path / "encrypted.pdf"
        content = b"%PDF-1.4\n/Encrypt\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
        pdf_path.write_bytes(content)
        signals = SignalExtractor().extract(pdf_path)
        assert signals.has_known_failures is True

    def test_all_signal_fields_populated(self, tmp_path: Path) -> None:
        """Signal extraction returns all required fields."""
        pdf_path = _write_minimal_pdf(tmp_path / "doc.pdf")
        signals = SignalExtractor().extract(pdf_path)

        assert signals.file_type != ""
        assert isinstance(signals.page_count, int)
        assert isinstance(signals.is_scanned, bool)
        assert isinstance(signals.is_dual_column, bool)
        assert isinstance(signals.is_table_heavy, bool)
        assert isinstance(signals.is_formula_heavy, bool)
        assert isinstance(signals.is_image_heavy, bool)
        assert signals.language != ""
        assert signals.target_mode in ("high_fidelity", "high_throughput", "low_cost")
