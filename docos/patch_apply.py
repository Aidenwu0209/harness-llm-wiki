"""PatchApplyService — apply patches to wiki state.

All wiki file writes go through this service. Patches are the only legal
way to change wiki files and wiki state artifacts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from docos.artifact_stores import WikiStore, WikiPageState
from docos.models.patch import ChangeType, Patch

logger = logging.getLogger(__name__)


class PatchApplyResult:
    """Result of applying a single patch."""

    def __init__(
        self,
        patch_id: str,
        applied: bool,
        changes_applied: int = 0,
        skipped: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        self.patch_id = patch_id
        self.applied = applied
        self.changes_applied = changes_applied
        self.skipped = skipped or []
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "applied": self.applied,
            "changes_applied": self.changes_applied,
            "skipped": self.skipped,
            "error": self.error,
        }


class PatchApplyService:
    """Apply patches to wiki state through a formal service layer.

    Supports CREATE_PAGE, UPDATE_PAGE, and DELETE_PAGE change types.
    Each apply is idempotent — applying the same patch twice does not
    create extra diffs or duplicate state writes.
    """

    def __init__(self, wiki_dir: Path, wiki_store: WikiStore | None = None) -> None:
        self._wiki_dir = wiki_dir
        self._wiki_dir.mkdir(parents=True, exist_ok=True)
        self._wiki_store = wiki_store or WikiStore(wiki_dir.parent / "wiki_state")
        # Track applied patch IDs for idempotency
        self._applied_log = self._wiki_dir / "apply_log.json"

    def _load_applied_ids(self) -> set[str]:
        """Load set of already-applied patch IDs."""
        if self._applied_log.exists():
            data = json.loads(self._applied_log.read_text(encoding="utf-8"))
            return set(data.get("applied_patch_ids", []))
        return set()

    def _save_applied_ids(self, ids: set[str]) -> None:
        """Persist set of applied patch IDs."""
        data = {"applied_patch_ids": sorted(ids), "updated_at": datetime.now().isoformat()}
        self._applied_log.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def apply(self, patch: Patch) -> PatchApplyResult:
        """Apply a single patch to wiki state.

        Returns PatchApplyResult indicating what was applied.
        Idempotent — re-applying the same patch is a no-op.
        """
        applied_ids = self._load_applied_ids()
        if patch.patch_id in applied_ids:
            logger.info("Patch %s already applied, skipping", patch.patch_id)
            return PatchApplyResult(
                patch_id=patch.patch_id,
                applied=True,
                changes_applied=0,
                skipped=["already_applied"],
            )

        changes_applied = 0
        skipped: list[str] = []

        for change in patch.changes:
            if change.type == ChangeType.CREATE_PAGE:
                self._apply_create(change.target, patch)
                changes_applied += 1
            elif change.type == ChangeType.UPDATE_PAGE:
                self._apply_update(change.target, patch)
                changes_applied += 1
            elif change.type == ChangeType.DELETE_PAGE:
                self._apply_delete(change.target, patch)
                changes_applied += 1
            else:
                skipped.append(f"unsupported_type:{change.type.value}")
                logger.warning("Unsupported change type: %s", change.type.value)

        # Record applied
        applied_ids.add(patch.patch_id)
        self._save_applied_ids(applied_ids)

        return PatchApplyResult(
            patch_id=patch.patch_id,
            applied=True,
            changes_applied=changes_applied,
            skipped=skipped,
        )

    def apply_batch(self, patches: list[Patch]) -> list[PatchApplyResult]:
        """Apply multiple patches in order."""
        results: list[PatchApplyResult] = []
        for patch in patches:
            results.append(self.apply(patch))
        return results

    def _apply_create(self, target: str, patch: Patch) -> None:
        """Apply a CREATE_PAGE change — write new wiki file and state."""
        # Write markdown file
        md_path = self._wiki_dir / target
        md_path.parent.mkdir(parents=True, exist_ok=True)

        if not md_path.exists():
            # Load wiki state for content
            state = self._wiki_store.get(target)
            content = self._build_markdown(state)
            md_path.write_text(content, encoding="utf-8")
            logger.info("Created wiki page: %s", target)

    def _apply_update(self, target: str, patch: Patch) -> None:
        """Apply an UPDATE_PAGE change — overwrite wiki file with new content."""
        md_path = self._wiki_dir / target
        md_path.parent.mkdir(parents=True, exist_ok=True)

        state = self._wiki_store.get(target)
        content = self._build_markdown(state)
        md_path.write_text(content, encoding="utf-8")
        logger.info("Updated wiki page: %s", target)

    def _apply_delete(self, target: str, patch: Patch) -> None:
        """Apply a DELETE_PAGE change — remove wiki file."""
        md_path = self._wiki_dir / target
        if md_path.exists():
            md_path.unlink()
            logger.info("Deleted wiki page: %s", target)

    @staticmethod
    def _build_markdown(state: WikiPageState | None) -> str:
        """Build markdown content from wiki page state."""
        if state is None:
            return ""
        import yaml  # type: ignore[import-untyped]
        fm = yaml.dump(state.frontmatter, default_flow_style=False).strip()
        return f"---\n{fm}\n---\n{state.body}\n"

    def rollback(self, patch: Patch) -> PatchApplyResult:
        """Rollback a previously applied patch.

        Restores pre-merge state for the affected pages.
        """
        applied_ids = self._load_applied_ids()
        if patch.patch_id not in applied_ids:
            return PatchApplyResult(
                patch_id=patch.patch_id,
                applied=False,
                error="patch_not_applied",
            )

        for change in patch.changes:
            if change.type == ChangeType.DELETE_PAGE:
                # Restore deleted page from state store
                md_path = self._wiki_dir / change.target
                state = self._wiki_store.get(change.target)
                if state:
                    md_path.parent.mkdir(parents=True, exist_ok=True)
                    md_path.write_text(self._build_markdown(state), encoding="utf-8")
            elif change.type in (ChangeType.CREATE_PAGE, ChangeType.UPDATE_PAGE):
                # Remove created/updated content — revert to pre-merge snapshot
                md_path = self._wiki_dir / change.target
                if change.target in (patch.pre_merge_snapshot or ""):
                    md_path.write_text(patch.pre_merge_snapshot or "", encoding="utf-8")
                elif md_path.exists() and change.type == ChangeType.CREATE_PAGE:
                    md_path.unlink()

        applied_ids.discard(patch.patch_id)
        self._save_applied_ids(applied_ids)

        # Write rollback artifact
        rollback_path = self._wiki_dir / f"rollback-{patch.patch_id}.json"
        rollback_path.write_text(json.dumps({
            "patch_id": patch.patch_id,
            "rolled_back_at": datetime.now().isoformat(),
            "changes_rolled_back": len(patch.changes),
        }, indent=2), encoding="utf-8")

        return PatchApplyResult(
            patch_id=patch.patch_id,
            applied=True,
            changes_applied=len(patch.changes),
        )
