"""Tests for US-016: Make formula-heavy signals influence route selection."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docos.models.config import AppConfig
from docos.models.source import SourceRecord
from docos.pipeline.router import DocumentSignals, ParserRouter


# ---------------------------------------------------------------------------
# Config with a formula-specific route
# ---------------------------------------------------------------------------

_FORMULA_CONFIG_YAML = """
environment: local
schema_version: "1"
router:
  default_route: text_route
  routes:
    - name: formula_route
      description: "Route for formula-heavy documents"
      file_types: ["application/pdf"]
      table_formula_heavy: true
      primary_parser: stdlib_pdf
      fallback_parsers: [basic_text_fallback]
      expected_risks: ["formula_fidelity"]
      review_policy: strict
    - name: text_route
      description: "Standard text route"
      file_types: ["application/pdf"]
      table_formula_heavy: false
      primary_parser: stdlib_pdf
      fallback_parsers: []
      expected_risks: []
      review_policy: default
"""


def _make_source() -> SourceRecord:
    return SourceRecord(source_id="src_test", source_hash="abc", file_name="test.pdf", byte_size=100)


def _load_config(yaml_str: str) -> AppConfig:
    return AppConfig.model_validate(yaml.safe_load(yaml_str))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFormulaHeavyScoring:
    """US-016: is_formula_heavy participates in route scoring."""

    def test_formula_heavy_selects_formula_route(self) -> None:
        """A formula-heavy document selects the formula route over the text route."""
        config = _load_config(_FORMULA_CONFIG_YAML)
        router = ParserRouter(config)
        source = _make_source()

        sigs = DocumentSignals(
            file_type="application/pdf",
            page_count=10,
            is_formula_heavy=True,
            is_table_heavy=False,
        )
        decision = router.route(source, sigs)
        assert decision.selected_route == "formula_route"
        assert decision.matched_signals.get("is_formula_heavy") is True

    def test_non_formula_selects_text_route(self) -> None:
        """A non-formula document selects the text route."""
        config = _load_config(_FORMULA_CONFIG_YAML)
        router = ParserRouter(config)
        source = _make_source()

        sigs = DocumentSignals(
            file_type="application/pdf",
            page_count=10,
            is_formula_heavy=False,
            is_table_heavy=False,
        )
        decision = router.route(source, sigs)
        assert decision.selected_route == "text_route"

    def test_formula_heavy_increases_score(self) -> None:
        """Formula-heavy signal adds scoring points for table_formula_heavy routes."""
        config = _load_config(_FORMULA_CONFIG_YAML)
        router = ParserRouter(config)

        # Build signals with formula-heavy
        sigs_formula = DocumentSignals(
            file_type="application/pdf",
            is_formula_heavy=True,
        )
        sigs_plain = DocumentSignals(
            file_type="application/pdf",
            is_formula_heavy=False,
        )

        formula_route = config.router.get_route("formula_route")
        assert formula_route is not None

        score_with_formula = router._score_route(formula_route, sigs_formula)
        score_without_formula = router._score_route(formula_route, sigs_plain)

        assert score_with_formula > score_without_formula

    def test_formula_heavy_logged_in_matched_signals(self) -> None:
        """Formula-heavy signal is recorded in the route log matched_signals."""
        config = _load_config(_FORMULA_CONFIG_YAML)
        router = ParserRouter(config)
        source = _make_source()

        sigs = DocumentSignals(
            file_type="application/pdf",
            is_formula_heavy=True,
        )
        decision = router.route(source, sigs)
        assert "is_formula_heavy" in decision.matched_signals
        assert decision.matched_signals["is_formula_heavy"] is True
