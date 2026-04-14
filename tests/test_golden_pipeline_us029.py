"""Tests for US-029: Add a full pipeline to report integration test."""

from __future__ import annotations

import json
from pathlib import Path

from docos.artifact_stores import PatchStore, ReportStore
from docos.ir_store import IRStore
from docos.knowledge_store import KnowledgeStore
from docos.pipeline.runner import PipelineRunner
from docos.run_store import RunStore
from tests.fixtures.build_fixtures import _build_simple_pdf


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

_TEST_CONFIG_YAML = (
    "environment: local\nschema_version: '1'\n"
    "router:\n  default_route: fallback_safe_route\n  routes:\n"
    "    - name: fast_text_route\n"
    "      description: 'Fast text extraction'\n"
    "      file_types: ['application/pdf']\n"
    "      max_pages: 50\n"
    "      requires_ocr: false\n"
    "      table_formula_heavy: false\n"
    "      image_heavy: false\n"
    "      dual_column: false\n"
    "      primary_parser: stdlib_pdf\n"
    "      fallback_parsers: [basic_text_fallback]\n"
    "      expected_risks: []\n      post_parse_repairs: []\n"
    "      review_policy: default\n"
    "    - name: fallback_safe_route\n"
    "      description: 'Safe fallback'\n"
    "      file_types: ['application/pdf']\n"
    "      primary_parser: stdlib_pdf\n"
    "      fallback_parsers: [basic_text_fallback]\n"
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


def _setup_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "router.yaml"
    config_path.write_text(_TEST_CONFIG_YAML)
    return config_path


class TestGoldenPipeline:
    """Golden-path test: raw fixture through full pipeline to report."""

    def test_golden_pipeline_to_report(self, tmp_path: Path) -> None:
        """Run simple_text fixture through full pipeline and verify report.

        This is the golden-path regression test. It exercises:
        ingest -> route -> parse -> normalize -> extract -> compile -> patch -> lint -> harness -> gate
        """
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # -- Pipeline completes successfully --
        assert result.status.value == "completed", (
            f"Pipeline failed at {result.failed_stage}: {result.error_detail}"
        )

        # -- Report includes route information --
        assert result.route_decision is not None
        assert result.route_decision.selected_route is not None
        assert result.route_decision.primary_parser in ("stdlib_pdf", "basic_text_fallback")

        # -- Report includes parser information --
        assert result.docir is not None
        assert result.docir.parser in ("stdlib_pdf", "basic_text_fallback")

        # -- Report includes final stage status --
        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # All stages completed
        from docos.models.run import StageStatus

        for stage in manifest.stages:
            assert stage.status == StageStatus.COMPLETED, (
                f"Stage {stage.name} is {stage.status.value}"
            )

        # -- Verify all major artifacts are persisted --
        # Route artifact
        assert manifest.route_artifact_path is not None
        route_path = Path(manifest.route_artifact_path)
        assert route_path.exists(), "Route artifact not persisted"
        route_data = json.loads(route_path.read_text())
        assert "selected_route" in route_data
        assert "primary_parser" in route_data

        # DocIR artifact
        ir_store = IRStore(tmp_path / "ir")
        docir = ir_store.get(result.run_id)
        assert docir is not None, "DocIR artifact not persisted"
        assert docir.page_count >= 1

        # Knowledge artifact
        ks = KnowledgeStore(tmp_path / "knowledge")
        knowledge = ks.get(result.run_id)
        assert knowledge is not None, "Knowledge artifact not persisted"

        # Lint artifact
        assert manifest.lint_artifact_path is not None
        lint_path = Path(manifest.lint_artifact_path)
        assert lint_path.exists(), "Lint artifact not persisted"

        # Harness report
        rs = ReportStore(tmp_path / "reports")
        harness_report = rs.get(result.run_id)
        assert harness_report is not None, "Harness report not persisted"
        assert harness_report.overall_passed is not None

        # -- Verify pipeline result aggregates --
        assert result.harness_passed is not None
        assert result.gate_passed is not None
        assert isinstance(result.entities, list)
        assert isinstance(result.claims, list)
        assert isinstance(result.patches, list)
        assert result.elapsed_seconds > 0

    def test_golden_pipeline_report_from_manifest(self, tmp_path: Path) -> None:
        """Report can be reconstructed from persisted manifest artifacts."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Reconstruct report from persisted artifacts (same as docos report CLI)
        # Route
        assert manifest.route_artifact_path is not None
        route_data = json.loads(Path(manifest.route_artifact_path).read_text())
        assert "selected_route" in route_data
        assert "primary_parser" in route_data

        # Parser chain
        assert "fallback_parsers" in route_data

        # DocIR
        ir_store = IRStore(tmp_path / "ir")
        docir = ir_store.get(result.run_id)
        assert docir is not None

        # Knowledge
        ks = KnowledgeStore(tmp_path / "knowledge")
        knowledge = ks.get(result.run_id)
        assert knowledge is not None

        # Harness
        rs = ReportStore(tmp_path / "reports")
        harness_report = rs.get(result.run_id)
        assert harness_report is not None

        # Gate decision can be derived from lint + harness
        assert manifest.lint_artifact_path is not None
        lint_data = json.loads(Path(manifest.lint_artifact_path).read_text())
        # Gate: check lint findings + harness passed
        lint_findings_count = len(lint_data)
        harness_passed = harness_report.overall_passed
        # Gate decision should be consistent with the pipeline result
        assert result.gate_passed is not None
