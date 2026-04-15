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
    """An item in the review queue.

    Supports both single-object reviews and run-level patch-set reviews.
    Run-level items carry ``run_id``, ``patch_ids``, and gate/lint/harness context.
    """

    review_id: str
    item_type: ReviewItemType
    target_object_id: str = Field(description="Patch ID, claim ID, or entity ID")
    source_id: str = ""

    # Run-level patch-set fields (US-002)
    run_id: str | None = Field(default=None, description="Linked run ID for run-level patch-set reviews")
    patch_ids: list[str] = Field(default_factory=list, description="Related patch IDs in this review item")

    # Why it's in the queue
    reason: str = ""
    risk_score: float = 0.0
    blast_radius_pages: int = 0

    # Run-level gate / quality context (US-002)
    gate_reasons: list[str] = Field(default_factory=list, description="Gate block reasons for this review item")
    lint_summary: dict[str, int] = Field(default_factory=dict, description="Lint findings summary by severity")
    harness_summary: dict[str, Any] = Field(default_factory=dict, description="Harness evaluation summary")

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

    def find_by_run_id(self, run_id: str) -> ReviewItem | None:
        """Find an existing review item by run_id."""
        for item in self._items.values():
            if item.run_id == run_id:
                return item
        return None

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

    def resolve_and_sync(
        self,
        review_id: str,
        action: str,
        reviewer: str,
        reason: str = "",
        patch_dir: Path | None = None,
        run_dir: Path | None = None,
        wiki_dir: Path | None = None,
        wiki_state_dir: Path | None = None,
    ) -> tuple[ReviewItem | None, dict[str, Any]]:
        """Resolve a review item and synchronize linked patch + manifest state.

        When action is "approve", applies wiki state through PatchApplyService
        if wiki_dir is provided.

        Returns (review_item, sync_report) where sync_report contains
        details about patches and manifest updates.
        """
        from docos.artifact_stores import PatchStore
        from docos.models.patch import MergeStatus
        from docos.run_store import RunStore

        item = self.resolve(review_id, action, reviewer, reason)
        if item is None:
            return None, {}

        sync_report: dict[str, Any] = {
            "review_id": review_id,
            "action": action,
            "patches_updated": [],
            "manifest_updated": False,
        }

        if action == "approve" and patch_dir is not None:
            patch_store = PatchStore(patch_dir)
            approved_patches = []
            for pid in item.patch_ids:
                patch = patch_store.get(pid)
                if patch is not None:
                    patch.approve_merge(reviewer=reviewer, note=reason)
                    patch_store.save(patch)
                    sync_report["patches_updated"].append(pid)
                    approved_patches.append(patch)

            # Apply wiki state for approved patches
            if wiki_dir is not None and approved_patches:
                from docos.artifact_stores import WikiStore
                from docos.patch_apply import PatchApplyService

                ws = WikiStore(wiki_state_dir) if wiki_state_dir else None
                apply_svc = PatchApplyService(wiki_dir, wiki_store=ws)
                apply_results = apply_svc.apply_batch(approved_patches)
                sync_report["wiki_applied"] = len([r for r in apply_results if r.changes_applied > 0])

        elif action == "reject" and patch_dir is not None:
            patch_store = PatchStore(patch_dir)
            for pid in item.patch_ids:
                patch = patch_store.get(pid)
                if patch is not None:
                    patch.reject(reviewer=reviewer, reason=reason)
                    patch_store.save(patch)
                    sync_report["patches_updated"].append(pid)

        # Update manifest if run_id is available
        if item.run_id and run_dir is not None:
            run_store = RunStore(run_dir)
            manifest = run_store.get(item.run_id)
            if manifest is not None:
                if action == "approve":
                    manifest.review_status = "approved"
                    manifest.release_reasoning = (
                        [f"Approved by {reviewer}: {reason}"] if reason
                        else [f"Approved by {reviewer}"]
                    )
                elif action == "reject":
                    manifest.review_status = "rejected"
                    manifest.release_reasoning = (
                        [f"Rejected by {reviewer}: {reason}"] if reason
                        else [f"Rejected by {reviewer}"]
                    )
                elif action == "request_changes":
                    manifest.review_status = "changes_requested"
                    manifest.release_reasoning = (
                        [f"Changes requested by {reviewer}: {reason}"] if reason
                        else [f"Changes requested by {reviewer}"]
                    )
                run_store.update(manifest)
                sync_report["manifest_updated"] = True

        # Write resolution artifact
        resolution_dir = self._base / "resolutions"
        resolution_dir.mkdir(parents=True, exist_ok=True)
        resolution_artifact = resolution_dir / f"{review_id}.json"
        resolution_data = {
            "review_id": review_id,
            "action": action,
            "reviewer": reviewer,
            "reason": reason,
            "run_id": item.run_id,
            "patch_ids": item.patch_ids,
            "patches_updated": sync_report["patches_updated"],
            "manifest_updated": sync_report["manifest_updated"],
            "resolved_at": datetime.now().isoformat(),
        }
        resolution_artifact.write_text(
            json.dumps(resolution_data, indent=2, default=str),
            encoding="utf-8",
        )
        sync_report["resolution_artifact"] = str(resolution_artifact)

        return item, sync_report

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
