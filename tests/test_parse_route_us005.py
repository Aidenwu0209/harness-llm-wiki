"""Tests for US-005: Parse stage uses Route + Registry + Orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from docos.cli.main import cli
from docos.pipeline.runner import PipelineRunner


def _make_test_config(config_dir: Path) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "router.yaml"
    config_path.write_text(
        "environment: local\nschema_version: '1'\n"
        "router:\n  default_route: fallback_safe_route\n  routes:\n"
        "    - name: fallback_safe_route\n      description: 'test'\n"
        "      file_types: ['application/pdf']\n"
        "      primary_parser: stdlib_pdf\n      fallback_parsers: [basic_text]\n"
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


def _write_simple_pdf(path: Path) -> Path:
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 80 >>\nstream\n"
        b"BT /F1 12 Tf 100 700 Td (Introduction) Tj ET\n"
        b"BT /F1 10 Tf 100 680 Td (This is a test document body.) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


class TestParseViaRoute:
    """US-005: Parse stage uses Route + Registry + Orchestrator."""

    def test_parse_cli_uses_route_decision(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The standalone parse CLI command uses route decision."""
        monkeypatch.chdir(tmp_path)
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")

        # First ingest the file
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        pipeline_result = runner.run(file_path=pdf_path)
        source_id = pipeline_result.source_id

        # Run standalone parse command
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["parse", source_id])
        assert output.exit_code == 0
        data = json.loads(output.output)
        assert "route" in data
        assert data["route"] == "fallback_safe_route"
        assert data["parser"] in ["stdlib_pdf", "basic_text"]

    def test_parse_not_directly_instantiating_parser(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parse CLI output includes route name, proving it went through router."""
        monkeypatch.chdir(tmp_path)
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        pipeline_result = runner.run(file_path=pdf_path)
        source_id = pipeline_result.source_id

        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["parse", source_id])
        data = json.loads(output.output)
        # Route name proves router was used, not direct parser instantiation
        assert data["route"] == "fallback_safe_route"
        assert data["success"] is True

    def test_parse_pipeline_uses_selected_route(self, tmp_path: Path) -> None:
        """PipelineRunner.parse uses the route-selected parser chain."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.route_decision is not None
        assert result.route_decision.selected_route == "fallback_safe_route"
        assert result.route_decision.primary_parser == "stdlib_pdf"
