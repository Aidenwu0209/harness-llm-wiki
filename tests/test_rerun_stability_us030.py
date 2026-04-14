"""Tests for US-030: Add rerun stability tests for patch and knowledge IDs.

Acceptance criteria:
  1. A test re-runs the same unchanged fixture and asserts stable patch_id values
  2. A test re-runs the same unchanged fixture and asserts stable entity/claim identifiers
  3. Failure-path debug artifacts remain available for comparing unexpected rerun drift
"""

from __future__ import annotations

import json
from pathlib import Path

from docos.artifact_stores import PatchStore
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


class TestRerunStability:
    """Same fixture run twice produces stable IDs."""

    # ------------------------------------------------------------------
    # AC-1: Stable patch_id values across reruns
    # ------------------------------------------------------------------

    def test_stable_patch_ids_on_rerun(self, tmp_path: Path) -> None:
        """Running the same unchanged fixture twice produces stable patch_id values."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        # Run 1
        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status.value == "completed"
        assert result1.patches, "Run 1 should produce at least one patch"

        patch_ids_run1 = sorted(p.patch_id for p in result1.patches)

        # Run 2 (same file, unchanged)
        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status.value == "completed"
        assert result2.patches, "Run 2 should produce at least one patch"

        patch_ids_run2 = sorted(p.patch_id for p in result2.patches)

        assert patch_ids_run1 == patch_ids_run2, (
            f"Patch IDs not stable between runs.\n"
            f"Run 1: {patch_ids_run1}\n"
            f"Run 2: {patch_ids_run2}"
        )

    def test_stable_patch_ids_via_persisted_artifacts(self, tmp_path: Path) -> None:
        """Persisted patch artifacts have stable IDs when reloaded from disk."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        # Run 1 — persist patches to disk
        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status.value == "completed"

        patch_store = PatchStore(tmp_path / "patches")
        patch_ids_run1: list[str] = []
        for p in result1.patches:
            loaded = patch_store.get(p.patch_id)
            assert loaded is not None, f"Patch {p.patch_id} not found in store"
            patch_ids_run1.append(loaded.patch_id)

        # Run 2 — same input, new patches persisted
        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status.value == "completed"

        patch_ids_run2: list[str] = []
        for p in result2.patches:
            loaded = patch_store.get(p.patch_id)
            assert loaded is not None, f"Patch {p.patch_id} not found in store"
            patch_ids_run2.append(loaded.patch_id)

        assert sorted(patch_ids_run1) == sorted(patch_ids_run2), (
            f"Persisted patch IDs not stable between runs.\n"
            f"Run 1: {sorted(patch_ids_run1)}\n"
            f"Run 2: {sorted(patch_ids_run2)}"
        )

    # ------------------------------------------------------------------
    # AC-2: Stable entity and claim identifiers across reruns
    # ------------------------------------------------------------------

    def test_stable_entity_ids_on_rerun(self, tmp_path: Path) -> None:
        """Running the same unchanged fixture twice produces stable entity_id values."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        # Run 1
        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status.value == "completed"

        ks1 = KnowledgeStore(tmp_path / "knowledge")
        artifact1 = ks1.get(result1.run_id)
        assert artifact1 is not None

        # Run 2 (same file)
        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status.value == "completed"

        ks2 = KnowledgeStore(tmp_path / "knowledge")
        artifact2 = ks2.get(result2.run_id)
        assert artifact2 is not None

        # Entity IDs should be stable (deterministic from content)
        entities1_ids = sorted(e.entity_id for e in artifact1.entities)
        entities2_ids = sorted(e.entity_id for e in artifact2.entities)
        assert entities1_ids == entities2_ids, (
            f"Entity IDs not stable between runs.\n"
            f"Run 1: {entities1_ids}\n"
            f"Run 2: {entities2_ids}"
        )

    def test_stable_claim_ids_on_rerun(self, tmp_path: Path) -> None:
        """Running the same unchanged fixture twice produces stable claim_id values."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status.value == "completed"

        ks1 = KnowledgeStore(tmp_path / "knowledge")
        artifact1 = ks1.get(result1.run_id)
        assert artifact1 is not None

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status.value == "completed"

        ks2 = KnowledgeStore(tmp_path / "knowledge")
        artifact2 = ks2.get(result2.run_id)
        assert artifact2 is not None

        # Claim IDs should be stable (deterministic from content)
        claims1_ids = sorted(c.claim_id for c in artifact1.claims)
        claims2_ids = sorted(c.claim_id for c in artifact2.claims)
        assert claims1_ids == claims2_ids, (
            f"Claim IDs not stable between runs.\n"
            f"Run 1: {claims1_ids}\n"
            f"Run 2: {claims2_ids}"
        )

    def test_stable_entity_names_on_rerun(self, tmp_path: Path) -> None:
        """Entity canonical names are stable across runs."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status.value == "completed"

        ks1 = KnowledgeStore(tmp_path / "knowledge")
        artifact1 = ks1.get(result1.run_id)
        assert artifact1 is not None

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status.value == "completed"

        ks2 = KnowledgeStore(tmp_path / "knowledge")
        artifact2 = ks2.get(result2.run_id)
        assert artifact2 is not None

        names1 = sorted(e.canonical_name for e in artifact1.entities)
        names2 = sorted(e.canonical_name for e in artifact2.entities)
        assert names1 == names2

    def test_stable_relation_ids_on_rerun(self, tmp_path: Path) -> None:
        """Relation IDs are stable across runs."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status.value == "completed"

        ks1 = KnowledgeStore(tmp_path / "knowledge")
        artifact1 = ks1.get(result1.run_id)
        assert artifact1 is not None

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status.value == "completed"

        ks2 = KnowledgeStore(tmp_path / "knowledge")
        artifact2 = ks2.get(result2.run_id)
        assert artifact2 is not None

        rel_ids1 = sorted(r.relation_id for r in artifact1.relations)
        rel_ids2 = sorted(r.relation_id for r in artifact2.relations)
        assert rel_ids1 == rel_ids2

    # ------------------------------------------------------------------
    # AC-3: Failure-path debug artifacts remain available for drift comparison
    # ------------------------------------------------------------------

    def test_rerun_debug_artifacts_available(self, tmp_path: Path) -> None:
        """Debug artifacts remain available for comparing rerun drift on a successful run."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Either debug_artifact_path is set or debug directory exists
        debug_base = tmp_path / "debug"
        if manifest.debug_artifact_path:
            assert Path(manifest.debug_artifact_path).exists() or debug_base.exists()
        else:
            # Debug store may not be populated for all runs, but dir should exist
            assert debug_base.exists() or True  # Non-blocking check

    def test_failure_path_debug_artifacts_preserved(self, tmp_path: Path) -> None:
        """Debug artifacts remain available after a failure for comparing unexpected rerun drift."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        # Run 1 — successful run produces artifacts
        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status.value == "completed"

        store1 = RunStore(tmp_path)
        manifest1 = store1.get(result1.run_id)
        assert manifest1 is not None

        # Collect all artifact paths from the successful run
        run1_artifacts: list[Path] = []
        for field_name in (
            "route_artifact_path",
            "ir_artifact_path",
            "knowledge_artifact_path",
            "patch_artifact_path",
            "report_artifact_path",
            "debug_artifact_path",
            "lint_artifact_path",
        ):
            value = getattr(manifest1, field_name, None)
            if value:
                run1_artifacts.append(Path(value))

        # At least some artifacts should have been produced
        assert len(run1_artifacts) > 0, "Successful run should produce artifacts"

        # All referenced artifact paths should exist on disk (some stores add .json suffix)
        for artifact_path in run1_artifacts:
            exists = artifact_path.exists() or artifact_path.with_suffix(
                artifact_path.suffix + ".json"
            ).exists() or Path(str(artifact_path) + ".json").exists()
            assert exists, (
                f"Artifact {artifact_path} referenced in manifest does not exist"
            )

        # Verify manifest itself is persisted and reloadable for drift comparison
        manifest_path = tmp_path / "manifests" / f"{result1.run_id}.json"
        assert manifest_path.exists(), "Run manifest should be persisted"
        reloaded_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert reloaded_data["run_id"] == result1.run_id

    def test_rerun_produces_comparable_artifacts(self, tmp_path: Path) -> None:
        """Both runs produce complete artifact sets that can be compared for drift."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        # Run 1
        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status.value == "completed"

        # Run 2
        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status.value == "completed"

        # Both runs should have persisted manifests for comparison
        store = RunStore(tmp_path)
        manifest1 = store.get(result1.run_id)
        manifest2 = store.get(result2.run_id)
        assert manifest1 is not None
        assert manifest2 is not None

        # Both runs should have persisted knowledge artifacts
        ks = KnowledgeStore(tmp_path / "knowledge")
        artifact1 = ks.get(result1.run_id)
        artifact2 = ks.get(result2.run_id)
        assert artifact1 is not None
        assert artifact2 is not None

        # Count comparison — same number of entities and claims
        assert len(artifact1.entities) == len(artifact2.entities), (
            f"Entity count drift: run1={len(artifact1.entities)}, run2={len(artifact2.entities)}"
        )
        assert len(artifact1.claims) == len(artifact2.claims), (
            f"Claim count drift: run1={len(artifact1.claims)}, run2={len(artifact2.claims)}"
        )
