"""US-021: Implement patch rollback and reject lifecycle steps."""

import tempfile
from datetime import date
from pathlib import Path

from docos.artifact_stores import WikiPageState, WikiStore
from docos.models.page import Frontmatter, PageType, PageStatus, ReviewStatus
from docos.models.patch import (
    Change,
    ChangeType,
    MergeStatus,
    Patch,
)
from docos.wiki.patch_service import PatchService


def _make_patch(patch_id: str = "pat_rollback_001") -> Patch:
    return Patch(
        patch_id=patch_id,
        run_id="run_001",
        source_id="src_001",
        changes=[
            Change(type=ChangeType.UPDATE_PAGE, target="wiki/sources/test.md"),
        ],
        risk_score=0.1,
    )


class TestRollbackPatch:
    def test_rollback_auto_merged_patch(self) -> None:
        """Rolling back an auto-merged patch sets ROLLED_BACK status."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch()
            svc.apply_patch(patch)
            svc.auto_merge(patch)
            assert patch.merge_status == MergeStatus.AUTO_MERGED
            svc.rollback(patch)
            assert patch.merge_status == MergeStatus.ROLLED_BACK

    def test_rollback_approved_patch(self) -> None:
        """Rolling back an approved patch sets ROLLED_BACK status."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch()
            svc.apply_patch(patch)
            svc.approve_merge(patch, reviewer="alice")
            assert patch.merge_status == MergeStatus.APPROVED
            svc.rollback(patch)
            assert patch.merge_status == MergeStatus.ROLLED_BACK

    def test_rollback_restores_prior_wiki_state(self) -> None:
        """Rolling back a merged patch restores the prior persisted wiki state."""
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            patch_dir = Path(tmp) / "patches"

            # Set up initial wiki state
            wiki_store = WikiStore(wiki_dir)
            wiki_store.save(WikiPageState(
                page_path="wiki/sources/test.md",
                run_id="run_old",
                frontmatter={"id": "source.test"},
                body="Original content before patch",
            ))

            svc = PatchService(patch_dir, wiki_dir)
            patch = _make_patch()
            svc.apply_patch(patch)
            svc.auto_merge(patch)
            assert patch.pre_merge_snapshot == "Original content before patch"

            # Now rollback
            svc.rollback(patch)

            # Verify wiki state is restored
            state = wiki_store.get("wiki/sources/test.md")
            assert state is not None
            assert state.body == "Original content before patch"

    def test_rollback_persists_status(self) -> None:
        """Rollback persists the ROLLED_BACK status to disk."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch()
            svc.apply_patch(patch)
            svc.auto_merge(patch)
            svc.rollback(patch)

            loaded = svc.get_patch("pat_rollback_001")
            assert loaded is not None
            assert loaded.merge_status == MergeStatus.ROLLED_BACK

    def test_cannot_rollback_pending_patch(self) -> None:
        """Rolling back a PENDING patch raises ValueError."""
        import pytest
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch()
            svc.apply_patch(patch)
            with pytest.raises(ValueError, match="Cannot rollback"):
                svc.rollback(patch)


class TestRejectPatch:
    def test_reject_sets_rejected_status(self) -> None:
        """Rejecting a patch sets REJECTED status and records reviewer."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch()
            svc.apply_patch(patch)
            svc.reject(patch, reviewer="bob", reason="Too risky")
            assert patch.merge_status == MergeStatus.REJECTED
            assert patch.reviewer == "bob"
            assert patch.review_note == "Too risky"

    def test_rejected_patch_remains_auditable(self) -> None:
        """Rejected patches stay in patch storage and can be loaded."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch()
            svc.apply_patch(patch)
            svc.reject(patch, reviewer="bob", reason="Bad")

            loaded = svc.get_patch("pat_rollback_001")
            assert loaded is not None
            assert loaded.merge_status == MergeStatus.REJECTED
            assert loaded.reviewer == "bob"

    def test_reject_does_not_modify_wiki_state(self) -> None:
        """Rejecting a patch does not change wiki page content."""
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            patch_dir = Path(tmp) / "patches"

            wiki_store = WikiStore(wiki_dir)
            wiki_store.save(WikiPageState(
                page_path="wiki/sources/test.md",
                run_id="run_old",
                frontmatter={"id": "source.test"},
                body="Unchanged content",
            ))

            svc = PatchService(patch_dir, wiki_dir)
            patch = _make_patch()
            svc.apply_patch(patch)
            svc.reject(patch, reviewer="alice", reason="No")

            state = wiki_store.get("wiki/sources/test.md")
            assert state is not None
            assert state.body == "Unchanged content"
