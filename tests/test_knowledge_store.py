"""Tests for Knowledge Store — entity/claim/relation artifact persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    EvidenceAnchor,
    KnowledgeRelation,
    KnowledgeRelationType,
)
from docos.run_store import RunStore


def _make_entity(entity_id: str = "ent_1", name: str = "Test Entity") -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        canonical_name=name,
        entity_type=EntityType.CONCEPT,
        source_ids=["src_test"],
    )


def _make_claim(claim_id: str = "clm_1") -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        statement="Test claim statement",
        evidence_anchors=[
            EvidenceAnchor(
                anchor_id="anc_1",
                source_id="src_test",
                doc_id="doc_test",
                page_no=1,
                block_id="blk_1",
            )
        ],
    )


def _make_relation(relation_id: str = "rel_1") -> KnowledgeRelation:
    return KnowledgeRelation(
        relation_id=relation_id,
        relation_type=KnowledgeRelationType.MENTIONS,
        source_id="ent_1",
        target_id="ent_2",
    )


class TestKnowledgeStore:
    def test_save_and_retrieve(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id="run_abc",
            source_id="src_test",
            entities=[_make_entity()],
            claims=[_make_claim()],
            relations=[_make_relation()],
        )
        store.save(artifact)

        loaded = store.get("run_abc")
        assert loaded is not None
        assert loaded.run_id == "run_abc"
        assert loaded.source_id == "src_test"
        assert len(loaded.entities) == 1
        assert loaded.entities[0].canonical_name == "Test Entity"
        assert len(loaded.claims) == 1
        assert loaded.claims[0].statement == "Test claim statement"
        assert len(loaded.relations) == 1

    def test_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path / "knowledge")
        assert store.get("run_missing") is None

    def test_exists(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path / "knowledge")
        assert not store.exists("run_check")
        artifact = KnowledgeArtifact(run_id="run_check", source_id="src_x")
        store.save(artifact)
        assert store.exists("run_check")

    def test_empty_artifact_round_trip(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(run_id="run_empty", source_id="src_y")
        store.save(artifact)

        loaded = store.get("run_empty")
        assert loaded is not None
        assert loaded.entities == []
        assert loaded.claims == []
        assert loaded.relations == []

    def test_reload_after_new_process(self, tmp_path: Path) -> None:
        store1 = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id="run_restart",
            source_id="src_restart",
            entities=[_make_entity("ent_r1", "Entity Restart")],
            claims=[_make_claim("clm_r1")],
        )
        store1.save(artifact)

        store2 = KnowledgeStore(tmp_path / "knowledge")
        loaded = store2.get("run_restart")
        assert loaded is not None
        assert loaded.entities[0].canonical_name == "Entity Restart"

    def test_manifest_links_knowledge_artifact(self, tmp_path: Path) -> None:
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_test",
            source_hash="a" * 64,
            source_file_path="/tmp/test.pdf",
        )

        ks = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(
            run_id=manifest.run_id,
            source_id="src_test",
            entities=[_make_entity()],
        )
        ks_path = ks.save(artifact)

        manifest.knowledge_artifact_path = str(ks_path)
        run_store.update(manifest)

        loaded = run_store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.knowledge_artifact_path is not None

    def test_save_creates_directory_structure(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path / "knowledge")
        artifact = KnowledgeArtifact(run_id="run_dirs", source_id="src_z")
        ks_path = store.save(artifact)

        assert (ks_path / "entities.json").exists()
        assert (ks_path / "claims.json").exists()
        assert (ks_path / "relations.json").exists()
        assert (ks_path / "meta.json").exists()
