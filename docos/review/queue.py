"""Review queue — manages high-risk patches, conflicted claims, and review actions.

The review queue ensures that high-risk changes, fallback results,
and conflict resolutions go through human review before merging.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Review item
# ---------------------------------------------------------------------------

class ReviewDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUEST_CHANGES = "request_changes"


class ReviewItemType(str, Enum):
    PATCH = "patch"
    CONFLICT_CLAIM = "conflict_claim"
    ENTITY_DEDUP = "entity_dedup"
    COMPLEX_TABLE = "complex_table"
    COMPLEX_FORMULA = "complex_formula"
    CROSS_PAGE = "cross_page"


class ReviewAction(BaseModel):
    """A single review action (approve/reject/request-changes)."""

    reviewer: str
    decision: ReviewDecision
    timestamp: datetime = Field(default_factory=datetime.now)
    reason: str = ""
    linked_patch_id: str | None = None
    note: str | None = None


class ReviewItem(BaseModel):
    """An item in the review queue."""

    review_id: str
    item_type: ReviewItemType
    target_object_id: str = Field(description="Patch ID, claim ID, or entity ID")
    source_id: str = ""

    # Why it's in the queue
    reason: str = ""
    risk_score: float = 0.0
    blast_radius_pages: int = 0

    # Status
    status: ReviewDecision = ReviewDecision.PENDING
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime | None = None

    # Review actions
    actions: list[ReviewAction] = Field(default_factory=list)

    # Linked data
    patch_summary: str | None = None
    conflict_details: str | None = None
    dedup_candidates: list[str] = Field(default_factory=list)

    def approve(self, reviewer: str, reason: str = "") -> None:
        action = ReviewAction(reviewer=reviewer, decision=ReviewDecision.APPROVED, reason=reason)
        self.actions.append(action)
        self.status = ReviewDecision.APPROVED
        self.updated_at = datetime.now()

    def reject(self, reviewer: str, reason: str = "") -> None:
        action = ReviewAction(reviewer=reviewer, decision=ReviewDecision.REJECTED, reason=reason)
        self.actions.append(action)
        self.status = ReviewDecision.REJECTED
        self.updated_at = datetime.now()

    def request_changes(self, reviewer: str, reason: str = "") -> None:
        action = ReviewAction(reviewer=reviewer, decision=ReviewDecision.REQUEST_CHANGES, reason=reason)
        self.actions.append(action)
        self.status = ReviewDecision.REQUEST_CHANGES
        self.updated_at = datetime.now()

    @property
    def is_resolved(self) -> bool:
        return self.status != ReviewDecision.PENDING


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------

class ReviewQueue:
    """Manages the review queue with persistence.

    Storage layout:
        <base_dir>/queue/<review_id>.json
        <base_dir>/approved/<review_id>.json
        <base_dir>/rejected/<review_id>.json
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        self._items: dict[str, ReviewItem] = {}
        (base_dir / "queue").mkdir(parents=True, exist_ok=True)
        (base_dir / "approved").mkdir(parents=True, exist_ok=True)
        (base_dir / "rejected").mkdir(parents=True, exist_ok=True)
        self._load_all()

    def add(self, item: ReviewItem) -> None:
        """Add an item to the review queue."""
        self._items[item.review_id] = item
        self._persist(item, "queue")

    def get(self, review_id: str) -> ReviewItem | None:
        return self._items.get(review_id)

    def list_pending(self) -> list[ReviewItem]:
        return [item for item in self._items.values() if item.status == ReviewDecision.PENDING]

    def list_all(self) -> list[ReviewItem]:
        return list(self._items.values())

    def resolve(self, review_id: str, action: str, reviewer: str, reason: str = "") -> ReviewItem | None:
        """Resolve a review item.

        Args:
            action: "approve", "reject", or "request_changes"
        """
        item = self._items.get(review_id)
        if item is None:
            return None

        if action == "approve":
            item.approve(reviewer, reason)
            self._persist(item, "approved")
        elif action == "reject":
            item.reject(reviewer, reason)
            self._persist(item, "rejected")
        elif action == "request_changes":
            item.request_changes(reviewer, reason)

        return item

    def _persist(self, item: ReviewItem, subdir: str) -> None:
        path = self._base / subdir / f"{item.review_id}.json"
        path.write_text(item.model_dump_json(indent=2), encoding="utf-8")

    def _load_all(self) -> None:
        """Load all existing review items from disk on initialization."""
        for subdir in ("queue", "approved", "rejected"):
            dir_path = self._base / subdir
            if not dir_path.exists():
                continue
            for path in dir_path.glob("*.json"):
                try:
                    item = ReviewItem.model_validate_json(path.read_text(encoding="utf-8"))
                    self._items[item.review_id] = item
                except Exception:
                    pass  # Skip corrupted files
