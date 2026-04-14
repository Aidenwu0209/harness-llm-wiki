"""US-028: Add raw-file E2E tests for artifact creation.

Verifies that:
- E2E tests start from real source files instead of in-memory objects
- Tests assert the full artifact chain: route, parse, DocIR, knowledge, patch, lint, eval, gate
- At least 3 fixture categories are tested
- Tests fail if a stage exits without writing required artifacts
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.artifact_stores import PatchStore, ReportStore
from docos.ir_store import IRStore
from docos.knowledge_store import KnowledgeStore
from docos.models.run import RunStatus, StageStatus
from docos.pipeline.runner import PipelineRunner
from docos.run_store import RunStore
from tests.fixtures.build_fixtures import (
    _build_dual_column_pdf,
    _build_ocr_like_pdf,
    _build_simple_pdf,
    _build_table_formula_pdf,
)


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

_TEST_CONFIG_YAML = (
    "environment: local\nschema_version: '1'\n"
    "router:\n  default_route: fallback_safe_route\n  routes:\n"
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
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "router.yaml"
    config_path.write_text(_TEST_CONFIG_YAML)
    return config_path


def _assert_full_artifact_chain(tmp_path: Path, result: object) -> None:
    """Assert the full artifact chain exists after a successful pipeline run.

    This helper verifies that every stage wrote its required persisted artifacts.
    If any stage silently skipped writing, this assertion fails.
    """
    run_id = result.run_id  # type: ignore[union-attr]

    # 1. Source registry record (raw source copy)
    raw_dir = tmp_path / "raw"
    assert raw_dir.exists(), "Raw source directory missing"

    # 2. RunManifest
    store = RunStore(tmp_path)
    manifest = store.get(run_id)
    assert manifest is not None, "RunManifest not persisted"
    assert manifest.source_id is not None
    assert manifest.source_file_path is not None

    # 3. Route logs/artifact
    assert manifest.route_artifact_path is not None, "Route artifact path not set in manifest"
    route_path = Path(manifest.route_artifact_path)
    assert route_path.exists(), f"Route artifact missing at {route_path}"
    route_data = json.loads(route_path.read_text())
    assert "selected_route" in route_data
    assert "primary_parser" in route_data

    # 4. DocIR artifact
    ir_store = IRStore(tmp_path / "ir")
    docir = ir_store.get(run_id)
    assert docir is not None, "DocIR artifact not persisted to IRStore"
    assert docir.page_count >= 1

    # 5. Knowledge artifact
    ks = KnowledgeStore(tmp_path / "knowledge")
    knowledge = ks.get(run_id)
    assert knowledge is not None, "Knowledge artifact not persisted"
    assert isinstance(knowledge.entities, list)
    assert isinstance(knowledge.claims, list)

    # 6. Patch artifact
    assert manifest.patch_artifact_path is not None, "Patch artifact path not set"
    patch_store = PatchStore(tmp_path / "patches")
    # At least one patch should exist
    patch_files = list((tmp_path / "patches").glob("*.json"))
    assert len(patch_files) >= 1, "No patch artifacts persisted"

    # 7. Lint artifact
    assert manifest.lint_artifact_path is not None, "Lint artifact path not set"
    lint_path = Path(manifest.lint_artifact_path)
    assert lint_path.exists(), f"Lint artifact missing at {lint_path}"
    lint_data = json.loads(lint_path.read_text())
    assert isinstance(lint_data, list)

    # 8. Harness report artifact
    assert manifest.report_artifact_path is not None, "Report artifact path not set"
    report_store = ReportStore(tmp_path / "reports")
    harness_report = report_store.get(run_id)
    assert harness_report is not None, "Harness report not persisted"
    assert harness_report.overall_passed is not None

    # 9. Gate decision in manifest
    assert manifest.gate_decision is not None, "Gate decision not set in manifest"
    assert manifest.gate_decision in ("passed", "blocked")

    # 10. All stages completed
    for stage in manifest.stages:
        assert stage.status == StageStatus.COMPLETED, (
            f"Stage {stage.name} is {stage.status.value}, expected completed"
        )


class TestSimpleTextE2E:
    """E2E test from simple_text.pdf raw file through full artifact chain."""

    def test_simple_text_full_artifact_chain(self, tmp_path: Path) -> None:
        """simple_text.pdf produces all artifacts: route, parse, DocIR, knowledge,
        patch, lint, eval, gate."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status == RunStatus.COMPLETED, (
            f"Pipeline failed at {result.failed_stage}: {result.error_detail}"
        )
        _assert_full_artifact_chain(tmp_path, result)

    def test_simple_text_source_registry_record_exists(self, tmp_path: Path) -> None:
        """Source registry record is persisted after simple_text run."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status == RunStatus.COMPLETED
        source = runner.source_registry.get(result.source_id)
        assert source is not None
        assert source.source_id == result.source_id


class TestDualColumnE2E:
    """E2E test from dual_column_or_formula.pdf raw file through full artifact chain."""

    def test_dual_column_full_artifact_chain(self, tmp_path: Path) -> None:
        """dual_column_or_formula.pdf produces all artifacts through full pipeline."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "dual_column.pdf"
        pdf_path.write_bytes(_build_dual_column_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status == RunStatus.COMPLETED, (
            f"Pipeline failed at {result.failed_stage}: {result.error_detail}"
        )
        _assert_full_artifact_chain(tmp_path, result)


class TestTableFormulaE2E:
    """E2E test from table_formula.pdf raw file through full artifact chain."""

    def test_table_formula_full_artifact_chain(self, tmp_path: Path) -> None:
        """table_formula.pdf produces all artifacts through full pipeline."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "table_formula.pdf"
        pdf_path.write_bytes(_build_table_formula_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status == RunStatus.COMPLETED, (
            f"Pipeline failed at {result.failed_stage}: {result.error_detail}"
        )
        _assert_full_artifact_chain(tmp_path, result)


class TestArtifactChainIntegrity:
    """Tests that verify the artifact chain is complete and linked correctly."""

    def test_manifest_links_to_all_artifact_paths(self, tmp_path: Path) -> None:
        """RunManifest contains paths to all expected artifacts after a run."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status == RunStatus.COMPLETED

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # All artifact path fields should be populated
        assert manifest.route_artifact_path is not None
        assert manifest.ir_artifact_path is not None
        assert manifest.knowledge_artifact_path is not None
        assert manifest.patch_artifact_path is not None
        assert manifest.lint_artifact_path is not None
        assert manifest.report_artifact_path is not None

        # Each path should point to an existing file or directory
        for path_str in [
            manifest.route_artifact_path,
            manifest.ir_artifact_path,
            manifest.knowledge_artifact_path,
            manifest.lint_artifact_path,
        ]:
            if path_str is not None:
                assert Path(path_str).exists(), f"Artifact path {path_str} does not exist"

        # Report artifact: path may point to directory with run_id.json
        report_store = ReportStore(Path(tmp_path) / "reports")
        assert report_store.get(result.run_id) is not None, "Report artifact not found in store"

    def test_all_stages_completed_successfully(self, tmp_path: Path) -> None:
        """Each pipeline stage reports COMPLETED status after a successful run."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status == RunStatus.COMPLETED

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        from docos.models.run import PIPELINE_STAGES
        for stage_name in PIPELINE_STAGES:
            stage = next(s for s in manifest.stages if s.name == stage_name)
            assert stage.status == StageStatus.COMPLETED, (
                f"Stage {stage_name} status: {stage.status.value}"
            )
