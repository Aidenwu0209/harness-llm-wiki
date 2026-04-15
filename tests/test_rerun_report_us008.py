"""Tests for US-008: Rerun and report support for existing sources and runs."""

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


def _run_pipeline(tmp_path: Path) -> tuple[str, str]:
    """Run full pipeline and return (run_id, source_id)."""
    config_path = _make_test_config(tmp_path / "configs")
    pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
    runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
    result = runner.run(file_path=pdf_path)
    assert result.status.value == "completed"
    return result.run_id, result.source_id


class TestRerunFromSourceId:
    """US-008: CLI can create a new run from an existing source_id."""

    def test_rerun_creates_new_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rerun command creates a new run_id from existing source_id."""
        monkeypatch.chdir(tmp_path)
        run_id_1, source_id = _run_pipeline(tmp_path)

        # Rerun using the existing source_id
        runner = CliRunner()
        output = runner.invoke(cli, ["rerun", source_id])
        assert output.exit_code == 0

        data = json.loads(output.output)
        assert data["source_id"] == source_id
        assert data["run_id"] != run_id_1  # new run_id
        assert data["status"] == "completed"

    def test_rerun_unknown_source_returns_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rerun with non-existent source_id returns error."""
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["rerun", "src_nonexistent"])
        assert output.exit_code == 1

    def test_rerun_preserves_source(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rerun doesn't modify the original source."""
        monkeypatch.chdir(tmp_path)
        run_id_1, source_id = _run_pipeline(tmp_path)

        # Rerun
        runner = CliRunner()
        output = runner.invoke(cli, ["rerun", source_id])
        data = json.loads(output.output)

        # Original run should still be accessible
        store = RunStore(tmp_path)
        original = store.get(run_id_1)
        assert original is not None
        assert original.source_id == source_id

        # New run should also be accessible
        new_run = store.get(data["run_id"])
        assert new_run is not None


class TestReportWithoutRerun:
    """US-008: CLI can inspect a saved run by run_id without rerunning."""

    def test_report_saved_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report command reads persisted run without rerunning."""
        monkeypatch.chdir(tmp_path)
        run_id, _ = _run_pipeline(tmp_path)

        # Report should work from persisted state alone
        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        assert output.exit_code == 0

        data = json.loads(output.output)
        assert data["run_id"] == run_id
        assert data["status"] == "completed"

    def test_report_unknown_run_returns_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report for non-existent run_id returns error."""
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", "run_nonexistent_abc"])
        assert output.exit_code == 1


class TestFailedRunPreservesArtifacts:
    """US-008: Failed run preserves completed artifact references."""

    @staticmethod
    def _make_no_fallback_config(config_dir: Path) -> Path:
        """Create a config with valid parser but no fallback, so parse failure causes pipeline to fail."""
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
        return config_path

    def test_failed_run_preserves_route_artifact(self, tmp_path: Path) -> None:
        """Failed run still has route artifact from completed stage."""
        config_path = self._make_no_fallback_config(tmp_path / "configs")
        # Use a corrupted PDF (no %PDF header) to force parse failure
        corrupted_pdf = b"CORRUPTED-HEADER\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(corrupted_pdf)
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status.value == "failed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Route artifact should still exist (ingest + route completed before failure)
        assert manifest.route_artifact_path is not None
        assert Path(manifest.route_artifact_path).exists()

    def test_failed_run_source_registry_intact(self, tmp_path: Path) -> None:
        """Failed run preserves source registry record."""
        config_path = self._make_no_fallback_config(tmp_path / "configs")
        # Use a corrupted PDF (no %PDF header) to force parse failure
        corrupted_pdf = b"CORRUPTED-HEADER\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(corrupted_pdf)
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # Source registry should still have the record
        source = runner.source_registry.get(result.source_id)
        assert source is not None
        assert source.source_hash != ""
