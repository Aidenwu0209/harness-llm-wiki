"""Tests for US-007: docos report reconstructs full run state from stores."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from docos.cli.main import cli
from docos.pipeline.runner import PipelineRunner
from docos.run_store import RunStore


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


class TestReportFullReconstruction:
    """US-007: docos report reconstructs full run state from stores."""

    def test_report_has_source_registry_info(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows source registry info."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert data["source_id"] is not None
        assert data["source_file_path"] is not None

    def test_report_has_route_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows route decision from persisted stores."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert isinstance(data["route"], dict)
        assert data["route"]["selected_route"] is not None
        assert data["route"]["primary_parser"] is not None

    def test_report_has_parser_chain_and_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows parser attempts and fallback state."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "parser_chain" in data
        assert "fallback_used" in data

    def test_report_has_docir_summary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows DocIR summary from persisted IR store."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert data["ir_pages"] is not None
        assert data["ir_blocks"] is not None
        assert data["ir_artifact"] != "not-generated-yet"

    def test_report_has_knowledge_summary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows knowledge summary from persisted stores."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert isinstance(data.get("entity_count"), int)
        assert isinstance(data.get("claim_count"), int)

    def test_report_has_patch_state(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows patch state."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "patch_artifact" in data

    def test_report_has_lint_summary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows lint summary from persisted stores."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "lint_findings" in data
        assert data["lint_findings"] != "not-generated-yet"

    def test_report_has_harness_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows harness evaluation result from persisted stores."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert data["harness_status"] != "not-generated-yet"
        assert data["harness_passed"] is not None

    def test_report_has_release_decision(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows release decision from manifest."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "gate_decision" in data
        assert data["gate_decision"] is not None

    def test_report_has_review_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows review status."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "review_status" in data


class TestReportFailedRun:
    """US-007: Failed run report includes failing stage and error."""

    def test_failed_run_report_has_failing_stage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report for failed run shows failing stage name."""
        monkeypatch.chdir(tmp_path)
        # Use valid parser but no fallback, so parse failure causes pipeline to fail
        config_dir = tmp_path / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "router.yaml"
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

        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", result.run_id])
        data = json.loads(output.output)

        assert data["status"] == "failed"
        assert data["failed_stage"] is not None
        assert data["error_detail"] is not None
        assert data["failed_stage"] != ""

    def test_report_no_placeholder_strings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report output uses real data, not placeholder strings."""
        monkeypatch.chdir(tmp_path)
        run_id = _run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)

        # Verify key fields are not placeholder strings
        placeholders = {"not-generated-yet", "placeholder", "TODO", "N/A", "tbd"}
        # Check that core fields have real values
        assert data["source_id"] not in placeholders
        assert data["status"] not in placeholders
        # Route should be a real dict, not a placeholder
        assert isinstance(data["route"], dict)
        assert data["route"].get("selected_route") not in placeholders
