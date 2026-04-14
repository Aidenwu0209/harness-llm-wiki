"""Knowledge models — Entity, Claim, Relation, Evidence Anchor.

These models form the Knowledge Truth layer: structured, evidence-backed
knowledge objects extracted from canonical DocIR.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Entity types (v1)
# ---------------------------------------------------------------------------

class EntityType(str, Enum):
    """Supported entity types."""

    PERSON = "person"
    ORGANIZATION = "organization"
    PRODUCT = "product"
    MODEL = "model"
    METHOD = "method"
    BENCHMARK = "benchmark"
    DATASET = "dataset"
    CONCEPT = "concept"
    METRIC = "metric"
    PARSER = "parser"
    FAILURE_MODE = "failure_mode"
    DECISION = "decision"
    DOCUMENT = "document"


# ---------------------------------------------------------------------------
# Claim status
# ---------------------------------------------------------------------------

class ClaimStatus(str, Enum):
    """Status of a knowledge claim."""

    SUPPORTED = "supported"
    INFERRED = "inferred"
    CONFLICTED = "conflicted"
    DEPRECATED = "deprecated"
    NEEDS_REVIEW = "needs_review"


# ---------------------------------------------------------------------------
# Evidence Anchor
# ---------------------------------------------------------------------------

class EvidenceAnchor(BaseModel):
    """A pointer to evidence in the source document.

    Every supported claim must have at least one anchor.
    """

    anchor_id: str = Field(description="Unique anchor identifier")
    source_id: str
    doc_id: str
    page_no: int = Field(ge=1)
    block_id: str
    bbox: tuple[float, float, float, float] | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str = Field(default="", description="Short excerpt of the evidence")
    render_uri: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------

class EntityRecord(BaseModel):
    """A recognized entity extracted from documents.

    Invariants:
    - Candidate aliases are preserved without implicit merging.
    - Each entity links back to supporting sources and claims.
    """

    entity_id: str
    canonical_name: str
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)
    defining_description: str = ""

    # Provenance
    source_ids: list[str] = Field(default_factory=list, description="Source documents mentioning this entity")
    first_seen_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Cross-references
    related_entity_ids: list[str] = Field(default_factory=list)
    related_claim_ids: list[str] = Field(default_factory=list)

    # Dedup
    candidate_duplicates: list[str] = Field(
        default_factory=list,
        description="Entity IDs that might be the same (requires review)",
    )
    merged_into: str | None = Field(
        default=None,
        description="If this entity was merged into another, its ID",
    )


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

class ClaimRecord(BaseModel):
    """A structured knowledge claim extracted from documents.

    Invariants:
    - supported claim → must have >=1 evidence anchor
    - inferred claim → must have inference_note
    - conflicted claim → must have conflicting_sources
    """

    claim_id: str
    statement: str
    subject_entity_id: str | None = None
    predicate: str = ""
    object_value: str = Field(default="", alias="object")

    # Evidence
    evidence_anchors: list[EvidenceAnchor] = Field(default_factory=list)
    page_refs: list[int] = Field(default_factory=list)

    # Status
    status: ClaimStatus = ClaimStatus.SUPPORTED
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # Source tracking
    supporting_sources: list[str] = Field(default_factory=list)
    conflicting_sources: list[str] = Field(default_factory=list)

    # Inference
    inference_note: str | None = None

    # Temporal
    updated_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="after")
    def _validate_status_constraints(self) -> "ClaimRecord":
        """Enforce evidence and inference rules based on claim status."""
        if self.status == ClaimStatus.SUPPORTED and not self.evidence_anchors:
            msg = f"Supported claim {self.claim_id} must have at least one evidence anchor"
            raise ValueError(msg)
        if self.status == ClaimStatus.INFERRED and not self.inference_note:
            msg = f"Inferred claim {self.claim_id} must have an inference_note"
            raise ValueError(msg)
        if self.status == ClaimStatus.CONFLICTED and not self.conflicting_sources:
            msg = f"Conflicted claim {self.claim_id} must reference conflicting sources"
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# Knowledge Relation
# ---------------------------------------------------------------------------

class KnowledgeRelationType(str, Enum):
    """Types of relations between knowledge objects."""

    USES = "uses"
    EVALUATED_ON = "evaluated_on"
    COMPARES = "compares"
    DERIVES_FROM = "derives_from"
    CONTRADICTS = "contradicts"
    SUPPORTS = "supports"
    MENTIONS = "mentions"
    PART_OF = "part_of"
    SUPERSEDES = "supersedes"


class KnowledgeRelation(BaseModel):
    """A typed relation between entities or claims."""

    relation_id: str
    relation_type: KnowledgeRelationType
    source_id: str = Field(description="Subject entity/claim ID")
    target_id: str = Field(description="Object entity/claim ID")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_anchors: list[EvidenceAnchor] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
