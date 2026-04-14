"""Patch schema — structured change proposals for wiki updates.

Patches are the ONLY way to modify the formal wiki. No LLM or process
may write directly to the wiki without going through the patch flow:

    generate patch → lint → review → merge
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Change types
# ---------------------------------------------------------------------------

class ChangeType(str, Enum):
    """Supported patch change types."""

    CREATE_PAGE = "create_page"
    UPDATE_PAGE = "update_page"
    SPLIT_PAGE = "split_page"
    MERGE_PAGE = "merge_page"
    ADD_CLAIM = "add_claim"
    UPDATE_CLAIM = "update_claim"
    DEPRECATE_CLAIM = "deprecate_claim"
    RELINK_ENTITY = "relink_entity"
    ADD_ALIAS = "add_alias"
    FIX_ANCHOR = "fix_anchor"
    MARK_CONFLICT = "mark_conflict"


class MergeStatus(str, Enum):
    """Patch merge lifecycle."""

    PENDING = "pending"
    AUTO_MERGED = "auto_merged"
    APPROVED = "approved"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------

class BlastRadius(BaseModel):
    """Impact metrics for a patch."""

    pages: int = Field(default=0, ge=0, description="Number of affected pages")
    claims: int = Field(default=0, ge=0, description="Number of affected claims")
    links: int = Field(default=0, ge=0, description="Number of affected links")
    entities_redirected: int = Field(default=0, ge=0, description="Entity redirects")
    conflicts_added: int = Field(default=0, ge=0, description="New conflicts introduced")


# ---------------------------------------------------------------------------
# Change
# ---------------------------------------------------------------------------

class Change(BaseModel):
    """A single change within a patch."""

    type: ChangeType
    target: str = Field(description="Target page path or object ID")
    summary: str = Field(default="", description="Human-readable change summary")
    details: dict[str, object] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------

class Patch(BaseModel):
    """A structured change proposal for the wiki.

    Invariants:
    - No direct wiki writes; all changes go through patches.
    - High-risk patches must have review_required=True.
    - Blast radius must be computed before merge.
    """

    patch_id: str = Field(description="Unique patch identifier")
    run_id: str = Field(description="Ingest run that produced this patch")
    source_id: str = Field(description="Source document this patch derives from")
    generated_at: datetime = Field(default_factory=datetime.now)

    # Content
    changes: list[Change] = Field(default_factory=list)

    # Risk assessment
    blast_radius: BlastRadius = Field(default_factory=BlastRadius)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    review_required: bool = False

    # Lint / harness (filled later)
    lint_passed: bool | None = None
    harness_passed: bool | None = None

    # Lifecycle
    merge_status: MergeStatus = MergeStatus.PENDING
    merged_at: datetime | None = None
    reviewer: str | None = None
    review_note: str | None = None
    rollback_of: str | None = Field(
        default=None, description="If this patch rolls back a previous patch, its ID"
    )
