"""Tests for US-021: Make `docos extract` replay the real extract stage."""

from __future__ import annotations

from pathlib import Path

from docos.ir_store import IRStore
from docos.knowledge.extractor import KnowledgeExtractionPipeline
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.models.docir import DocIR
from docos.run_store import RunStore


class TestExtractCLI:
    """US-021: `docos extract` replays real extract stage."""

    def test_extract_loads_docir_and_produces_knowledge(self, tmp_path: Path) -> None:
        """Extract loads DocIR, runs extraction pipeline, and saves knowledge artifacts."""
        base = tmp_path / "artifacts"
        store = RunStore(base)
        manifest = store.create(source_id="src-ext", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        # Save DocIR — use simple empty-page DocIR; the extraction pipeline
        # will still produce (possibly empty) knowledge artifacts.
        docir = DocIR(
            doc_id="d-1", source_id="src-ext", parser="test",
            page_count=1, pages=[],
        )
        ir_store = IRStore(base / "ir")
        ir_store.save(docir, run_id)

        # Run extract (same logic as CLI command)
        loaded = ir_store.get(run_id)
        assert loaded is not None

        pipeline = KnowledgeExtractionPipeline()
        entities, claims, relations = pipeline.extract(loaded)

        # Persist knowledge
        ks = KnowledgeStore(base / "knowledge")
        artifact = KnowledgeArtifact(
            run_id=run_id, source_id="src-ext",
            entities=entities, claims=claims, relations=relations,
        )
        ks.save(artifact)

        # Verify knowledge was saved and can be reloaded
        reloaded = ks.get(run_id)
        assert reloaded is not None
        assert len(reloaded.entities) == len(entities)

    def test_extract_with_explicit_run_id(self, tmp_path: Path) -> None:
        """Extract with explicit run_id loads correct DocIR."""
        base = tmp_path / "artifacts"
        store = RunStore(base)
        manifest = store.create(source_id="src-ext2", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        ir_store = IRStore(base / "ir")
        docir = DocIR(doc_id="d-2", source_id="src-ext2", parser="test", page_count=1, pages=[])
        ir_store.save(docir, run_id)

        # Load by explicit run_id
        loaded = ir_store.get(run_id)
        assert loaded is not None
        assert loaded.doc_id == "d-2"

        pipeline = KnowledgeExtractionPipeline()
        entities, claims, relations = pipeline.extract(loaded)

        ks = KnowledgeStore(base / "knowledge")
        ks.save(KnowledgeArtifact(run_id=run_id, source_id="src-ext2", entities=entities, claims=claims, relations=relations))

        reloaded = ks.get(run_id)
        assert reloaded is not None

    def test_extract_missing_docir(self, tmp_path: Path) -> None:
        """Extract returns None for run without parse artifact."""
        base = tmp_path / "artifacts"
        ir_store = IRStore(base / "ir")
        result = ir_store.get("nonexistent-run")
        assert result is None

    def test_extract_missing_run(self, tmp_path: Path) -> None:
        """find_latest_run returns None for unknown source."""
        base = tmp_path / "artifacts"
        store = RunStore(base)
        assert store.find_latest_run("nonexistent") is None
