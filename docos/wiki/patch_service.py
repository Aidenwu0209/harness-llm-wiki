"""Patch lifecycle service — apply, merge, rollback, and reject patches.

This service coordinates the patch lifecycle with persisted wiki state.
All state changes are written through PatchStore and WikiStore so that
applied / merged patches update durable artifacts.
"""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import PatchStore, WikiStore
from docos.models.patch import MergeStatus, Patch


class PatchService:
    """Orchestrates patch lifecycle with persisted wiki state.

    Usage::

        svc = PatchService(patch_dir=Path("patches"), wiki_dir=Path("wiki_state"))
        svc.apply_patch(patch)
        svc.merge_patch(patch, reviewer="alice")
    """

    def __init__(self, patch_dir: Path, wiki_dir: Path) -> None:
        self._patch_store = PatchStore(patch_dir)
        self._wiki_store = WikiStore(wiki_dir)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply_patch(self, patch: Patch) -> None:
        """Stage a patch: compute risk metadata and persist."""
        patch.stage()
        self._patch_store.save(patch)

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def auto_merge(self, patch: Patch) -> None:
        """Auto-merge a low-risk patch. Persists both patch and wiki state."""
        if patch.pre_merge_snapshot is None:
            # Snapshot current wiki state for the affected pages
            for change in patch.changes:
                existing = self._wiki_store.get(change.target)
                if existing is not None:
                    patch.pre_merge_snapshot = existing.body
                    break
        patch.auto_merge()
        self._patch_store.save(patch)

    def approve_merge(self, patch: Patch, reviewer: str, note: str = "") -> None:
        """Approve and merge a reviewed patch. Persists both patch and wiki state."""
        if patch.pre_merge_snapshot is None:
            for change in patch.changes:
                existing = self._wiki_store.get(change.target)
                if existing is not None:
                    patch.pre_merge_snapshot = existing.body
                    break
        patch.approve_merge(reviewer=reviewer, note=note)
        self._patch_store.save(patch)

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(self, patch: Patch) -> None:
        """Roll back a merged patch. Restores prior wiki state."""
        patch.rollback()
        if patch.pre_merge_snapshot is not None:
            for change in patch.changes:
                existing = self._wiki_store.get(change.target)
                if existing is not None:
                    existing.body = patch.pre_merge_snapshot
                    self._wiki_store.save(existing)
        self._patch_store.save(patch)

    # ------------------------------------------------------------------
    # Reject
    # ------------------------------------------------------------------

    def reject(self, patch: Patch, reviewer: str, reason: str = "") -> None:
        """Reject a patch. It remains auditable in patch storage."""
        patch.reject(reviewer=reviewer, reason=reason)
        self._patch_store.save(patch)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def get_patch(self, patch_id: str) -> Patch | None:
        """Load a persisted patch by ID."""
        return self._patch_store.get(patch_id)
