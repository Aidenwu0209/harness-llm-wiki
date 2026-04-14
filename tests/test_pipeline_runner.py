"""Tests for US-001: Unified pipeline run command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.pipeline.runner import PipelineRunner


def _write_simple_pdf(path: Path) -> Path:
    """Create a minimal valid PDF for testing."""
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


class TestPipelineRunner:
    """Tests for PipelineRunner.run()."""

    def test_full_pipeline_success(self, tmp_path: Path) -> None:
        """Full pipeline runs end-to-end and produces artifacts."""
        # Set up config
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "router.yaml").write_text(
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

        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_dir / "router.yaml")
        result = runner.run(file_path=pdf_path)

        # Pipeline should complete successfully
        assert result.status.value == "completed", f"Failed at {result.failed_stage}: {result.error_detail}"
        assert result.run_id != ""
        assert result.source_id != ""
        assert result.docir is not None
        assert result.route_decision is not None
        assert result.elapsed_seconds > 0

    def test_pipeline_creates_run_manifest(self, tmp_path: Path) -> None:
        """Pipeline creates a persisted RunManifest."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "router.yaml").write_text(
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

        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_dir / "router.yaml")
        result = runner.run(file_path=pdf_path)

        assert result.run_id != ""
        # Verify manifest is persisted
        from docos.run_store import RunStore

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.run_id == result.run_id
        assert manifest.source_id == result.source_id

    def test_pipeline_stages_all_completed(self, tmp_path: Path) -> None:
        """All pipeline stages are marked completed in the RunManifest."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "router.yaml").write_text(
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

        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_dir / "router.yaml")
        result = runner.run(file_path=pdf_path)

        from docos.run_store import RunStore
        from docos.models.run import StageStatus

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        for stage in manifest.stages:
            assert stage.status == StageStatus.COMPLETED, (
                f"Stage {stage.name} is {stage.status.value}, expected completed"
            )

    def test_pipeline_persists_ir_artifact(self, tmp_path: Path) -> None:
        """Pipeline persists DocIR artifact to disk."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "router.yaml").write_text(
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

        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_dir / "router.yaml")
        result = runner.run(file_path=pdf_path)

        from docos.ir_store import IRStore

        ir_store = IRStore(tmp_path / "ir")
        docir = ir_store.get(result.run_id)
        assert docir is not None
        assert docir.page_count >= 1

    def test_pipeline_failure_stops_early(self, tmp_path: Path) -> None:
        """Pipeline stops and reports failure when a stage fails."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "router.yaml").write_text(
            "environment: local\nschema_version: '1'\n"
            "router:\n  default_route: bad_route\n  routes:\n"
            "    - name: bad_route\n      description: 'test'\n"
            "      file_types: ['application/pdf']\n"
            "      primary_parser: nonexistent_parser\n      fallback_parsers: []\n"
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

        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_dir / "router.yaml")
        result = runner.run(file_path=pdf_path)

        assert result.status.value == "failed"
        assert result.failed_stage == "parse"
        assert result.error_detail is not None

    def test_cli_run_command_registered(self) -> None:
        """The 'run' command is registered in the CLI."""
        from click.testing import CliRunner

        from docos.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "run" in result.output
