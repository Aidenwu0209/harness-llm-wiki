"""US-021: Implement patch rollback and reject lifecycle steps."""

import tempfile
from pathlib import Path

from docos.artifact_stores import WikiPageState, WikiStore
from docos.models.patch import (
    Change,
    ChangeType,
    MergeStatus,
    Patch,
)
from docos.wiki.patch_service import PatchService

import pytest


def _make_patch(
    patch_id: str = "pat_rb_001",
    risk: float = 0.1,
) -> Patch:
    return Patch(
        patch_id=patch_id,
        run_id="run_001",
        source_id="src_001",
        changes=[
            Change(type=ChangeType.CREATE_PAGE, target="wiki/sources/test.md"),
        ],
        risk_score=risk,
    )


class TestRollback:
    def test_rollback_auto_merged_patch(self) -> None:
        """Rolling back an auto-merged patch transitions status to ROLLED_BACK."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.1)
            svc.apply_patch(patch)
            svc.auto_merge(patch)
            assert patch.merge_status == MergeStatus.AUTO_MERGED

            svc.rollback(patch)
            assert patch.merge_status == MergeStatus.ROLLED_BACK

    def test_rollback_approved_patch(self) -> None:
        """Rolling back an approved patch transitions status to ROLLED_BACK."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)
            svc.approve_merge(patch, reviewer="alice", note="ok")
            assert patch.merge_status == MergeStatus.APPROVED

            svc.rollback(patch)
            assert patch.merge_status == MergeStatus.ROLLED_BACK

    def test_rollback_restores_prior_wiki_state(self) -> None:
        """Rolling back a merged patch restores the pre-merge wiki body."""
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            patch_dir = Path(tmp) / "patches"

            # Save initial wiki state
            wiki_store = WikiStore(wiki_dir)
            wiki_store.save(WikiPageState(
                page_path="wiki/sources/test.md",
                run_id="run_000",
                frontmatter={"id": "source.test"},
                body="Original wiki content",
            ))

            svc = PatchService(patch_dir, wiki_dir)
            patch = _make_patch(risk=0.1)
            svc.apply_patch(patch)
            svc.auto_merge(patch)
            assert patch.pre_merge_snapshot == "Original wiki content"

            # Rollback should restore the original body
            svc.rollback(patch)

            restored = wiki_store.get("wiki/sources/test.md")
            assert restored is not None
            assert restored.body == "Original wiki content"

    def test_rollback_persists_rolled_back_status(self) -> None:
        """Rolled-back status is persisted to disk."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.1)
            svc.apply_patch(patch)
            svc.auto_merge(patch)
            svc.rollback(patch)

            loaded = svc.get_patch("pat_rb_001")
            assert loaded is not None
            assert loaded.merge_status == MergeStatus.ROLLED_BACK

    def test_rollback_pending_patch_raises(self) -> None:
        """Cannot rollback a patch that was never merged."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.1)
            svc.apply_patch(patch)
            with pytest.raises(ValueError, match="Cannot rollback"):
                svc.rollback(patch)

    def test_rollback_already_rolled_back_raises(self) -> None:
        """Cannot rollback a patch that is already rolled back."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.1)
            svc.apply_patch(patch)
            svc.auto_merge(patch)
            svc.rollback(patch)
            with pytest.raises(ValueError, match="Cannot rollback"):
                svc.rollback(patch)


class TestReject:
    def test_reject_sets_status(self) -> None:
        """Rejecting a patch transitions status to REJECTED."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)
            svc.reject(patch, reviewer="bob", reason="Bad data")
            assert patch.merge_status == MergeStatus.REJECTED

    def test_reject_records_reviewer_and_reason(self) -> None:
        """Rejected patch records the reviewer and reason."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)
            svc.reject(patch, reviewer="carol", reason="Outdated info")
            assert patch.reviewer == "carol"
            assert patch.review_note == "Outdated info"

    def test_rejected_patch_remains_auditable(self) -> None:
        """Rejected patches are persisted and can be reloaded."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)
            svc.reject(patch, reviewer="bob", reason="No")

            # Load from disk
            loaded = svc.get_patch("pat_rb_001")
            assert loaded is not None
            assert loaded.merge_status == MergeStatus.REJECTED
            assert loaded.reviewer == "bob"
            assert loaded.review_note == "No"
            # Patch still has its changes and metadata (auditable)
            assert len(loaded.changes) == 1
            assert loaded.patch_id == "pat_rb_001"

    def test_reject_without_merge_does_not_affect_wiki(self) -> None:
        """Rejecting a pending patch does not modify wiki state."""
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            patch_dir = Path(tmp) / "patches"

            # Pre-save wiki state
            wiki_store = WikiStore(wiki_dir)
            wiki_store.save(WikiPageState(
                page_path="wiki/sources/test.md",
                run_id="run_000",
                frontmatter={"id": "source.test"},
                body="Unchanged content",
            ))

            svc = PatchService(patch_dir, wiki_dir)
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)
            svc.reject(patch, reviewer="alice", reason="Skip")

            # Wiki state should remain unchanged
            state = wiki_store.get("wiki/sources/test.md")
            assert state is not None
            assert state.body == "Unchanged content"
