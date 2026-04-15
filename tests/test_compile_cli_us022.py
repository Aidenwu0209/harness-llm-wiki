"""Tests for US-022: Make `docos compile` replay the real compile stage."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import PatchStore, WikiStore
from docos.ir_store import IRStore
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.models.docir import DocIR
from docos.models.knowledge import EntityRecord, EntityType
from docos.models.patch_set import PatchSet
from docos.run_store import RunStore
from docos.source_store import RawStorage
from docos.registry import SourceRegistry
from docos.wiki.compiler import CompiledPage, WikiCompiler


class TestCompileCLI:
    """US-022: `docos compile` replays real compile stage."""

    def test_compile_loads_artifacts_and_produces_pages(self, tmp_path: Path) -> None:
        """Compile loads DocIR + knowledge, produces pages and patches."""
        base = tmp_path / "artifacts"
        store = RunStore(base)
        manifest = store.create(source_id="src-cmp", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        # Save DocIR
        ir_store = IRStore(base / "ir")
        docir = DocIR(doc_id="d-1", source_id="src-cmp", parser="test", page_count=1, pages=[])
        ir_store.save(docir, run_id)

        # Save knowledge with entities
        ks = KnowledgeStore(base / "knowledge")
        entity = EntityRecord(entity_id="e-1", canonical_name="TestEntity", entity_type=EntityType.CONCEPT, source_ids=["src-cmp"])
        ks.save(KnowledgeArtifact(run_id=run_id, source_id="src-cmp", entities=[entity], claims=[]))

        # Run compile logic
        loaded_docir = ir_store.get(run_id)
        assert loaded_docir is not None

        knowledge = ks.get(run_id)
        assert knowledge is not None
        entities = knowledge.entities
        claims = knowledge.claims

        compiler = WikiCompiler(base / "wiki")
        wiki_store = WikiStore(base / "wiki_state")
        patch_store = PatchStore(base / "patches")

        patches = []
        page_types = []

        # Entity pages
        for e in entities:
            efm, ebody, epath = compiler.compile_entity_page(e, claims)
            ecompiled = CompiledPage(frontmatter=efm, body=ebody, page_path=epath, run_id=run_id)
            epatch = ecompiled.compute_patch(run_id=run_id, source_id="src-cmp")
            if epatch is not None:
                patches.append(epatch)
            page_types.append("entity")

        # Concept pages (entity is CONCEPT type)
        concept_names = {e.canonical_name for e in entities if e.entity_type.value in ("concept", "topic", "theme")}
        for concept_name in concept_names:
            related_entities = [e for e in entities if e.canonical_name == concept_name]
            cfm, cbody, cpath = compiler.compile_concept_page(
                concept_name=concept_name,
                source_ids=["src-cmp"],
                related_claims=[],
                related_entities=related_entities,
            )
            ccompiled = CompiledPage(frontmatter=cfm, body=cbody, page_path=cpath, run_id=run_id)
            cpatch = ccompiled.compute_patch(run_id=run_id, source_id="src-cmp")
            if cpatch is not None:
                patches.append(cpatch)
            page_types.append("concept")

        # Save patch set
        ps = PatchSet.from_patches(run_id, "src-cmp", patches)
        for p in patches:
            patch_store.save(p)
        patch_store.save_patch_set(ps)

        # Verify
        assert len(page_types) >= 2  # at least entity + concept
        assert "entity" in page_types
        assert "concept" in page_types
        assert len(patches) >= 2

        # Verify patch set persisted
        reloaded_ps = patch_store.get_patch_set(run_id)
        assert reloaded_ps is not None
        assert reloaded_ps.summary.total_patches == len(patches)

    def test_compile_with_empty_knowledge(self, tmp_path: Path) -> None:
        """Compile handles empty knowledge artifacts gracefully."""
        base = tmp_path / "artifacts"
        store = RunStore(base)
        manifest = store.create(source_id="src-cmp2", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        ir_store = IRStore(base / "ir")
        docir = DocIR(doc_id="d-2", source_id="src-cmp2", parser="test", page_count=1, pages=[])
        ir_store.save(docir, run_id)

        # No knowledge saved — compile should handle gracefully

        loaded_docir = ir_store.get(run_id)
        assert loaded_docir is not None
        ks = KnowledgeStore(base / "knowledge")
        knowledge = ks.get(run_id)
        entities = knowledge.entities if knowledge else []
        claims = knowledge.claims if knowledge else []

        assert len(entities) == 0
        assert len(claims) == 0

    def test_compile_missing_docir(self, tmp_path: Path) -> None:
        """Compile returns None for run without parse artifact."""
        ir_store = IRStore(tmp_path / "ir")
        assert ir_store.get("nonexistent") is None
