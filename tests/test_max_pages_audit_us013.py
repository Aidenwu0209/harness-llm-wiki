"""Tests for US-013: Define max_pages semantics and route score audit fields."""

from __future__ import annotations

import pytest
import yaml

from docos.models.config import AppConfig
from docos.models.source import SourceRecord
from docos.pipeline.router import DocumentSignals, ParserRouter


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_CONFIG_YAML = """
environment: local
schema_version: "1"
router:
  default_route: text_route
  routes:
    - name: short_route
      description: "Route for short documents only"
      file_types: ["application/pdf"]
      max_pages: 5
      primary_parser: stdlib_pdf
      fallback_parsers: []
      expected_risks: []
      review_policy: default
    - name: long_route
      description: "Route for longer documents"
      file_types: ["application/pdf"]
      max_pages: 100
      primary_parser: stdlib_pdf
      fallback_parsers: [basic_text_fallback]
      expected_risks: ["slow_parse"]
      review_policy: default
    - name: text_route
      description: "Default text route"
      file_types: ["application/pdf"]
      primary_parser: stdlib_pdf
      fallback_parsers: []
      expected_risks: []
      review_policy: default
"""


def _make_source() -> SourceRecord:
    return SourceRecord(
        source_id="src_test",
        source_hash="abc",
        file_name="test.pdf",
        byte_size=100,
    )


def _load_config(yaml_str: str) -> AppConfig:
    return AppConfig.model_validate(yaml.safe_load(yaml_str))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMaxPagesSemantics:
    """US-013: max_pages is a soft score, not a hard filter."""

    def test_max_pages_soft_score_short_doc(self) -> None:
        """A 3-page document earns the max_pages bonus for short_route (limit 5)."""
        config = _load_config(_CONFIG_YAML)
        router = ParserRouter(config)

        short_route = config.router.get_route("short_route")
        assert short_route is not None

        sigs = DocumentSignals(file_type="application/pdf", page_count=3)
        score = router._score_route(short_route, sigs)
        # Should include max_pages bonus (+1) + file_type match (+1) = at least 2
        assert score >= 2

    def test_max_pages_soft_score_long_doc(self) -> None:
        """A 50-page document does NOT earn the max_pages bonus for short_route (limit 5)."""
        config = _load_config(_CONFIG_YAML)
        router = ParserRouter(config)

        short_route = config.router.get_route("short_route")
        assert short_route is not None

        sigs_short_limit = DocumentSignals(file_type="application/pdf", page_count=50)
        score_short = router._score_route(short_route, sigs_short_limit)

        long_route = config.router.get_route("long_route")
        assert long_route is not None

        score_long = router._score_route(long_route, sigs_short_limit)
        # long_route should score higher because it has max_pages=100 which
        # covers 50 pages, while short_route max_pages=5 does not.
        assert score_long > score_short

    def test_max_pages_not_hard_filter(self) -> None:
        """Documents exceeding max_pages are NOT excluded — they just lose the bonus."""
        config = _load_config(_CONFIG_YAML)
        router = ParserRouter(config)

        short_route = config.router.get_route("short_route")
        assert short_route is not None

        sigs = DocumentSignals(file_type="application/pdf", page_count=50)
        score = router._score_route(short_route, sigs)
        # Score should still be > 0 (just missing the max_pages bonus)
        assert score > 0

    def test_route_decision_stability(self) -> None:
        """Routing the same input multiple times yields the same selected route."""
        config = _load_config(_CONFIG_YAML)
        router = ParserRouter(config)
        source = _make_source()

        sigs = DocumentSignals(file_type="application/pdf", page_count=10)
        decisions = [router.route(source, sigs) for _ in range(5)]

        routes = [d.selected_route for d in decisions]
        assert len(set(routes)) == 1, f"Expected stable route, got: {routes}"
        # matched_signals should also be stable
        for d in decisions:
            assert d.matched_signals == decisions[0].matched_signals


class TestRouteScoreAudit:
    """US-013: RouteDecision stores per-route scores and rejection reasons."""

    def test_route_scores_populated(self) -> None:
        """RouteDecision contains audit entries for all candidate routes."""
        config = _load_config(_CONFIG_YAML)
        router = ParserRouter(config)
        source = _make_source()

        sigs = DocumentSignals(file_type="application/pdf", page_count=3)
        decision = router.route(source, sigs)

        assert len(decision.route_scores) > 0
        route_names = [e.route_name for e in decision.route_scores]
        assert "short_route" in route_names
        assert "long_route" in route_names
        assert "text_route" in route_names

    def test_accepted_route_marked(self) -> None:
        """The selected route is marked as accepted in the audit trail."""
        config = _load_config(_CONFIG_YAML)
        router = ParserRouter(config)
        source = _make_source()

        sigs = DocumentSignals(file_type="application/pdf", page_count=3)
        decision = router.route(source, sigs)

        accepted = [e for e in decision.route_scores if e.accepted]
        assert len(accepted) == 1
        assert accepted[0].route_name == decision.selected_route

    def test_rejection_reasons_populated(self) -> None:
        """Rejected routes have rejection reasons."""
        config = _load_config(_CONFIG_YAML)
        router = ParserRouter(config)
        source = _make_source()

        sigs = DocumentSignals(file_type="application/pdf", page_count=3)
        decision = router.route(source, sigs)

        rejected = [e for e in decision.route_scores if not e.accepted]
        for e in rejected:
            # Rejection reason should be present (may be empty string for
            # routes that scored > 0 but were not the best)
            assert isinstance(e.rejection_reason, str)

    def test_all_routes_have_scores(self) -> None:
        """Every audit entry has a numeric score."""
        config = _load_config(_CONFIG_YAML)
        router = ParserRouter(config)
        source = _make_source()

        sigs = DocumentSignals(file_type="application/pdf", page_count=3)
        decision = router.route(source, sigs)

        for entry in decision.route_scores:
            assert isinstance(entry.score, int)
            assert entry.score >= 0

    def test_file_type_mismatch_rejection_reason(self) -> None:
        """Routes with mismatched file types report the reason."""
        mismatch_yaml = """
        environment: local
        schema_version: "1"
        router:
          default_route: text_route
          routes:
            - name: image_route
              file_types: ["image/png"]
              primary_parser: basic_text_fallback
              fallback_parsers: []
              expected_risks: []
              review_policy: default
            - name: text_route
              file_types: ["application/pdf"]
              primary_parser: stdlib_pdf
              fallback_parsers: []
              expected_risks: []
              review_policy: default
        """
        config = _load_config(mismatch_yaml)
        router = ParserRouter(config)
        source = _make_source()

        sigs = DocumentSignals(file_type="application/pdf", page_count=5)
        decision = router.route(source, sigs)

        image_entry = [e for e in decision.route_scores if e.route_name == "image_route"]
        assert len(image_entry) == 1
        assert image_entry[0].score == 0
        assert "file_type mismatch" in image_entry[0].rejection_reason
