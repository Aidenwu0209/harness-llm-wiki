"""Tests for US-010: Choose and apply one parser alignment strategy.

Strategy selected: SHRINK-TO-IMPLEMENTED — router.yaml only references
parsers that are registered in the ParserRegistry at runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docos.models.config import AppConfig
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import ParserRouter


class TestParserAlignment:
    """US-010: Config and runtime parser capabilities are aligned."""

    def test_config_only_references_implemented_parsers(self) -> None:
        """router.yaml only references parsers that exist in the registry."""
        config_path = Path("configs/router.yaml")
        with open(config_path) as f:
            config = AppConfig.model_validate(yaml.safe_load(f))

        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        router = ParserRouter(config, parser_registry=registry)
        unresolved = router.validate_config()
        assert unresolved == [], (
            f"router.yaml references unimplemented parsers: {unresolved}. "
            f"Either implement the parser or remove it from config."
        )

    def test_implemented_parsers_in_registry(self) -> None:
        """All implemented parsers are registered and resolvable."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        assert registry.get("stdlib_pdf") is not None
        assert registry.get("basic_text_fallback") is not None

    def test_config_routes_resolve(self) -> None:
        """Every route in router.yaml resolves primary and fallback parsers."""
        config_path = Path("configs/router.yaml")
        with open(config_path) as f:
            config = AppConfig.model_validate(yaml.safe_load(f))

        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        for route in config.router.routes:
            primary = registry.get(route.primary_parser)
            assert primary is not None, (
                f"Route '{route.name}' has unresolved primary_parser '{route.primary_parser}'"
            )
            for fb in route.fallback_parsers:
                fb_parser = registry.get(fb)
                assert fb_parser is not None, (
                    f"Route '{route.name}' has unresolved fallback_parser '{fb}'"
                )

    def test_strategy_documented_in_config(self) -> None:
        """The SHRINK-TO-IMPLEMENTED strategy is documented in router.yaml."""
        config_path = Path("configs/router.yaml")
        content = config_path.read_text()
        assert "SHRINK-TO-IMPLEMENTED" in content, (
            "router.yaml must document the alignment strategy"
        )
        assert "stdlib_pdf" in content, (
            "router.yaml must list implemented parsers"
        )
        assert "basic_text_fallback" in content, (
            "router.yaml must list implemented parsers"
        )
