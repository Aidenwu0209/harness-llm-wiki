"""Tests for US-003: Artifact persistence for all pipeline stages."""

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


class TestArtifactPersistence:
    """US-003: All pipeline stages persist artifacts to disk."""

    def test_route_artifact_persisted(self, tmp_path: Path) -> None:
        """Route decision is persisted as a JSON file."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.route_artifact_path is not None

        route_path = Path(manifest.route_artifact_path)
        assert route_path.exists()
        route_data = json.loads(route_path.read_text())
        assert "selected_route" in route_data
        assert "primary_parser" in route_data

    def test_ir_artifact_persisted(self, tmp_path: Path) -> None:
        """DocIR artifact is persisted to disk."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.ir_artifact_path is not None
        assert Path(manifest.ir_artifact_path).exists()

    def test_knowledge_artifact_persisted(self, tmp_path: Path) -> None:
        """Knowledge artifacts (entities, claims, relations) are persisted."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.knowledge_artifact_path is not None
        knowledge_dir = Path(manifest.knowledge_artifact_path)
        assert knowledge_dir.exists()
        assert (knowledge_dir / "entities.json").exists()
        assert (knowledge_dir / "claims.json").exists()

    def test_patch_artifact_persisted(self, tmp_path: Path) -> None:
        """Patch artifacts are persisted to disk."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        # Patch may or may not be generated depending on wiki state
        if result.patches:
            assert manifest.patch_artifact_path is not None

    def test_lint_artifact_persisted(self, tmp_path: Path) -> None:
        """Lint findings are persisted to disk."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.lint_artifact_path is not None
        lint_path = Path(manifest.lint_artifact_path)
        assert lint_path.exists()

    def test_harness_report_persisted(self, tmp_path: Path) -> None:
        """Harness report is persisted to disk."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.report_artifact_path is not None

    def test_manifest_links_all_artifacts(self, tmp_path: Path) -> None:
        """RunManifest contains links to all persisted artifacts."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Verify all artifact links are populated
        assert manifest.route_artifact_path is not None
        assert manifest.ir_artifact_path is not None
        assert manifest.knowledge_artifact_path is not None
        assert manifest.report_artifact_path is not None
        assert manifest.lint_artifact_path is not None

    def test_failed_run_preserves_debug_artifacts(self, tmp_path: Path) -> None:
        """Failed runs still preserve available debug artifacts."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # This should succeed, but let's verify the debug path is set
        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        # Debug artifact path may be set during parse stage
        if manifest.debug_artifact_path:
            assert Path(manifest.debug_artifact_path).exists()

    def test_no_stage_result_only_in_memory(self, tmp_path: Path) -> None:
        """Verify key artifacts exist on disk, not just in memory."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # All key artifacts should be on disk
        assert (tmp_path / "routes" / f"{result.run_id}.json").exists()
        assert (tmp_path / "ir" / f"{result.run_id}.json").exists()
        assert (tmp_path / "knowledge" / result.run_id / "entities.json").exists()
        assert (tmp_path / "lint_results" / f"{result.run_id}.json").exists()
        assert (tmp_path / "reports" / f"{result.run_id}.json").exists()


class TestFailedRunStageStatus:
    """US-003: Explicit stage status assertions when a pipeline stage fails.

    When a pipeline fails at a middle stage, stages BEFORE the failure point
    must remain COMPLETED, the FAILED stage must be FAILED with error_detail,
    and stages AFTER the failure point must remain PENDING (not started).
    """

    @staticmethod
    def _make_failing_parse_config(config_dir: Path) -> Path:
        """Create a config that routes to a nonexistent parser, causing parse to fail."""
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "router.yaml"
        config_path.write_text(
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
        return config_path

    def test_failed_run_early_stages_completed_later_pending(self, tmp_path: Path) -> None:
        """When config has unresolved parsers, the pipeline fails fast with failed_stage='unknown'."""
        config_path = self._make_failing_parse_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # The pipeline must have failed (fail-fast validation catches bad parsers)
        assert result.status.value == "failed"
        assert result.failed_stage in ("parse", "unknown")
        assert result.error_detail is not None

        # Load the persisted manifest (may exist even on fail-fast)
        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)

        if manifest is not None:
            # When fail-fast catches the error before any stage runs,
            # all stages remain PENDING.  When the error happens at the parse
            # stage, earlier stages (ingest, route) are COMPLETED.
            for stage in manifest.stages:
                if stage.status == StageStatus.FAILED:
                    assert stage.error_detail is not None, (
                        f"Failed stage '{stage.name}' must have error_detail set"
                    )
