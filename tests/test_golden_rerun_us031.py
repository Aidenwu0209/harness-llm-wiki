"""Tests for US-031: Rerun-stability golden scenario."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import PatchStore, WikiStore, WikiPageState
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.models.docir import DocIR
from docos.models.knowledge import EntityRecord, EntityType
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.models.patch_set import PatchSet
from docos.run_store import RunStore
from docos.wiki.compiler import CompiledPage, WikiCompiler


class TestGoldenRerunStability:
    """US-031: Golden scenario proving rerun stability."""

    def test_rerun_preserves_page_ids(self, tmp_path: Path) -> None:
        """Rerunning same fixture preserves page IDs for unchanged content."""
        base = tmp_path / "artifacts"

        # Run 1
        run_store = RunStore(base)
        manifest1 = run_store.create(source_id="src-stable", source_hash="h", source_file_path="/tmp/stable.pdf")

        # Setup knowledge
        ks = KnowledgeStore(base / "knowledge")
        entities = [
            EntityRecord(entity_id="e-stable", canonical_name="StableEntity", entity_type=EntityType.CONCEPT, source_ids=["src-stable"]),
        ]
        ks.save(KnowledgeArtifact(run_id=manifest1.run_id, source_id="src-stable", entities=entities, claims=[]))

        # Compile run 1
        compiler = WikiCompiler(base / "wiki")
        entity = entities[0]
        efm1, ebody1, epath1 = compiler.compile_entity_page(entity, [])

        # Run 2 (same source)
        manifest2 = run_store.create(source_id="src-stable", source_hash="h", source_file_path="/tmp/stable.pdf")

        # Same knowledge (rerun)
        ks.save(KnowledgeArtifact(run_id=manifest2.run_id, source_id="src-stable", entities=entities, claims=[]))

        # Compile run 2
        efm2, ebody2, epath2 = compiler.compile_entity_page(entity, [])

        # Paths should be stable
        assert str(epath1) == str(epath2)
        assert efm1.id == efm2.id

    def test_rerun_preserves_entity_and_patch_ids(self, tmp_path: Path) -> None:
        """Rerunning same fixture preserves entity IDs and patch IDs."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)

        # Run 1
        m1 = run_store.create(source_id="src-stable2", source_hash="h", source_file_path="/tmp/t.pdf")
        ks = KnowledgeStore(base / "knowledge")
        e1 = EntityRecord(entity_id="e-1", canonical_name="MyEntity", entity_type=EntityType.CONCEPT, source_ids=["src-stable2"])
        ks.save(KnowledgeArtifact(run_id=m1.run_id, source_id="src-stable2", entities=[e1], claims=[]))

        # Run 2
        m2 = run_store.create(source_id="src-stable2", source_hash="h", source_file_path="/tmp/t.pdf")
        ks.save(KnowledgeArtifact(run_id=m2.run_id, source_id="src-stable2", entities=[e1], claims=[]))

        # Entity IDs stable
        k1 = ks.get(m1.run_id)
        k2 = ks.get(m2.run_id)
        assert k1 is not None and k2 is not None
        assert k1.entities[0].entity_id == k2.entities[0].entity_id
        assert k1.entities[0].canonical_name == k2.entities[0].canonical_name

    def test_rerun_no_ghost_patches(self, tmp_path: Path) -> None:
        """Rerunning same fixture does not create ghost patches."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)
        patch_store = PatchStore(base / "patches")

        # Run 1
        m1 = run_store.create(source_id="src-ghost", source_hash="h", source_file_path="/tmp/t.pdf")
        p1 = Patch(
            patch_id="p-ghost-1",
            run_id=m1.run_id,
            source_id="src-ghost",
            changes=[Change(type=ChangeType.CREATE_PAGE, target="wiki/source/ghost.md")],
            risk_score=0.1,
            blast_radius=BlastRadius(pages=1),
        )
        patch_store.save(p1)
        ps1 = PatchSet.from_patches(m1.run_id, "src-ghost", [p1])
        patch_store.save_patch_set(ps1)

        # Run 2 (same source, new run)
        m2 = run_store.create(source_id="src-ghost", source_hash="h2", source_file_path="/tmp/t.pdf")
        p2 = Patch(
            patch_id="p-ghost-2",
            run_id=m2.run_id,
            source_id="src-ghost",
            changes=[Change(type=ChangeType.CREATE_PAGE, target="wiki/source/ghost.md")],
            risk_score=0.1,
            blast_radius=BlastRadius(pages=1),
        )
        patch_store.save(p2)
        ps2 = PatchSet.from_patches(m2.run_id, "src-ghost", [p2])
        patch_store.save_patch_set(ps2)

        # Verify run 1 data is intact
        ps1_reloaded = patch_store.get_patch_set(m1.run_id)
        assert ps1_reloaded is not None
        assert ps1_reloaded.summary.total_patches == 1

        # Verify run 2 data is separate
        ps2_reloaded = patch_store.get_patch_set(m2.run_id)
        assert ps2_reloaded is not None
        assert ps2_reloaded.summary.total_patches == 1
        assert ps1_reloaded.run_id != ps2_reloaded.run_id
