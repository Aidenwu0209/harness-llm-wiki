"""Tests for US-036: Validate the golden closed loop from raw fixture to stable rerun."""

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


class TestGoldenClosedLoop:
    """Final validation: golden fixture -> full pipeline -> report -> stable rerun."""

    def test_golden_fixture_produces_all_artifacts(self, tmp_path: Path) -> None:
        """Golden fixture produces persisted route, parse, DocIR, knowledge, patch, lint, harness, and report artifacts."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "golden.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # Pipeline completes
        assert result.status.value == "completed", (
            f"Golden run failed at {result.failed_stage}: {result.error_detail}"
        )

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Route artifact
        assert manifest.route_artifact_path is not None
        route_data = json.loads(Path(manifest.route_artifact_path).read_text())
        assert "selected_route" in route_data
        assert "primary_parser" in route_data

        # DocIR artifact
        ir_store = IRStore(tmp_path / "ir")
        docir = ir_store.get(result.run_id)
        assert docir is not None, "DocIR artifact missing"
        assert docir.page_count >= 1

        # Knowledge artifact
        ks = KnowledgeStore(tmp_path / "knowledge")
        knowledge = ks.get(result.run_id)
        assert knowledge is not None, "Knowledge artifact missing"

        # Patch artifact
        if result.patches:
            assert manifest.patch_artifact_path is not None
            patch_store = PatchStore(tmp_path / "patches")
            for p in result.patches:
                loaded = patch_store.get(p.patch_id)
                assert loaded is not None, f"Patch {p.patch_id} not persisted"

        # Lint artifact
        assert manifest.lint_artifact_path is not None
        lint_path = Path(manifest.lint_artifact_path)
        assert lint_path.exists(), "Lint artifact not persisted"

        # Harness report
        rs = ReportStore(tmp_path / "reports")
        harness_report = rs.get(result.run_id)
        assert harness_report is not None, "Harness report missing"

    def test_golden_report_shows_complete_trace(self, tmp_path: Path) -> None:
        """docos report equivalent shows route, parser chain, gate decision, and artifact locations."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "golden.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Route info
        assert manifest.selected_route is not None
        route_data = json.loads(Path(manifest.route_artifact_path).read_text())
        assert route_data["selected_route"] == manifest.selected_route

        # Parser chain
        assert len(manifest.parser_chain) > 0
        assert manifest.selected_route in route_data["selected_route"]

        # Gate decision
        assert manifest.gate_decision in ("passed", "blocked")

        # Artifact locations
        assert manifest.route_artifact_path is not None
        assert manifest.ir_artifact_path is not None
        assert manifest.knowledge_artifact_path is not None

    def test_golden_rerun_preserves_stable_identifiers(self, tmp_path: Path) -> None:
        """Re-running the same golden fixture preserves stable identifiers."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "golden.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        # Run 1
        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status.value == "completed"

        ks1 = KnowledgeStore(tmp_path / "knowledge")
        artifact1 = ks1.get(result1.run_id)
        assert artifact1 is not None

        entity_ids_run1 = sorted(e.entity_id for e in artifact1.entities)
        claim_ids_run1 = sorted(c.claim_id for c in artifact1.claims)
        rel_ids_run1 = sorted(r.relation_id for r in artifact1.relations)

        # Run 2 (same fixture)
        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status.value == "completed"

        ks2 = KnowledgeStore(tmp_path / "knowledge")
        artifact2 = ks2.get(result2.run_id)
        assert artifact2 is not None

        entity_ids_run2 = sorted(e.entity_id for e in artifact2.entities)
        claim_ids_run2 = sorted(c.claim_id for c in artifact2.claims)
        rel_ids_run2 = sorted(r.relation_id for r in artifact2.relations)

        # Stable IDs
        assert entity_ids_run1 == entity_ids_run2, (
            f"Entity IDs not stable.\nRun1: {entity_ids_run1}\nRun2: {entity_ids_run2}"
        )
        assert claim_ids_run1 == claim_ids_run2, (
            f"Claim IDs not stable.\nRun1: {claim_ids_run1}\nRun2: {claim_ids_run2}"
        )
        assert rel_ids_run1 == rel_ids_run2, (
            f"Relation IDs not stable.\nRun1: {rel_ids_run1}\nRun2: {rel_ids_run2}"
        )

    def test_golden_rerun_preserves_stable_patch_ids(self, tmp_path: Path) -> None:
        """Re-running the same golden fixture preserves stable patch IDs."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "golden.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        # Run 1
        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status.value == "completed"

        patch_ids_run1 = sorted(p.patch_id for p in result1.patches) if result1.patches else []

        # Run 2
        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status.value == "completed"

        patch_ids_run2 = sorted(p.patch_id for p in result2.patches) if result2.patches else []

        assert patch_ids_run1 == patch_ids_run2, (
            f"Patch IDs not stable.\nRun1: {patch_ids_run1}\nRun2: {patch_ids_run2}"
        )

    def test_golden_rerun_does_not_regress(self, tmp_path: Path) -> None:
        """Re-running the same golden fixture does not regress the golden-path test.

        Both runs complete successfully with the same structure.
        """
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "golden.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        for run_num in range(1, 3):
            runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
            result = runner.run(file_path=pdf_path)

            assert result.status.value == "completed", (
                f"Run {run_num} failed at {result.failed_stage}: {result.error_detail}"
            )
            assert result.docir is not None
            assert result.route_decision is not None
            assert result.gate_passed is not None
