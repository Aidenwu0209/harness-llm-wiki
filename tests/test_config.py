"""Tests for externalized configuration."""

import pytest
import yaml
from pathlib import Path

from docos.models.config import (
    AppConfig,
    Environment,
    ParserRoute,
    ReleaseGates,
    ReviewPolicies,
    RiskThresholds,
    RouterConfig,
)

CONFIGS_DIR = Path(__file__).parent.parent / "configs"


class TestParserRoute:
    def test_minimal_route(self) -> None:
        r = ParserRoute(name="test_route", primary_parser="pymupdf")
        assert r.name == "test_route"
        assert r.fallback_parsers == []

    def test_route_with_criteria(self) -> None:
        r = ParserRoute(
            name="complex_pdf_route",
            primary_parser="marker",
            fallback_parsers=["pymupdf", "pdfplumber"],
            file_types=["application/pdf"],
            table_formula_heavy=True,
            dual_column=True,
        )
        assert r.fallback_parsers == ["pymupdf", "pdfplumber"]
        assert r.table_formula_heavy is True


class TestRouterConfig:
    def test_get_route_found(self) -> None:
        rc = RouterConfig(
            routes=[
                ParserRoute(name="route_a", primary_parser="p1"),
                ParserRoute(name="route_b", primary_parser="p2"),
            ]
        )
        assert rc.get_route("route_a") is not None
        assert rc.get_route("route_a").primary_parser == "p1"

    def test_get_route_not_found(self) -> None:
        rc = RouterConfig(routes=[])
        assert rc.get_route("nonexistent") is None


class TestRiskThresholds:
    def test_defaults(self) -> None:
        rt = RiskThresholds()
        assert rt.high_risk_score == 0.7
        assert rt.auto_merge_max_risk == 0.3

    def test_custom(self) -> None:
        rt = RiskThresholds(high_risk_score=0.8, auto_merge_max_risk=0.2)
        assert rt.high_risk_score == 0.8


class TestReleaseGates:
    def test_all_gates_on_by_default(self) -> None:
        rg = ReleaseGates()
        assert rg.block_on_p0_lint is True
        assert rg.block_on_p1_lint is True
        assert rg.block_on_missing_harness is True


class TestReviewPolicies:
    def test_get_policy(self) -> None:
        rp = ReviewPolicies(
            default_policy="default",
            policies=[
                {"name": "default", "require_review_on_fallback": True},
                {"name": "strict", "require_review_on_fallback": True},
            ],
        )
        assert rp.get_policy("strict") is not None
        assert rp.get_policy("nonexistent").name == "default"

    def test_get_policy_no_default(self) -> None:
        rp = ReviewPolicies(policies=[])
        assert rp.get_policy("anything") is None


class TestAppConfig:
    def test_minimal_config(self) -> None:
        c = AppConfig()
        assert c.environment == "local"
        assert c.schema_version == "1"

    def test_all_environments(self) -> None:
        for env in ("local", "dev", "staging", "prod"):
            c = AppConfig(environment=env)
            assert c.environment == env


class TestYamlConfig:
    def test_load_router_yaml(self) -> None:
        yaml_path = CONFIGS_DIR / "router.yaml"
        if not yaml_path.exists():
            pytest.skip("router.yaml not found")

        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        config = AppConfig.model_validate(data)
        assert config.environment == "local"
        assert len(config.router.routes) >= 2  # shrink-to-implemented strategy

        # Verify implemented route names (shrink-to-implemented strategy)
        route_names = {r.name for r in config.router.routes}
        assert "fast_text_route" in route_names
        assert "fallback_safe_route" in route_names
        # complex_pdf_route, ocr_heavy_route, table_formula_route are
        # commented out until their parser adapters are implemented

    def test_yaml_config_roundtrip(self) -> None:
        """Config loaded from YAML can be serialized and re-loaded."""
        yaml_path = CONFIGS_DIR / "router.yaml"
        if not yaml_path.exists():
            pytest.skip("router.yaml not found")

        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        config1 = AppConfig.model_validate(data)
        json_data = config1.model_dump_json()
        config2 = AppConfig.model_validate_json(json_data)
        assert config1.environment == config2.environment
        assert len(config1.router.routes) == len(config2.router.routes)
