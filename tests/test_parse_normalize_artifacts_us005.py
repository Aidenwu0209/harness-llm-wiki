"""Tests for US-005: Persist parse and normalize artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.models.run import StageStatus
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


class TestParseArtifacts:
    """US-005: Parse writes parser attempt logs, parse results, and debug assets."""

    def test_parse_log_persisted(self, tmp_path: Path) -> None:
        """Parse writes a parse_log.json for each parser attempt."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Debug artifact path should be set
        assert manifest.debug_artifact_path is not None

        # Parse log should exist
        debug_dir = Path(manifest.debug_artifact_path)
        assert debug_dir.exists()
        # Check for parse_log.json inside debug directory
        parse_logs = list(debug_dir.rglob("parse_log.json"))
        assert len(parse_logs) >= 1, "Expected at least one parse_log.json"

        # Parse log should contain meaningful data
        log_data = json.loads(parse_logs[0].read_text())
        assert "parser_name" in log_data
        assert "success" in log_data

    def test_parse_results_persisted_as_docir(self, tmp_path: Path) -> None:
        """Parse writes DocIR (parse results) to persistent storage."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # DocIR should be persisted
        assert manifest.ir_artifact_path is not None
        ir_path = Path(manifest.ir_artifact_path)
        assert ir_path.exists()

        ir_data = json.loads(ir_path.read_text())
        assert "pages" in ir_data
        assert "blocks" in ir_data

    def test_debug_assets_persisted(self, tmp_path: Path) -> None:
        """Parse writes debug assets (assets_index.json, raw_output, etc.)."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Debug assets directory should exist
        if manifest.debug_artifact_path:
            debug_dir = Path(manifest.debug_artifact_path)
            assert debug_dir.exists()
            # Should have assets_index.json
            asset_indices = list(debug_dir.rglob("assets_index.json"))
            assert len(asset_indices) >= 1

    def test_parse_stage_completed_in_manifest(self, tmp_path: Path) -> None:
        """Parse stage is marked COMPLETED in RunManifest."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        parse_stage = next(s for s in manifest.stages if s.name == "parse")
        assert parse_stage.status == StageStatus.COMPLETED


class TestNormalizeArtifacts:
    """US-005: Normalize writes canonical DocIR, repair logs, and invariant checks."""

    def test_canonical_docir_persisted(self, tmp_path: Path) -> None:
        """Normalize writes the canonical DocIR to persistent storage."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # The ir_artifact_path should contain the normalized (post-repair) DocIR
        assert manifest.ir_artifact_path is not None
        ir_path = Path(manifest.ir_artifact_path)
        assert ir_path.exists()

        ir_data = json.loads(ir_path.read_text())
        # Verify it's a valid DocIR
        assert "pages" in ir_data
        assert "blocks" in ir_data
        assert "schema_version" in ir_data

    def test_normalize_stage_completed_in_manifest(self, tmp_path: Path) -> None:
        """Normalize stage is marked COMPLETED in RunManifest."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        normalize_stage = next(s for s in manifest.stages if s.name == "normalize")
        assert normalize_stage.status == StageStatus.COMPLETED

    def test_manifest_links_parse_and_normalize_artifacts(self, tmp_path: Path) -> None:
        """RunManifest links to parse and normalize artifact paths."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Parse artifacts: ir_artifact_path, debug_artifact_path
        assert manifest.ir_artifact_path is not None
        assert Path(manifest.ir_artifact_path).exists()

        # Debug assets from parse
        if manifest.debug_artifact_path:
            assert Path(manifest.debug_artifact_path).exists()
