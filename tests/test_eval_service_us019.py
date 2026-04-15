"""Tests for US-019: Shared eval service for run and CLI parity."""

from __future__ import annotations

from pathlib import Path

from docos.harness.service import run_eval_for_run
from docos.run_store import RunStore


class TestSharedEvalService:
    """US-019: Pipeline and CLI use same eval service."""

    def test_service_returns_report_for_valid_run(self, tmp_path: Path) -> None:
        """Service loads real data and produces a harness report."""
        base = tmp_path / "artifacts"
        store = RunStore(base)
        manifest = store.create(source_id="src-eval", source_hash="h", source_file_path="/tmp/t.pdf")

        report = run_eval_for_run(base, manifest.run_id)
        assert report is not None
        assert report.run_id == manifest.run_id

    def test_service_returns_none_for_missing_run(self, tmp_path: Path) -> None:
        """Service returns None for non-existent run."""
        report = run_eval_for_run(tmp_path / "artifacts", "nonexistent")
        assert report is None

    def test_service_uses_real_artifacts(self, tmp_path: Path) -> None:
        """Service loads DocIR, knowledge, and patches from stores."""
        from docos.artifact_stores import PatchStore
        from docos.ir_store import IRStore
        from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
        from docos.models.docir import DocIR
        from docos.models.knowledge import EntityRecord, EntityType
        from docos.models.patch import BlastRadius, Change, ChangeType, Patch
        from docos.models.patch_set import PatchSet

        base = tmp_path / "artifacts"
        store = RunStore(base)
        manifest = store.create(source_id="src-eval2", source_hash="h", source_file_path="/tmp/t.pdf")

        # Save DocIR
        ir_store = IRStore(base / "ir")
        docir = DocIR(doc_id="d-1", source_id="src-eval2", parser="test", page_count=1, pages=[])
        ir_store.save(docir, manifest.run_id)

        # Save knowledge
        ks = KnowledgeStore(base / "knowledge")
        ks.save(KnowledgeArtifact(
            run_id=manifest.run_id, source_id="src-eval2",
            entities=[EntityRecord(entity_id="e-1", canonical_name="Test", entity_type=EntityType.CONCEPT, source_ids=["src-eval2"])],
            claims=[],
        ))

        # Save patches
        patch_store = PatchStore(base / "patches")
        p = Patch(patch_id="p-1", run_id=manifest.run_id, source_id="src-eval2",
                  changes=[Change(type=ChangeType.CREATE_PAGE, target="t.md")],
                  risk_score=0.3, blast_radius=BlastRadius(pages=1))
        ps = PatchSet.from_patches(manifest.run_id, "src-eval2", [p])
        patch_store.save(p)
        patch_store.save_patch_set(ps)

        report = run_eval_for_run(base, manifest.run_id)
        assert report is not None
        metrics = report.maintenance_quality.metrics
        assert metrics.get("entity_count") == 1
        assert metrics.get("total_patches") == 1
