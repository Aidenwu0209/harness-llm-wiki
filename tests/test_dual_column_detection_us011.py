"""Tests for US-011: Implement real dual-column detection.

Verifies:
- Dual-column detection returns real signal values (not constant false)
- Dual-column fixture produces is_dual_column=True
- Single-column fixture produces is_dual_column=False
- Route log stores the detected dual-column value
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from docos.models.config import AppConfig
from docos.models.source import SourceRecord, SourceStatus
from docos.pipeline.router import DocumentSignals, ParserRouter
from docos.pipeline.signal_extractor import SignalExtractor


def _write_single_column_pdf(path: Path) -> Path:
    """Single-column PDF with text at one x-position."""
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 180 >>\nstream\n"
        b"BT /F1 12 Tf 72 700 Td (Title) Tj ET\n"
        b"BT /F1 10 Tf 72 680 Td (Single column text line one.) Tj ET\n"
        b"BT /F1 10 Tf 72 660 Td (Single column text line two.) Tj ET\n"
        b"BT /F1 10 Tf 72 640 Td (Single column text line three.) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _write_dual_column_pdf(path: Path) -> Path:
    """Dual-column PDF with text at two distinct x-positions."""
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 400 >>\nstream\n"
        b"BT /F1 10 Tf 72 700 Td (Left column one.) Tj ET\n"
        b"BT /F1 10 Tf 72 680 Td (Left column two.) Tj ET\n"
        b"BT /F1 10 Tf 72 660 Td (Left column three.) Tj ET\n"
        b"BT /F1 10 Tf 320 700 Td (Right column one.) Tj ET\n"
        b"BT /F1 10 Tf 320 680 Td (Right column two.) Tj ET\n"
        b"BT /F1 10 Tf 320 660 Td (Right column three.) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _make_config() -> AppConfig:
    """Create a minimal config for route testing."""
    config_yaml = (
        "environment: local\nschema_version: '1'\n"
        "router:\n  default_route: test_route\n  routes:\n"
        "    - name: test_route\n      description: 'test'\n"
        "      file_types: ['application/pdf']\n"
        "      primary_parser: stdlib_pdf\n      fallback_parsers: [basic_text_fallback]\n"
        "      expected_risks: []\n      post_parse_repairs: []\n"
        "      review_policy: default\n"
        "      dual_column: null\n"
        "risk_thresholds:\n  high_risk_score: 0.7\n  medium_risk_score: 0.4\n"
        "  high_blast_pages: 5\n  high_blast_claims: 10\n  high_blast_links: 15\n"
        "  auto_merge_max_risk: 0.3\n  auto_merge_max_pages: 3\n"
        "release_gates:\n  block_on_p0_lint: true\n  block_on_p1_lint: true\n"
        "  block_on_unsupported_claim_increase: true\n  block_on_missing_harness: true\n"
        "  block_on_regression_exceeded: true\n  block_on_fallback_low_confidence: true\n"
        "  fallback_confidence_threshold: 0.5\n"
        "  regression_max_claim_change_pct: 10.0\n  regression_max_link_break_count: 0\n"
        "review_policies:\n  default_policy: default\n  policies:\n"
        "    - name: default\n      description: 'test'\n"
        "      require_review_on_fallback: true\n      require_review_on_high_risk: true\n"
        "      require_review_on_high_blast: true\n      require_review_on_conflict: true\n"
        "      require_review_on_entity_merge: true\n"
        "      auto_assign_reviewer: false\n      min_reviewers: 1\n"
        "lint_policy:\n  p0_blocks_merge: true\n  p1_blocks_merge: true\n"
    )
    return AppConfig.model_validate(yaml.safe_load(config_yaml))


def _make_source(source_id: str = "src_test") -> SourceRecord:
    """Create a minimal source record."""
    return SourceRecord(
        source_id=source_id,
        source_hash="a" * 64,
        file_name="test.pdf",
        mime_type="application/pdf",
        byte_size=100,
        status=SourceStatus.UPLOADED,
    )


class TestDualColumnDetection:
    """US-011: Real dual-column detection produces meaningful signal values."""

    def test_dual_column_fixture_returns_true(self, tmp_path: Path) -> None:
        """Dual-column fixture produces is_dual_column=True."""
        pdf_path = _write_dual_column_pdf(tmp_path / "dual.pdf")
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)
        assert signals.is_dual_column is True

    def test_single_column_fixture_returns_false(self, tmp_path: Path) -> None:
        """Single-column fixture produces is_dual_column=False."""
        pdf_path = _write_single_column_pdf(tmp_path / "single.pdf")
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)
        assert signals.is_dual_column is False

    def test_detection_is_not_constant_false(self, tmp_path: Path) -> None:
        """Dual-column detection returns different values for different inputs."""
        dual_path = _write_dual_column_pdf(tmp_path / "dual.pdf")
        single_path = _write_single_column_pdf(tmp_path / "single.pdf")

        dual_signals = SignalExtractor().extract(dual_path)
        single_signals = SignalExtractor().extract(single_path)

        # Must produce different results
        assert dual_signals.is_dual_column != single_signals.is_dual_column
        assert dual_signals.is_dual_column is True
        assert single_signals.is_dual_column is False

    def test_route_log_stores_dual_column_value(self, tmp_path: Path) -> None:
        """Route log stores the detected dual-column value."""
        pdf_path = _write_dual_column_pdf(tmp_path / "dual.pdf")
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)

        config = _make_config()
        source = _make_source()
        log_dir = tmp_path / "route_logs"
        router = ParserRouter(config, log_dir=log_dir)
        decision = router.route(source, signals)

        # Check the route log file contains is_dual_column
        log_path = log_dir / f"route_{source.source_id}.json"
        assert log_path.exists()
        log_data = json.loads(log_path.read_text())
        assert "signals" in log_data
        assert log_data["signals"]["is_dual_column"] is True

    def test_route_log_stores_false_for_single_column(self, tmp_path: Path) -> None:
        """Route log stores is_dual_column=False for single-column document."""
        pdf_path = _write_single_column_pdf(tmp_path / "single.pdf")
        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)

        config = _make_config()
        source = _make_source("src_single")
        log_dir = tmp_path / "route_logs"
        router = ParserRouter(config, log_dir=log_dir)
        decision = router.route(source, signals)

        log_path = log_dir / f"route_{source.source_id}.json"
        log_data = json.loads(log_path.read_text())
        assert log_data["signals"]["is_dual_column"] is False
