"""Tests for US-004: Report output from persisted artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from docos.cli.main import cli
from docos.models.run import RunManifest, StageStatus
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


class TestReportFromArtifacts:
    """US-004: report reads from persisted artifacts."""

    def _run_pipeline(self, tmp_path: Path) -> str:
        """Run full pipeline and return run_id."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"
        return result.run_id

    def test_report_shows_route_info(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report includes route decision from persisted artifact."""
        monkeypatch.chdir(tmp_path)
        run_id = self._run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        assert output.exit_code == 0
        data = json.loads(output.output)
        assert isinstance(data["route"], dict)
        assert "selected_route" in data["route"]
        assert "primary_parser" in data["route"]

    def test_report_shows_parser_chain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report includes parser chain info."""
        monkeypatch.chdir(tmp_path)
        run_id = self._run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert isinstance(data["parser_chain"], dict)
        assert "primary" in data["parser_chain"]

    def test_report_shows_ir_info(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows DocIR page and block counts."""
        monkeypatch.chdir(tmp_path)
        run_id = self._run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert data["ir_pages"] is not None
        assert data["ir_blocks"] is not None

    def test_report_shows_knowledge_counts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows entity, claim, relation counts."""
        monkeypatch.chdir(tmp_path)
        run_id = self._run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert isinstance(data.get("entity_count"), int)
        assert isinstance(data.get("claim_count"), int)

    def test_report_shows_harness_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows harness evaluation result."""
        monkeypatch.chdir(tmp_path)
        run_id = self._run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert data["harness_status"] is not None
        assert data["harness_passed"] is not None

    def test_report_shows_all_stages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report shows all pipeline stages with status."""
        monkeypatch.chdir(tmp_path)
        run_id = self._run_pipeline(tmp_path)

        runner = CliRunner()
        output = runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        stages = data["stages"]
        assert len(stages) >= 10
        stage_names = [s["name"] for s in stages]
        assert "ingest" in stage_names
        assert "route" in stage_names
        assert "parse" in stage_names
        assert "gate" in stage_names

    def test_report_failed_run_shows_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report for a failed run shows failing stage and error."""
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
        # Use a corrupted PDF (no %PDF header) to force parse failure
        corrupted_pdf = b"CORRUPTED-HEADER\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(corrupted_pdf)
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        runner_cli = CliRunner()
        output = runner_cli.invoke(cli, ["report", result.run_id])
        data = json.loads(output.output)
        assert data["status"] == "failed"
        assert data.get("failed_stage") is not None
        assert data.get("error_detail") is not None

    def test_report_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report for non-existent run returns error."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        output = runner.invoke(cli, ["report", "run_nonexistent"])
        assert output.exit_code == 1
        data = json.loads(output.output)
        assert "error" in data


class TestSourceIdReload:
    """US-004: Persisted route artifacts can be reloaded by source_id."""

    def test_get_by_source_id_returns_manifest(self, tmp_path: Path) -> None:
        """RunStore.get_by_source_id finds a manifest by its source_id."""
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_reload_test",
            source_hash="a" * 64,
            source_file_path="/tmp/test.pdf",
        )

        # Mark a stage to prove full round-trip
        manifest.mark_stage("ingest", StageStatus.COMPLETED)
        store.update(manifest)

        # Reload by source_id in a fresh store instance
        store2 = RunStore(tmp_path)
        found = store2.get_by_source_id("src_reload_test")
        assert found is not None
        assert found.run_id == manifest.run_id
        assert found.source_id == "src_reload_test"

        # Verify persisted stage state survived the round-trip
        ingest = next(s for s in found.stages if s.name == "ingest")
        assert ingest.status == StageStatus.COMPLETED

    def test_get_by_source_id_returns_none_when_missing(self, tmp_path: Path) -> None:
        """RunStore.get_by_source_id returns None for unknown source_id."""
        store = RunStore(tmp_path)
        assert store.get_by_source_id("src_nonexistent") is None

    def test_get_by_source_id_among_multiple_runs(self, tmp_path: Path) -> None:
        """get_by_source_id returns the correct manifest when multiple exist."""
        store = RunStore(tmp_path)
        m1 = store.create(
            source_id="src_alpha",
            source_hash="a" * 64,
            source_file_path="/tmp/a.pdf",
        )
        m2 = store.create(
            source_id="src_beta",
            source_hash="b" * 64,
            source_file_path="/tmp/b.pdf",
        )

        found = store.get_by_source_id("src_beta")
        assert found is not None
        assert found.run_id == m2.run_id
        assert found.source_id == "src_beta"
        assert found.run_id != m1.run_id
