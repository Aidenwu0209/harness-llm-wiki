"""Tests for Knowledge Extraction (US-014, US-015, US-016)."""

import pytest
from pydantic import ValidationError

from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    EvidenceAnchor,
    KnowledgeRelation,
    KnowledgeRelationType,
)
from docos.knowledge.extractor import (
    KnowledgeExtractionPipeline,
    RuleBasedClaimExtractor,
    RuleBasedEntityExtractor,
    RuleBasedRelationExtractor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _docir_with_content() -> DocIR:
    """Build a small but realistic DocIR for testing."""
    blocks = [
        Block(
            block_id="title", page_no=1, block_type=BlockType.TITLE,
            reading_order=0, bbox=(0, 0, 500, 50),
            text_plain="READOC: A Benchmark for Document Structure Extraction",
            source_parser="test", source_node_id="n0",
        ),
        Block(
            block_id="h1", page_no=1, block_type=BlockType.HEADING,
            reading_order=1, bbox=(0, 60, 500, 90),
            text_plain="Introduction", text_md="## Introduction",
            source_parser="test", source_node_id="n1",
        ),
        Block(
            block_id="p1", page_no=1, block_type=BlockType.PARAGRAPH,
            reading_order=2, bbox=(0, 100, 500, 300),
            text_plain="Document structure extraction requires balancing global and local fidelity.",
            source_parser="test", source_node_id="n2",
        ),
        Block(
            block_id="h2", page_no=1, block_type=BlockType.HEADING,
            reading_order=3, bbox=(0, 310, 500, 340),
            text_plain="Methodology", text_md="## Methodology",
            source_parser="test", source_node_id="n3",
        ),
        Block(
            block_id="p2", page_no=1, block_type=BlockType.PARAGRAPH,
            reading_order=4, bbox=(0, 350, 500, 500),
            text_plain="We propose an end-to-end approach using transformer models.",
            source_parser="test", source_node_id="n4",
        ),
    ]
    page = Page(page_no=1, width=612, height=792, blocks=["title", "h1", "p1", "h2", "p2"])
    return DocIR(
        doc_id="doc_test", source_id="src_test",
        parser="test", page_count=1,
        pages=[page], blocks=blocks,
    )


# ---------------------------------------------------------------------------
# US-014: Entity extraction
# ---------------------------------------------------------------------------

class TestEntityExtraction:
    def test_extracts_document_entity(self) -> None:
        docir = _docir_with_content()
        ext = RuleBasedEntityExtractor()
        entities = ext.extract_entities(docir)

        doc_entities = [e for e in entities if e.entity_type == EntityType.DOCUMENT]
        assert len(doc_entities) >= 1
        assert "READOC" in doc_entities[0].canonical_name

    def test_extracts_concept_entities(self) -> None:
        docir = _docir_with_content()
        ext = RuleBasedEntityExtractor()
        entities = ext.extract_entities(docir)

        concepts = [e for e in entities if e.entity_type == EntityType.CONCEPT]
        names = {e.canonical_name for e in concepts}
        assert "Introduction" in names
        assert "Methodology" in names

    def test_preserves_aliases_no_merge(self) -> None:
        e1 = EntityRecord(entity_id="e1", canonical_name="READOC", entity_type=EntityType.BENCHMARK, aliases=["Readoc"])
        e2 = EntityRecord(entity_id="e2", canonical_name="Readoc Benchmark", entity_type=EntityType.BENCHMARK)
        assert e1.entity_id != e2.entity_id
        assert "Readoc" in e1.aliases

    def test_source_ids_populated(self) -> None:
        docir = _docir_with_content()
        ext = RuleBasedEntityExtractor()
        entities = ext.extract_entities(docir)
        assert all("src_test" in e.source_ids for e in entities)

    def test_all_entity_types(self) -> None:
        for et in EntityType:
            e = EntityRecord(entity_id=f"e_{et.value}", canonical_name="Test", entity_type=et)
            assert e.entity_type == et


# ---------------------------------------------------------------------------
# US-015: Claim extraction
# ---------------------------------------------------------------------------

class TestClaimExtraction:
    def test_extracts_claims_from_sections(self) -> None:
        docir = _docir_with_content()
        entities = RuleBasedEntityExtractor().extract_entities(docir)
        ext = RuleBasedClaimExtractor()
        claims = ext.extract_claims(docir, entities)
        assert len(claims) >= 1

    def test_claims_have_evidence_anchors(self) -> None:
        docir = _docir_with_content()
        entities = RuleBasedEntityExtractor().extract_entities(docir)
        claims = RuleBasedClaimExtractor().extract_claims(docir, entities)
        for claim in claims:
            assert len(claim.evidence_anchors) >= 1

    def test_claims_link_to_source(self) -> None:
        docir = _docir_with_content()
        entities = RuleBasedEntityExtractor().extract_entities(docir)
        claims = RuleBasedClaimExtractor().extract_claims(docir, entities)
        for claim in claims:
            assert "src_test" in claim.supporting_sources

    def test_claim_status_fields(self) -> None:
        claim = ClaimRecord(
            claim_id="c1",
            statement="Test statement",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[
                EvidenceAnchor(
                    anchor_id="a1", source_id="s1", doc_id="d1",
                    page_no=1, block_id="b1",
                )
            ],
        )
        assert claim.status == ClaimStatus.SUPPORTED

    def test_all_claim_statuses(self) -> None:
        for cs in ClaimStatus:
            assert isinstance(cs.value, str)


# ---------------------------------------------------------------------------
# US-016: Evidence and inference validation
# ---------------------------------------------------------------------------

class TestEvidenceValidation:
    def test_supported_claim_without_anchor_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must have at least one evidence anchor"):
            ClaimRecord(
                claim_id="c_bad",
                statement="Unsupported claim",
                status=ClaimStatus.SUPPORTED,
            )

    def test_inferred_claim_without_note_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must have an inference_note"):
            ClaimRecord(
                claim_id="c_inf",
                statement="Inferred claim",
                status=ClaimStatus.INFERRED,
            )

    def test_inferred_claim_with_note_accepted(self) -> None:
        claim = ClaimRecord(
            claim_id="c_inf_ok",
            statement="Inferred claim",
            status=ClaimStatus.INFERRED,
            inference_note="Derived from pattern in multiple sources",
        )
        assert claim.status == ClaimStatus.INFERRED

    def test_conflicted_claim_without_sources_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must reference conflicting sources"):
            ClaimRecord(
                claim_id="c_conf",
                statement="Conflicted claim",
                status=ClaimStatus.CONFLICTED,
            )

    def test_conflicted_claim_with_sources_accepted(self) -> None:
        claim = ClaimRecord(
            claim_id="c_conf_ok",
            statement="Conflicted claim",
            status=ClaimStatus.CONFLICTED,
            conflicting_sources=["src_001", "src_002"],
        )
        assert claim.status == ClaimStatus.CONFLICTED

    def test_supported_claim_with_anchor_accepted(self) -> None:
        claim = ClaimRecord(
            claim_id="c_ok",
            statement="Supported claim",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[
                EvidenceAnchor(
                    anchor_id="a1", source_id="s1", doc_id="d1",
                    page_no=1, block_id="b1", quote="Evidence text",
                )
            ],
        )
        assert len(claim.evidence_anchors) == 1


# ---------------------------------------------------------------------------
# Relation extraction
# ---------------------------------------------------------------------------

class TestRelationExtraction:
    def test_extracts_mention_relations(self) -> None:
        docir = _docir_with_content()
        entities = RuleBasedEntityExtractor().extract_entities(docir)
        claims = RuleBasedClaimExtractor().extract_claims(docir, entities)
        ext = RuleBasedRelationExtractor()
        relations = ext.extract_relations(docir, entities, claims)
        assert len(relations) >= 1

    def test_relation_types(self) -> None:
        for rt in KnowledgeRelationType:
            r = KnowledgeRelation(
                relation_id=f"r_{rt.value}",
                relation_type=rt,
                source_id="e1",
                target_id="e2",
            )
            assert r.relation_type == rt


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

class TestExtractionPipeline:
    def test_full_pipeline(self) -> None:
        docir = _docir_with_content()
        pipeline = KnowledgeExtractionPipeline()
        entities, claims, relations = pipeline.extract(docir)

        assert len(entities) >= 1
        assert len(claims) >= 1
        assert len(relations) >= 1

    def test_pipeline_output_consistency(self) -> None:
        docir = _docir_with_content()
        pipeline = KnowledgeExtractionPipeline()
        entities, claims, relations = pipeline.extract(docir)

        # All entity IDs are unique
        ent_ids = [e.entity_id for e in entities]
        assert len(ent_ids) == len(set(ent_ids))

        # All claims have evidence (since rule-based always creates SUPPORTED)
        for c in claims:
            assert len(c.evidence_anchors) >= 1
