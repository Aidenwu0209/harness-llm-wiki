"""PatchSet — a run-level aggregate of patches for a single pipeline execution.

Groups all patches produced by one run, with aggregate summary fields
for risk, change types, and affected pages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from docos.models.patch import ChangeType, Patch


class PatchSetSummary(BaseModel):
    """Aggregate summary computed from the patches in a PatchSet."""

    total_patches: int = 0
    create_page_count: int = 0
    update_page_count: int = 0
    delete_page_count: int = 0
    total_pages_changed: int = 0
    max_risk_score: float = 0.0
    any_review_required: bool = False


class PatchSet(BaseModel):
    """A run-level aggregate of patches.

    Invariants:
    - run_id must be stable and unique.
    - patch_ids tracks all patches belonging to this run-level change set.
    - summary is computed from the linked patches.
    """

    # Identity
    run_id: str = Field(description="Linked run ID")
    source_id: str = Field(description="Linked source ID")

    # Patches
    patch_ids: list[str] = Field(default_factory=list, description="IDs of patches in this set")
    patches: list[Patch] = Field(default_factory=list, description="Linked patch objects")

    # Aggregate summary
    summary: PatchSetSummary = Field(default_factory=PatchSetSummary)

    # Temporal
    created_at: datetime = Field(default_factory=datetime.now)

    @classmethod
    def from_patches(
        cls,
        run_id: str,
        source_id: str,
        patches: list[Patch],
    ) -> PatchSet:
        """Create a PatchSet from a list of patches, computing the aggregate summary."""
        summary = PatchSetSummary(
            total_patches=len(patches),
            create_page_count=sum(
                1 for p in patches for c in p.changes if c.type == ChangeType.CREATE_PAGE
            ),
            update_page_count=sum(
                1 for p in patches for c in p.changes if c.type == ChangeType.UPDATE_PAGE
            ),
            delete_page_count=sum(
                1 for p in patches for c in p.changes if c.type == ChangeType.DELETE_PAGE
            ),
            total_pages_changed=len(
                {c.target for p in patches for c in p.changes}
            ),
            max_risk_score=max((p.risk_score for p in patches), default=0.0),
            any_review_required=any(p.review_required for p in patches),
        )

        return cls(
            run_id=run_id,
            source_id=source_id,
            patch_ids=[p.patch_id for p in patches],
            patches=patches,
            summary=summary,
        )
