"""Tests for US-013: Validate router config against runtime parser registry."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docos.models.config import AppConfig
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import ParserRouter


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_VALID_CONFIG_YAML = """
environment: local
schema_version: "1"
router:
  default_route: fallback_route
  routes:
    - name: primary_route
      file_types: ["application/pdf"]
      primary_parser: stdlib_pdf
      fallback_parsers: [basic_text_fallback]
      review_policy: default
    - name: fallback_route
      primary_parser: basic_text_fallback
      fallback_parsers: []
      review_policy: default
"""

_INVALID_CONFIG_YAML = """
environment: local
schema_version: "1"
router:
  default_route: bad_route
  routes:
    - name: bad_route
      primary_parser: nonexistent_parser
      fallback_parsers: [also_missing, yet_another]
      review_policy: default
"""

_MIXED_CONFIG_YAML = """
environment: local
schema_version: "1"
router:
  default_route: mixed_route
  routes:
    - name: mixed_route
      primary_parser: stdlib_pdf
      fallback_parsers: [missing_parser]
      review_policy: default
"""


def _make_registry() -> ParserRegistry:
    """Create a registry with the two built-in parsers."""
    reg = ParserRegistry()
    reg.register(StdlibPDFParser())
    reg.register(BasicTextFallbackParser())
    return reg


def _load_config(yaml_str: str) -> AppConfig:
    return AppConfig.model_validate(yaml.safe_load(yaml_str))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestValidateConfig:
    """US-013: Router validation checks parser names against the registry."""

    def test_valid_config_no_unresolved(self) -> None:
        """All parser names resolve — empty list returned."""
        config = _load_config(_VALID_CONFIG_YAML)
        registry = _make_registry()
        router = ParserRouter(config)

        unresolved = router.validate_config(registry)
        assert unresolved == []

    def test_valid_config_with_constructor_registry(self) -> None:
        """Registry passed at construction time is used when no arg given."""
        config = _load_config(_VALID_CONFIG_YAML)
        registry = _make_registry()
        router = ParserRouter(config, parser_registry=registry)

        unresolved = router.validate_config()
        assert unresolved == []

    def test_invalid_config_returns_unresolved(self) -> None:
        """Unknown parser names are returned as unresolved."""
        config = _load_config(_INVALID_CONFIG_YAML)
        registry = _make_registry()
        router = ParserRouter(config)

        unresolved = router.validate_config(registry)
        assert "nonexistent_parser" in unresolved
        assert "also_missing" in unresolved
        assert "yet_another" in unresolved
        assert len(unresolved) == 3

    def test_mixed_config_reports_only_missing(self) -> None:
        """Only truly unresolvable names are reported."""
        config = _load_config(_MIXED_CONFIG_YAML)
        registry = _make_registry()
        router = ParserRouter(config)

        unresolved = router.validate_config(registry)
        assert unresolved == ["missing_parser"]

    def test_no_registry_returns_empty(self) -> None:
        """Without a registry, validation is skipped (returns empty)."""
        config = _load_config(_INVALID_CONFIG_YAML)
        router = ParserRouter(config)

        unresolved = router.validate_config()
        assert unresolved == []

    def test_deduplication_across_routes(self) -> None:
        """Same missing name in multiple routes is reported only once."""
        dedup_yaml = """
        environment: local
        schema_version: "1"
        router:
          default_route: r1
          routes:
            - name: r1
              primary_parser: missing_x
              fallback_parsers: []
              review_policy: default
            - name: r2
              primary_parser: missing_x
              fallback_parsers: []
              review_policy: default
        """
        config = _load_config(dedup_yaml)
        registry = _make_registry()
        router = ParserRouter(config)

        unresolved = router.validate_config(registry)
        assert unresolved.count("missing_x") == 1
