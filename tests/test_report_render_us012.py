"""Tests for US-012: Render report output from persisted artifacts.

Acceptance criteria:
- report prints route, parser, DocIR, knowledge, patch, harness, review state
- failed run shows failing stage and error detail
- the command no longer returns placeholder or guessed status text
"""

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
        "      primary_parser: stdlib_pdf\n      fallback_parsers: [basic_text_fallback]\n"
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


def _run_pipeline(tmp_path: Path) -> str:
    """Run full pipeline and return run_id."""
    config_path = _make_test_config(tmp_path / "configs")
    pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
    runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
    result = runner.run(file_path=pdf_path)
    assert result.status.value == "completed"
    return result.run_id


def _run_failed_pipeline(tmp_path: Path) -> str:
    """Run pipeline with a corrupted PDF to force parse failure and return run_id."""
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "router.yaml"
    # Use valid parser but no fallback, so parse failure causes pipeline to fail
    config_path.write_text(
        "environment: local\nschema_version: '1'\n"
        "router:\n  default_route: fallback_safe_route\n  routes:\n"
        "    - name: fallback_safe_route\n      description: 'test'\n"
        "      file_types: ['application/pdf']\n"
        "      primary_parser: stdlib_pdf\n      fallback_parsers: []\n"
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
    # Use a corrupted PDF (no %PDF header) so stdlib_pdf fails at parse stage
    corrupted_pdf = b"CORRUPTED-HEADER\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(corrupted_pdf)
    runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
    result = runner.run(file_path=pdf_path)
    return result.run_id


# ---------------------------------------------------------------------------
# AC1: Report prints route, parser, DocIR, knowledge, patch, harness, review
# ---------------------------------------------------------------------------


class TestReportRendersAllState:
    """Report prints route, parser, DocIR, knowledge, patch, harness, and
    review state from persisted artifacts."""

    def test_report_shows_route(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report output includes route decision."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert isinstance(data["route"], dict)
        assert "selected_route" in data["route"]

    def test_report_shows_parser(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report output includes parser chain."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert isinstance(data["parser_chain"], dict)
        assert "primary" in data["parser_chain"]

    def test_report_shows_docir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report output includes DocIR page/block counts."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert isinstance(data["ir_pages"], int)
        assert isinstance(data["ir_blocks"], int)

    def test_report_shows_knowledge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report output includes knowledge artifact counts."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert isinstance(data.get("entity_count"), int)
        assert isinstance(data.get("claim_count"), int)

    def test_report_shows_patch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report output includes patch artifact path."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert data.get("patch_artifact") is not None
        assert data["patch_artifact"] != "not-generated-yet"

    def test_report_shows_harness(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report output includes harness status."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert data["harness_status"] is not None
        assert data["harness_passed"] is not None

    def test_report_shows_review(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report output includes review status."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "review_status" in data


# ---------------------------------------------------------------------------
# AC2: Failed run shows failing stage and error detail
# ---------------------------------------------------------------------------


class TestReportFailedRun:
    """A failed run shows the failing stage and error detail in report output."""

    def test_failed_run_shows_stage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report for a failed run includes the failing stage name."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_failed_pipeline(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert data["status"] == "failed"
        assert data.get("failed_stage") is not None
        assert isinstance(data["failed_stage"], str)

    def test_failed_run_shows_error_detail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report for a failed run includes error detail text."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_failed_pipeline(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert data["status"] == "failed"
        assert data.get("error_detail") is not None
        assert isinstance(data["error_detail"], str)
        assert len(data["error_detail"]) > 0

    def test_failed_run_no_placeholder_text(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report for a failed run uses real error text, not placeholders."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_failed_pipeline(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        # The error detail should be a real error message, not a placeholder
        assert data["error_detail"] not in ("", "unknown error", "N/A")
