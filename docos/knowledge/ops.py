"""Knowledge ops — conflict management, entity dedup, deprecation workflows.

These operations maintain knowledge integrity over time:
- Conflict marking preserves both sides of evidence
- Entity dedup uses candidate-based workflow (no implicit merge)
- Deprecation preserves history with replacement links
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord


# ---------------------------------------------------------------------------
# Conflict management
# ---------------------------------------------------------------------------

class ConflictMarker(BaseModel):
    """Records a conflict between claims from different sources."""

    conflict_id: str
    claim_ids: list[str] = Field(min_length=2, description="At least 2 conflicting claims")
    source_ids: list[str] = Field(default_factory=list)
    description: str = ""
    detected_at: datetime = Field(default_factory=datetime.now)
    resolved: bool = False
    resolution_note: str | None = None

    def resolve(self, note: str) -> None:
        self.resolved = True
        self.resolution_note = note


def mark_conflict(claims: list[ClaimRecord], description: str = "") -> ConflictMarker:
    """Mark a set of claims as conflicting.

    Both sides of evidence are preserved — neither is silently overwritten.
    """
    from docos.knowledge.extractor import _make_id
    conflict = ConflictMarker(
        conflict_id=_make_id("conflict"),
        claim_ids=[c.claim_id for c in claims],
        source_ids=list({s for c in claims for s in c.supporting_sources}),
        description=description,
    )
    return conflict


# ---------------------------------------------------------------------------
# Entity dedup
# ---------------------------------------------------------------------------

class DedupCandidate(BaseModel):
    """A candidate pair for entity deduplication."""

    candidate_id: str
    entity_a_id: str
    entity_b_id: str
    similarity_score: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    status: Literal["pending", "merged", "kept_separate"] = "pending"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    def merge(self, reviewer: str) -> None:
        """Approve the merge."""
        self.status = "merged"
        self.reviewed_by = reviewer
        self.reviewed_at = datetime.now()

    def keep_separate(self, reviewer: str) -> None:
        """Reject the merge — keep entities separate."""
        self.status = "kept_separate"
        self.reviewed_by = reviewer
        self.reviewed_at = datetime.now()


def generate_dedup_candidates(entities: list[EntityRecord]) -> list[DedupCandidate]:
    """Generate dedup candidates based on name similarity.

    This is candidate-based — no implicit merging.
    Each candidate requires human review before merging.
    """
    from docos.knowledge.extractor import _make_id

    candidates: list[DedupCandidate] = []
    for i, a in enumerate(entities):
        for b in entities[i + 1:]:
            if a.entity_type != b.entity_type:
                continue
            score = _name_similarity(a.canonical_name, b.canonical_name)
            if score >= 0.3:
                candidates.append(DedupCandidate(
                    candidate_id=_make_id("dedup"),
                    entity_a_id=a.entity_id,
                    entity_b_id=b.entity_id,
                    similarity_score=score,
                    reason=f"Similar names: '{a.canonical_name}' vs '{b.canonical_name}' ({a.entity_type.value})",
                ))
    return candidates


def _name_similarity(a: str, b: str) -> float:
    """Simple name similarity based on common tokens and containment."""
    a_lower = a.lower().strip()
    b_lower = b.lower().strip()
    if a_lower == b_lower:
        return 1.0

    # Containment check: one name contains the other
    if a_lower in b_lower or b_lower in a_lower:
        shorter = min(len(a_lower), len(b_lower))
        longer = max(len(a_lower), len(b_lower))
        return shorter / longer

    # Token-based Jaccard similarity
    a_tokens = set(a_lower.split())
    b_tokens = set(b_lower.split())
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens & b_tokens
    union = a_tokens | b_tokens
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# Deprecation
# ---------------------------------------------------------------------------

class DeprecationRecord(BaseModel):
    """Records the deprecation of a claim or entity."""

    target_id: str  # claim_id or entity_id
    target_type: str  # "claim" or "entity"
    deprecated_at: datetime = Field(default_factory=datetime.now)
    reason: str = ""
    replacement_id: str | None = Field(
        default=None,
        description="ID of the entity/claim that supersedes this one",
    )
    deprecated_by: str = ""
    preserved: bool = True  # History is always preserved


def deprecate_claim(
    claim: ClaimRecord,
    reason: str,
    replacement_claim_id: str | None = None,
    deprecated_by: str = "system",
) -> tuple[ClaimRecord, DeprecationRecord]:
    """Deprecate a claim, preserving its history."""
    updated_claim = ClaimRecord(
        claim_id=claim.claim_id,
        statement=claim.statement,
        subject_entity_id=claim.subject_entity_id,
        predicate=claim.predicate,
        evidence_anchors=claim.evidence_anchors,
        page_refs=claim.page_refs,
        status=ClaimStatus.DEPRECATED,
        confidence=claim.confidence,
        supporting_sources=claim.supporting_sources,
        conflicting_sources=claim.conflicting_sources,
        inference_note=claim.inference_note,
        updated_at=datetime.now(),
    )
    deprecation = DeprecationRecord(
        target_id=claim.claim_id,
        target_type="claim",
        reason=reason,
        replacement_id=replacement_claim_id,
        deprecated_by=deprecated_by,
    )
    return updated_claim, deprecation


# Need to import Literal for DedupCandidate
from typing import Literal
