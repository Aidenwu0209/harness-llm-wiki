"""US-029: Cover fallback and rerun stability in E2E regression.

Verifies that:
- Fallback behavior tested (primary fails, fallback succeeds)
- Rerun stability: same input produces same patch IDs, entity IDs
- Debug artifacts available for drift comparison
"""

from __future__ import annotations

import json
from pathlib import Path

from docos.artifact_stores import PatchStore
from docos.debug_store import DebugAssetStore
from docos.ir_store import IRStore
from docos.knowledge_store import KnowledgeStore
from docos.models.run import RunStatus, StageStatus
from docos.pipeline.runner import PipelineRunner
from docos.run_store import RunStore
from tests.fixtures.build_fixtures import _build_simple_pdf


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

# Config where primary parser fails (non-existent) but fallback works
_FALLBACK_CONFIG_YAML = (
    "environment: local\nschema_version: '1'\n"
    "router:\n  default_route: fallback_route\n  routes:\n"
    "    - name: fallback_route\n"
    "      description: 'Route that triggers fallback'\n"
    "      file_types: ['application/pdf']\n"
    "      primary_parser: nonexistent_parser\n"
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

_NORMAL_CONFIG_YAML = (
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


def _setup_config(tmp_path: Path, config_yaml: str = _NORMAL_CONFIG_YAML) -> Path:
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "router.yaml"
    config_path.write_text(config_yaml)
    return config_path


class TestFallbackBehavior:
    """Test fallback parser behavior in E2E scenario."""

    def test_primary_fails_fallback_succeeds(self, tmp_path: Path) -> None:
        """When primary parser fails, fallback parser succeeds and pipeline completes."""
        config_path = _setup_config(tmp_path, _FALLBACK_CONFIG_YAML)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status == RunStatus.COMPLETED, (
            f"Pipeline failed: {result.failed_stage}: {result.error_detail}"
        )

    def test_fallback_produces_persisted_docir(self, tmp_path: Path) -> None:
        """Fallback parser produces a DocIR that is persisted to disk."""
        config_path = _setup_config(tmp_path, _FALLBACK_CONFIG_YAML)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status == RunStatus.COMPLETED
        ir_store = IRStore(tmp_path / "ir")
        docir = ir_store.get(result.run_id)
        assert docir is not None, "Fallback DocIR not persisted"

    def test_fallback_recorded_in_manifest(self, tmp_path: Path) -> None:
        """Manifest records that fallback parser was used."""
        config_path = _setup_config(tmp_path, _FALLBACK_CONFIG_YAML)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status == RunStatus.COMPLETED
        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.fallback_used is True

    def test_fallback_produces_knowledge_artifacts(self, tmp_path: Path) -> None:
        """Fallback pipeline produces knowledge artifacts."""
        config_path = _setup_config(tmp_path, _FALLBACK_CONFIG_YAML)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status == RunStatus.COMPLETED
        ks = KnowledgeStore(tmp_path / "knowledge")
        artifact = ks.get(result.run_id)
        assert artifact is not None
        assert isinstance(artifact.entities, list)
        assert isinstance(artifact.claims, list)


class TestRerunStability:
    """Test rerun stability: same input produces same identifiers."""

    def test_stable_source_id_on_rerun(self, tmp_path: Path) -> None:
        """Same file produces same source_id on repeated runs."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        # source_id should be stable (based on content hash)
        assert result1.source_id == result2.source_id, (
            f"source_id drift: {result1.source_id} vs {result2.source_id}"
        )

    def test_stable_route_choice_on_rerun(self, tmp_path: Path) -> None:
        """Same file produces same route choice on repeated runs."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        assert result1.route_decision is not None
        assert result2.route_decision is not None
        assert result1.route_decision.selected_route == result2.route_decision.selected_route

    def test_stable_patch_ids_on_rerun(self, tmp_path: Path) -> None:
        """Same input produces same patch_id values on rerun."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        patch_ids_1 = sorted(p.patch_id for p in result1.patches)
        patch_ids_2 = sorted(p.patch_id for p in result2.patches)
        assert patch_ids_1 == patch_ids_2, (
            f"Patch ID drift: {patch_ids_1} vs {patch_ids_2}"
        )

    def test_stable_entity_ids_on_rerun(self, tmp_path: Path) -> None:
        """Same input produces same entity_id values on rerun."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        ks = KnowledgeStore(tmp_path / "knowledge")
        art1 = ks.get(result1.run_id)
        art2 = ks.get(result2.run_id)
        assert art1 is not None and art2 is not None

        ent_ids_1 = sorted(e.entity_id for e in art1.entities)
        ent_ids_2 = sorted(e.entity_id for e in art2.entities)
        assert ent_ids_1 == ent_ids_2, (
            f"Entity ID drift: {ent_ids_1} vs {ent_ids_2}"
        )

    def test_rerun_verifies_real_content(self, tmp_path: Path) -> None:
        """Rerun test verifies real object content, not just exit codes."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        # Verify real DocIR content
        ir_store = IRStore(tmp_path / "ir")
        docir1 = ir_store.get(result1.run_id)
        docir2 = ir_store.get(result2.run_id)
        assert docir1 is not None and docir2 is not None
        assert docir1.page_count == docir2.page_count
        assert len(docir1.blocks) == len(docir2.blocks)

        # Verify real knowledge content
        ks = KnowledgeStore(tmp_path / "knowledge")
        art1 = ks.get(result1.run_id)
        art2 = ks.get(result2.run_id)
        assert art1 is not None and art2 is not None
        assert len(art1.entities) == len(art2.entities)
        assert len(art1.claims) == len(art2.claims)


class TestDebugArtifactsForDrift:
    """Test that debug artifacts are available for drift comparison."""

    def test_manifest_persisted_for_drift_comparison(self, tmp_path: Path) -> None:
        """Both run manifests are persisted for drift comparison."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        store = RunStore(tmp_path)
        m1 = store.get(result1.run_id)
        m2 = store.get(result2.run_id)
        assert m1 is not None
        assert m2 is not None

        # Verify manifests have timing data for drift comparison
        assert m1.started_at is not None
        assert m2.started_at is not None
        assert m1.finished_at is not None
        assert m2.finished_at is not None

    def test_knowledge_artifacts_persisted_for_comparison(self, tmp_path: Path) -> None:
        """Knowledge artifacts from both runs are available for comparison."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)

        ks = KnowledgeStore(tmp_path / "knowledge")
        assert ks.exists(result1.run_id)
        assert ks.exists(result2.run_id)

    def test_patch_artifacts_persisted_for_comparison(self, tmp_path: Path) -> None:
        """Patch artifacts from both runs are available for comparison."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)

        # Patches from both runs should be in the store
        for p in result1.patches:
            ps = PatchStore(tmp_path / "patches")
            assert ps.get(p.patch_id) is not None
        for p in result2.patches:
            ps = PatchStore(tmp_path / "patches")
            assert ps.get(p.patch_id) is not None
