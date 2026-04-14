"""Knowledge extractor — extracts entities, claims, relations from DocIR.

This module provides the extraction interface. Actual extraction logic
may be rule-based, LLM-assisted, or a hybrid.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Protocol

from docos.models.docir import BlockType, DocIR
from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    EvidenceAnchor,
    KnowledgeRelation,
    KnowledgeRelationType,
)


# ---------------------------------------------------------------------------
# Extractor protocol
# ---------------------------------------------------------------------------

class EntityExtractor(Protocol):
    """Protocol for entity extraction strategies."""

    def extract_entities(self, docir: DocIR) -> list[EntityRecord]:
        ...


class ClaimExtractor(Protocol):
    """Protocol for claim extraction strategies."""

    def extract_claims(self, docir: DocIR, entities: list[EntityRecord]) -> list[ClaimRecord]:
        ...


class RelationExtractor(Protocol):
    """Protocol for relation extraction strategies."""

    def extract_relations(
        self,
        docir: DocIR,
        entities: list[EntityRecord],
        claims: list[ClaimRecord],
    ) -> list[KnowledgeRelation]:
        ...


# ---------------------------------------------------------------------------
# Rule-based extractors (v1 baseline)
# ---------------------------------------------------------------------------

def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class RuleBasedEntityExtractor:
    """Extract entities using deterministic rules from DocIR.

    V1 strategy:
    - Title blocks → document entity
    - Heading text patterns → concept entities
    - All content → aggregate for later LLM-based extraction
    """

    def extract_entities(self, docir: DocIR) -> list[EntityRecord]:
        entities: list[EntityRecord] = []

        # Document entity from title
        for block in docir.blocks:
            if block.block_type == BlockType.TITLE and block.text_plain:
                entities.append(EntityRecord(
                    entity_id=_make_id("ent"),
                    canonical_name=block.text_plain.strip()[:200],
                    entity_type=EntityType.DOCUMENT,
                    source_ids=[docir.source_id],
                    defining_description=f"Document: {block.text_plain.strip()[:200]}",
                ))
                break

        # Extract potential concept entities from headings
        seen_headings: set[str] = set()
        for block in docir.blocks:
            if block.block_type == BlockType.HEADING and block.text_plain:
                name = block.text_plain.strip()
                if name and name not in seen_headings and len(name) > 2:
                    seen_headings.add(name)
                    entities.append(EntityRecord(
                        entity_id=_make_id("ent"),
                        canonical_name=name,
                        entity_type=EntityType.CONCEPT,
                        source_ids=[docir.source_id],
                    ))

        return entities


class RuleBasedClaimExtractor:
    """Extract claims using deterministic rules from DocIR.

    V1 strategy:
    - Each heading section → one structural claim
    - All claims start as SUPPORTED with evidence anchors
    """

    def extract_claims(self, docir: DocIR, entities: list[EntityRecord]) -> list[ClaimRecord]:
        claims: list[ClaimRecord] = []

        # Create structural claims from heading sections
        heading_blocks = [b for b in docir.blocks if b.block_type == BlockType.HEADING]

        for heading in heading_blocks:
            # Find paragraph blocks under this heading (same page, higher reading order)
            section_blocks = [
                b for b in docir.blocks
                if b.page_no == heading.page_no
                and b.block_type == BlockType.PARAGRAPH
                and b.reading_order > heading.reading_order
            ]

            if not section_blocks:
                continue

            # Create a claim for the section
            first_para = section_blocks[0]
            text = first_para.text_plain[:300]

            anchor = EvidenceAnchor(
                anchor_id=_make_id("anc"),
                source_id=docir.source_id,
                doc_id=docir.doc_id,
                page_no=first_para.page_no,
                block_id=first_para.block_id,
                quote=text[:100],
                confidence=first_para.confidence,
            )

            claim = ClaimRecord(
                claim_id=_make_id("claim"),
                statement=f"Section '{heading.text_plain.strip()}' discusses: {text[:150]}",
                page_refs=[heading.page_no, first_para.page_no],
                status=ClaimStatus.SUPPORTED,
                evidence_anchors=[anchor],
                supporting_sources=[docir.source_id],
                confidence=min(heading.confidence, first_para.confidence),
            )
            claims.append(claim)

        return claims


class RuleBasedRelationExtractor:
    """Extract relations using deterministic rules.

    V1 strategy:
    - Document entity → mentions each concept entity
    - Claims → mention their source entities
    """

    def extract_relations(
        self,
        docir: DocIR,
        entities: list[EntityRecord],
        claims: list[ClaimRecord],
    ) -> list[KnowledgeRelation]:
        relations: list[KnowledgeRelation] = []

        doc_entities = [e for e in entities if e.entity_type == EntityType.DOCUMENT]
        other_entities = [e for e in entities if e.entity_type != EntityType.DOCUMENT]

        # Document → mentions concepts
        if doc_entities:
            doc_id = doc_entities[0].entity_id
            for ent in other_entities:
                relations.append(KnowledgeRelation(
                    relation_id=_make_id("rel"),
                    relation_type=KnowledgeRelationType.MENTIONS,
                    source_id=doc_id,
                    target_id=ent.entity_id,
                    confidence=0.9,
                ))

        # Claims → mention entities
        for claim in claims:
            for ent in entities:
                if ent.canonical_name.lower() in claim.statement.lower():
                    relations.append(KnowledgeRelation(
                        relation_id=_make_id("rel"),
                        relation_type=KnowledgeRelationType.MENTIONS,
                        source_id=claim.claim_id,
                        target_id=ent.entity_id,
                        confidence=0.7,
                    ))

        return relations


# ---------------------------------------------------------------------------
# Extraction pipeline
# ---------------------------------------------------------------------------

class KnowledgeExtractionPipeline:
    """Run entity → claim → relation extraction in order."""

    def __init__(
        self,
        entity_extractor: EntityExtractor | None = None,
        claim_extractor: ClaimExtractor | None = None,
        relation_extractor: RelationExtractor | None = None,
    ) -> None:
        self._entity_ext = entity_extractor or RuleBasedEntityExtractor()
        self._claim_ext = claim_extractor or RuleBasedClaimExtractor()
        self._relation_ext = relation_extractor or RuleBasedRelationExtractor()

    def extract(self, docir: DocIR) -> tuple[list[EntityRecord], list[ClaimRecord], list[KnowledgeRelation]]:
        """Run the full extraction pipeline.

        Returns:
            Tuple of (entities, claims, relations).
        """
        entities = self._entity_ext.extract_entities(docir)
        claims = self._claim_ext.extract_claims(docir, entities)
        relations = self._relation_ext.extract_relations(docir, entities, claims)
        return entities, claims, relations
