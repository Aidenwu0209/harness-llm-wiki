"""Tests for US-017: Define max_pages and signal logging semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from docos.models.config import AppConfig
from docos.models.source import SourceRecord
from docos.pipeline.router import DocumentSignals, ParserRouter


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

_TEST_CONFIG_YAML = """
environment: local
schema_version: "1"
router:
  default_route: fallback
  routes:
    - name: short_route
      description: "Route for short documents"
      file_types: ["application/pdf"]
      max_pages: 10
      primary_parser: stdlib_pdf
      fallback_parsers: []
      review_policy: default
    - name: long_route
      description: "Route for long documents"
      file_types: ["application/pdf"]
      max_pages: 1000
      primary_parser: stdlib_pdf
      fallback_parsers: []
      review_policy: default
    - name: fallback
      description: "Fallback route"
      file_types: ["application/pdf"]
      primary_parser: stdlib_pdf
      fallback_parsers: []
      review_policy: default
"""


def _load_config() -> AppConfig:
    return AppConfig.model_validate(yaml.safe_load(_TEST_CONFIG_YAML))


def _make_source(sid: str = "src_test") -> SourceRecord:
    return SourceRecord(source_id=sid, source_hash="abc", file_name="test.pdf", byte_size=100)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMaxPagesSemantics:
    """US-017: max_pages is a soft score, not a hard filter."""

    def test_max_pages_is_soft_score_not_hard_filter(self) -> None:
        """A document exceeding max_pages still selects the route (just no bonus point)."""
        config = _load_config()
        router = ParserRouter(config)
        source = _make_source()

        # 50 pages exceeds short_route's max_pages=10, but the route is still
        # selectable — it just doesn't get the max_pages bonus point.
        sigs = DocumentSignals(file_type="application/pdf", page_count=50)
        decision = router.route(source, sigs)
        assert decision.selected_route != ""  # still selects a route

    def test_max_pages_within_limit_scores_higher(self) -> None:
        """A document within max_pages scores higher on that route."""
        config = _load_config()
        router = ParserRouter(config)

        short_route = config.router.get_route("short_route")
        assert short_route is not None

        sigs_within = DocumentSignals(file_type="application/pdf", page_count=5)
        sigs_exceed = DocumentSignals(file_type="application/pdf", page_count=50)

        score_within = router._score_route(short_route, sigs_within)
        score_exceed = router._score_route(short_route, sigs_exceed)
        assert score_within > score_exceed


class TestSignalLogging:
    """US-017: Route logs include all key signals."""

    @pytest.fixture()
    def router(self, tmp_path: Path) -> ParserRouter:
        config = _load_config()
        return ParserRouter(config, log_dir=tmp_path / "route_logs")

    def test_all_signals_in_matched_signals(self, router: ParserRouter) -> None:
        """All key signals appear in matched_signals of the decision."""
        source = _make_source()
        sigs = DocumentSignals(
            file_type="application/pdf",
            page_count=10,
            needs_ocr=True,
            is_scanned=True,
            is_dual_column=True,
            is_table_heavy=True,
            is_formula_heavy=True,
            is_image_heavy=True,
        )
        decision = router.route(source, sigs)

        # All key signals must be present
        expected_keys = [
            "file_type",
            "page_count",
            "needs_ocr",
            "is_scanned",
            "is_dual_column",
            "is_table_heavy",
            "is_formula_heavy",
            "is_image_heavy",
        ]
        for key in expected_keys:
            assert key in decision.matched_signals, f"Missing signal: {key}"

    def test_signals_present_even_when_false(self, router: ParserRouter) -> None:
        """Signals are logged even when their values are False/None."""
        source = _make_source()
        sigs = DocumentSignals(
            file_type="application/pdf",
            page_count=5,
            needs_ocr=False,
            is_scanned=False,
            is_dual_column=False,
            is_table_heavy=False,
            is_formula_heavy=False,
            is_image_heavy=False,
        )
        decision = router.route(source, sigs)

        # All keys must exist, even with False/None values
        assert "file_type" in decision.matched_signals
        assert "page_count" in decision.matched_signals
        assert "needs_ocr" in decision.matched_signals
        assert "is_scanned" in decision.matched_signals
        assert "is_dual_column" in decision.matched_signals
        assert "is_table_heavy" in decision.matched_signals
        assert "is_formula_heavy" in decision.matched_signals
        assert "is_image_heavy" in decision.matched_signals

    def test_persisted_log_includes_signals_section(self, router: ParserRouter, tmp_path: Path) -> None:
        """Persisted JSON log includes a signals section with all key signals."""
        source = _make_source()
        sigs = DocumentSignals(
            file_type="application/pdf",
            page_count=20,
            needs_ocr=True,
            is_scanned=False,
            is_dual_column=True,
            is_table_heavy=True,
            is_formula_heavy=True,
            is_image_heavy=False,
        )
        router.route(source, sigs)

        log_path = tmp_path / "route_logs" / f"route_{source.source_id}.json"
        assert log_path.exists()
        data = json.loads(log_path.read_text(encoding="utf-8"))

        assert "signals" in data
        signals = data["signals"]
        expected = [
            "file_type",
            "page_count",
            "needs_ocr",
            "is_scanned",
            "is_dual_column",
            "is_table_heavy",
            "is_formula_heavy",
            "is_image_heavy",
        ]
        for key in expected:
            assert key in signals, f"Missing signal in log: {key}"

        assert signals["file_type"] == "application/pdf"
        assert signals["page_count"] == 20
        assert signals["needs_ocr"] is True
        assert signals["is_dual_column"] is True
        assert signals["is_formula_heavy"] is True
