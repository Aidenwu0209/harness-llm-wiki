"""Tests for US-010: Persist knowledge artifacts for extract output.

Acceptance criteria:
- The extract stage writes persisted entity, claim, and relation artifacts for a successful run
- The persisted knowledge artifact can be reloaded by run_id
- The RunManifest links to the knowledge artifact path
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.debug_store import DebugAssetStore
from docos.ir_store import IRStore
from docos.knowledge.extractor import KnowledgeExtractionPipeline
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    KnowledgeRelation,
    KnowledgeRelationType,
)
from docos.pipeline.orchestrator import PipelineOrchestrator
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import RouteDecision
from docos.run_store import RunStore


def _write_text_pdf(path: Path) -> Path:
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\n"
        b"endobj\n"
        b"4 0 obj\n"
        b"<< /Length 44 >>\n"
        b"stream\n"
        b"BT /F1 12 Tf 100 700 Td (Hello World) Tj ET\n"
        b"endstream\n"
        b"endobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _parse_and_extract(tmp_path: Path, run_id: str) -> tuple[DocIR, list[EntityRecord], list[ClaimRecord], list[KnowledgeRelation]]:
    """Helper: parse a PDF, extract knowledge, return all outputs."""
    registry = ParserRegistry()
    registry.register(StdlibPDFParser())

    debug_store = DebugAssetStore(tmp_path / "debug")
    orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

    pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
    decision = RouteDecision(
        selected_route="test",
        primary_parser="stdlib_pdf",
        fallback_parsers=[],
        expected_risks=[],
        post_parse_repairs=[],
        review_policy="default",
    )

    result = orchestrator.execute(
        run_id=run_id,
        source_id="src_know",
        file_path=pdf_path,
        route_decision=decision,
    )
    assert result.success
    assert result.docir is not None

    pipeline = KnowledgeExtractionPipeline()
    entities, claims, relations = pipeline.extract(result.docir)

    return result.docir, entities, claims, relations


# ---------------------------------------------------------------------------
# AC1: Extract writes entity, claim, and relation artifacts
# ---------------------------------------------------------------------------


class TestExtractPersistsKnowledge:
    """The extract stage writes persisted entity, claim, and relation artifacts
    for a successful run."""

    def test_entities_persisted(self, tmp_path: Path) -> None:
        """Entities are written to disk after extraction."""
        run_id = "run_know_1"
        docir, entities, claims, relations = _parse_and_extract(tmp_path, run_id)

        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id=run_id,
            source_id="src_know",
            entities=entities,
            claims=claims,
            relations=relations,
        )
        store.save(artifact)

        # Verify entities file exists
        entities_path = tmp_path / "knowledge" / run_id / "entities.json"
        assert entities_path.exists()
        data = json.loads(entities_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)

    def test_claims_persisted(self, tmp_path: Path) -> None:
        """Claims are written to disk after extraction."""
        run_id = "run_know_2"
        docir, entities, claims, relations = _parse_and_extract(tmp_path, run_id)

        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id=run_id,
            source_id="src_know",
            entities=entities,
            claims=claims,
            relations=relations,
        )
        store.save(artifact)

        claims_path = tmp_path / "knowledge" / run_id / "claims.json"
        assert claims_path.exists()
        data = json.loads(claims_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)

    def test_relations_persisted(self, tmp_path: Path) -> None:
        """Relations are written to disk after extraction."""
        run_id = "run_know_3"
        docir, entities, claims, relations = _parse_and_extract(tmp_path, run_id)

        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id=run_id,
            source_id="src_know",
            entities=entities,
            claims=claims,
            relations=relations,
        )
        store.save(artifact)

        relations_path = tmp_path / "knowledge" / run_id / "relations.json"
        assert relations_path.exists()
        data = json.loads(relations_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)

    def test_meta_persisted(self, tmp_path: Path) -> None:
        """Meta info (run_id, source_id) is written alongside artifacts."""
        run_id = "run_know_4"
        docir, entities, claims, relations = _parse_and_extract(tmp_path, run_id)

        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id=run_id,
            source_id="src_know",
            entities=entities,
            claims=claims,
            relations=relations,
        )
        store.save(artifact)

        meta_path = tmp_path / "knowledge" / run_id / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["run_id"] == run_id
        assert meta["source_id"] == "src_know"


# ---------------------------------------------------------------------------
# AC2: Persisted knowledge artifact can be reloaded by run_id
# ---------------------------------------------------------------------------


class TestReloadKnowledgeByRunId:
    """The persisted knowledge artifact can be reloaded by run_id."""

    def test_reload_artifact_from_fresh_store(self, tmp_path: Path) -> None:
        """A new KnowledgeStore can reload the artifact by run_id."""
        run_id = "run_reload_know"
        docir, entities, claims, relations = _parse_and_extract(tmp_path, run_id)

        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id=run_id,
            source_id="src_know",
            entities=entities,
            claims=claims,
            relations=relations,
        )
        store.save(artifact)

        # New store instance (simulates new process)
        new_store = KnowledgeStore(tmp_path / "knowledge")
        loaded = new_store.get(run_id)
        assert loaded is not None
        assert loaded.run_id == run_id
        assert loaded.source_id == "src_know"

    def test_reload_preserves_entity_count(self, tmp_path: Path) -> None:
        """Reloaded artifact has the same entity count."""
        run_id = "run_reload_count"
        docir, entities, claims, relations = _parse_and_extract(tmp_path, run_id)

        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id=run_id,
            source_id="src_know",
            entities=entities,
            claims=claims,
            relations=relations,
        )
        store.save(artifact)

        new_store = KnowledgeStore(tmp_path / "knowledge")
        loaded = new_store.get(run_id)
        assert loaded is not None
        assert len(loaded.entities) == len(entities)
        assert len(loaded.claims) == len(claims)
        assert len(loaded.relations) == len(relations)

    def test_exists_check(self, tmp_path: Path) -> None:
        """KnowledgeStore.exists() works correctly."""
        run_id = "run_know_exists"
        store = KnowledgeStore(tmp_path / "knowledge")
        assert not store.exists(run_id)

        docir, entities, claims, relations = _parse_and_extract(tmp_path, run_id)
        artifact = KnowledgeArtifact(
            run_id=run_id,
            source_id="src_know",
            entities=entities,
            claims=claims,
            relations=relations,
        )
        store.save(artifact)
        assert store.exists(run_id)


# ---------------------------------------------------------------------------
# AC3: RunManifest links to the knowledge artifact path
# ---------------------------------------------------------------------------


class TestManifestLinksKnowledge:
    """The RunManifest links to the knowledge artifact path."""

    def test_manifest_knowledge_path_set(self, tmp_path: Path) -> None:
        """RunManifest.knowledge_artifact_path points to knowledge dir."""
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_know",
            source_hash="a" * 64,
            source_file_path=str(tmp_path / "doc.pdf"),
        )

        run_id = manifest.run_id
        docir, entities, claims, relations = _parse_and_extract(tmp_path, run_id)

        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id=run_id,
            source_id="src_know",
            entities=entities,
            claims=claims,
            relations=relations,
        )
        store.save(artifact)

        knowledge_path = str(tmp_path / "knowledge" / run_id)
        manifest.knowledge_artifact_path = knowledge_path
        run_store.update(manifest)

        loaded = run_store.get(run_id)
        assert loaded is not None
        assert loaded.knowledge_artifact_path is not None
        assert Path(loaded.knowledge_artifact_path).exists()

    def test_manifest_survives_reload(self, tmp_path: Path) -> None:
        """A new RunStore can reload the manifest with knowledge link."""
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_know",
            source_hash="b" * 64,
            source_file_path=str(tmp_path / "doc.pdf"),
        )

        run_id = manifest.run_id
        docir, entities, claims, relations = _parse_and_extract(tmp_path, run_id)

        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id=run_id,
            source_id="src_know",
            entities=entities,
            claims=claims,
            relations=relations,
        )
        store.save(artifact)

        knowledge_path = str(tmp_path / "knowledge" / run_id)
        manifest.knowledge_artifact_path = knowledge_path
        run_store.update(manifest)

        # New store instance
        new_store = RunStore(tmp_path)
        loaded = new_store.get(run_id)
        assert loaded is not None
        assert loaded.knowledge_artifact_path == knowledge_path
