"""Knowledge extractor — extracts entities, claims, relations from DocIR.

This module provides the extraction interface. Actual extraction logic
may be rule-based, LLM-assisted, or a hybrid.
"""

from __future__ import annotations

import hashlib
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


def _deterministic_id(prefix: str, *components: str) -> str:
    """Generate a deterministic ID from stable content inputs.

    Uses SHA-256 of concatenated components to produce a stable hash.
    Same inputs always produce the same ID.
    """
    payload = "|".join(components)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


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
                    entity_id=_deterministic_id("ent", "document", docir.source_id, block.text_plain.strip()),
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
                        entity_id=_deterministic_id("ent", "concept", docir.source_id, name),
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
        # Sort all blocks by (page_no, reading_order) for sequential scan
        sorted_blocks = sorted(docir.blocks, key=lambda b: (b.page_no, b.reading_order))
        heading_blocks = [b for b in sorted_blocks if b.block_type == BlockType.HEADING]

        for idx, heading in enumerate(heading_blocks):
            # Determine the boundary: next heading or end of document
            if idx + 1 < len(heading_blocks):
                next_heading = heading_blocks[idx + 1]
                # Section includes blocks from this heading up to (not including) next heading
                section_blocks = [
                    b for b in sorted_blocks
                    if (b.page_no, b.reading_order) >= (heading.page_no, heading.reading_order)
                    and (b.page_no, b.reading_order) < (next_heading.page_no, next_heading.reading_order)
                    and b.block_type == BlockType.PARAGRAPH
                ]
            else:
                # Last heading: section extends to end of document
                section_blocks = [
                    b for b in sorted_blocks
                    if (b.page_no, b.reading_order) >= (heading.page_no, heading.reading_order)
                    and b.block_type == BlockType.PARAGRAPH
                ]

            # Also include table/figure evidence blocks in the section
            evidence_blocks = [
                b for b in sorted_blocks
                if (b.page_no, b.reading_order) >= (heading.page_no, heading.reading_order)
                and (idx + 1 >= len(heading_blocks) or (b.page_no, b.reading_order) < (heading_blocks[idx + 1].page_no, heading_blocks[idx + 1].reading_order))
                and b.block_type in (BlockType.TABLE, BlockType.FIGURE)
            ]

            if not section_blocks:
                continue

            # Create anchors from section paragraphs and evidence blocks
            first_para = section_blocks[0]
            text = " ".join(b.text_plain[:100] for b in section_blocks[:3])[:300]

            anchor_blocks = section_blocks + evidence_blocks
            anchors = [
                EvidenceAnchor(
                    anchor_id=_deterministic_id("anc", docir.source_id, b.block_id, str(b.page_no)),
                    source_id=docir.source_id,
                    doc_id=docir.doc_id,
                    page_no=b.page_no,
                    block_id=b.block_id,
                    quote=b.text_plain[:100],
                    confidence=b.confidence,
                )
                for b in anchor_blocks
            ]

            anchor = EvidenceAnchor(
                anchor_id=_deterministic_id("anc", docir.source_id, first_para.block_id, str(first_para.page_no)),
                source_id=docir.source_id,
                doc_id=docir.doc_id,
                page_no=first_para.page_no,
                block_id=first_para.block_id,
                quote=text[:100],
                confidence=first_para.confidence,
            )

            claim = ClaimRecord(
                claim_id=_deterministic_id("claim", docir.source_id, heading.block_id, text[:50]),
                statement=f"Section '{heading.text_plain.strip()}' discusses: {text[:150]}",
                page_refs=list({b.page_no for b in anchor_blocks}),
                status=ClaimStatus.SUPPORTED,
                evidence_anchors=anchors,
                supporting_sources=[docir.source_id],
                confidence=min((b.confidence for b in anchor_blocks), default=1.0),
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
                    relation_id=_deterministic_id("rel", "mentions", doc_id, ent.entity_id),
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
                        relation_id=_deterministic_id("rel", "claim_mention", claim.claim_id, ent.entity_id),
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
