"""Tests for US-009: Fail fast when route config references unknown parsers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from docos.models.config import AppConfig
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import ParserRouter


def _make_config(config_dir: Path, parser_name: str, fallback: str = "") -> Path:
    """Create a config file with specified parser names."""
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "router.yaml"
    fallback_str = f"      fallback_parsers: [{fallback}]\n" if fallback else "      fallback_parsers: []\n"
    config_path.write_text(
        "environment: local\nschema_version: '1'\n"
        "router:\n  default_route: test_route\n  routes:\n"
        "    - name: test_route\n      description: 'test'\n"
        f"      file_types: ['application/pdf']\n"
        f"      primary_parser: {parser_name}\n"
        f"{fallback_str}"
        "      expected_risks: []\n      post_parse_repairs: []\n"
        "      review_policy: default\n"
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
    return config_path


def _make_registry() -> ParserRegistry:
    """Create a parser registry with standard parsers."""
    registry = ParserRegistry()
    registry.register(StdlibPDFParser())
    registry.register(BasicTextFallbackParser())
    return registry


class TestRouteConfigValidation:
    """US-009: Route config validation checks parser names resolve through ParserRegistry."""

    def test_valid_config_passes_validation(self, tmp_path: Path) -> None:
        """Valid config with known parsers passes validation."""
        config_path = _make_config(tmp_path, "stdlib_pdf", "basic_text_fallback")
        with open(config_path) as f:
            config = AppConfig.model_validate(yaml.safe_load(f))

        registry = _make_registry()
        router = ParserRouter(config, parser_registry=registry)
        unresolved = router.validate_config()
        assert unresolved == []

    def test_invalid_primary_parser_fails_validation(self, tmp_path: Path) -> None:
        """Unknown primary parser name produces clear validation failure."""
        config_path = _make_config(tmp_path, "nonexistent_parser")
        with open(config_path) as f:
            config = AppConfig.model_validate(yaml.safe_load(f))

        registry = _make_registry()
        router = ParserRouter(config, parser_registry=registry)
        unresolved = router.validate_config()
        assert "nonexistent_parser" in unresolved
        assert len(unresolved) >= 1

    def test_invalid_fallback_parser_fails_validation(self, tmp_path: Path) -> None:
        """Unknown fallback parser name produces clear validation failure."""
        config_path = _make_config(tmp_path, "stdlib_pdf", "missing_fallback")
        with open(config_path) as f:
            config = AppConfig.model_validate(yaml.safe_load(f))

        registry = _make_registry()
        router = ParserRouter(config, parser_registry=registry)
        unresolved = router.validate_config()
        assert "missing_fallback" in unresolved

    def test_mixed_valid_invalid_reports_only_invalid(self, tmp_path: Path) -> None:
        """Valid parser + invalid parser reports only the invalid one."""
        config_path = _make_config(tmp_path, "stdlib_pdf", "ghost_parser")
        with open(config_path) as f:
            config = AppConfig.model_validate(yaml.safe_load(f))

        registry = _make_registry()
        router = ParserRouter(config, parser_registry=registry)
        unresolved = router.validate_config()
        assert "stdlib_pdf" not in unresolved
        assert "ghost_parser" in unresolved

    def test_validation_failure_is_structured(self, tmp_path: Path) -> None:
        """Validation returns list of unresolved names for structured error handling."""
        config_path = _make_config(tmp_path, "bad1")
        with open(config_path) as f:
            config = AppConfig.model_validate(yaml.safe_load(f))

        registry = _make_registry()
        router = ParserRouter(config, parser_registry=registry)
        unresolved = router.validate_config()

        # Result is a list of strings (parser names)
        assert isinstance(unresolved, list)
        for name in unresolved:
            assert isinstance(name, str)

    def test_registered_parsers_match_config(self, tmp_path: Path) -> None:
        """All configured parsers in the default route resolve through registry."""
        config_path = _make_config(tmp_path, "stdlib_pdf", "basic_text_fallback")
        with open(config_path) as f:
            config = AppConfig.model_validate(yaml.safe_load(f))

        registry = _make_registry()

        # Verify each configured parser can be resolved
        for route in config.router.routes:
            primary = registry.get(route.primary_parser)
            assert primary is not None, f"Primary parser '{route.primary_parser}' not found"
            for fb in route.fallback_parsers:
                fb_parser = registry.get(fb)
                assert fb_parser is not None, f"Fallback parser '{fb}' not found"
