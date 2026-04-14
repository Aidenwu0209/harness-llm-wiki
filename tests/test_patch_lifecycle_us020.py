"""US-020: Implement patch apply and merge lifecycle steps."""

import tempfile
from datetime import date
from pathlib import Path

from docos.artifact_stores import WikiPageState, WikiStore
from docos.models.page import Frontmatter, PageType, PageStatus, ReviewStatus
from docos.models.patch import (
    BlastRadius,
    Change,
    ChangeType,
    MergeStatus,
    Patch,
)
from docos.wiki.patch_service import PatchService


def _make_patch(
    patch_id: str = "pat_001",
    risk: float = 0.1,
    review_required: bool = False,
) -> Patch:
    return Patch(
        patch_id=patch_id,
        run_id="run_001",
        source_id="src_001",
        changes=[
            Change(type=ChangeType.CREATE_PAGE, target="wiki/sources/test.md"),
        ],
        risk_score=risk,
        review_required=review_required,
    )


def _make_fm() -> Frontmatter:
    return Frontmatter(
        id="source.test",
        type=PageType.SOURCE,
        title="Test",
        status=PageStatus.AUTO,
        created_at=date(2026, 4, 15),
        updated_at=date(2026, 4, 15),
        review_status=ReviewStatus.PENDING,
    )


class TestApplyPatch:
    def test_apply_stages_patch(self) -> None:
        """apply_patch() calls stage() and persists the patch."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch()
            svc.apply_patch(patch)
            assert patch.merge_status == MergeStatus.PENDING
            # Verify persisted
            loaded = svc.get_patch("pat_001")
            assert loaded is not None
            assert loaded.merge_status == MergeStatus.PENDING

    def test_apply_computes_review_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)
            assert patch.review_required is True


class TestAutoMerge:
    def test_auto_merge_low_risk(self) -> None:
        """auto_merge() transitions status to AUTO_MERGED and persists."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.1)
            svc.apply_patch(patch)
            svc.auto_merge(patch)
            assert patch.merge_status == MergeStatus.AUTO_MERGED
            assert patch.merged_at is not None

    def test_auto_merge_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.1)
            svc.apply_patch(patch)
            svc.auto_merge(patch)
            loaded = svc.get_patch("pat_001")
            assert loaded is not None
            assert loaded.merge_status == MergeStatus.AUTO_MERGED

    def test_auto_merge_blocked_for_review_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            # risk=0.5 triggers review_required via stage() (risk > 0.3)
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)
            assert patch.review_required is True
            import pytest
            with pytest.raises(ValueError, match="review"):
                svc.auto_merge(patch)


class TestApproveMerge:
    def test_approve_merge_transitions_status(self) -> None:
        """approve_merge() transitions status to APPROVED and records reviewer."""
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)
            svc.approve_merge(patch, reviewer="alice", note="Looks good")
            assert patch.merge_status == MergeStatus.APPROVED
            assert patch.reviewer == "alice"
            assert patch.review_note == "Looks good"
            assert patch.merged_at is not None

    def test_approve_merge_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = PatchService(Path(tmp) / "patches", Path(tmp) / "wiki")
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)
            svc.approve_merge(patch, reviewer="bob", note="OK")
            loaded = svc.get_patch("pat_001")
            assert loaded is not None
            assert loaded.merge_status == MergeStatus.APPROVED
            assert loaded.reviewer == "bob"


class TestMergeUpdatesWikiState:
    def test_auto_merge_snapshots_prior_wiki_state(self) -> None:
        """Auto-merge captures the pre-merge wiki body as snapshot."""
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            patch_dir = Path(tmp) / "patches"

            # Save initial wiki state
            wiki_store = WikiStore(wiki_dir)
            wiki_store.save(WikiPageState(
                page_path="wiki/sources/test.md",
                run_id="run_000",
                frontmatter={"id": "source.test"},
                body="Old wiki content",
            ))

            svc = PatchService(patch_dir, wiki_dir)
            patch = _make_patch(risk=0.1)
            svc.apply_patch(patch)
            svc.auto_merge(patch)
            assert patch.pre_merge_snapshot == "Old wiki content"

    def test_approve_merge_snapshots_prior_wiki_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            patch_dir = Path(tmp) / "patches"

            wiki_store = WikiStore(wiki_dir)
            wiki_store.save(WikiPageState(
                page_path="wiki/sources/test.md",
                run_id="run_000",
                frontmatter={"id": "source.test"},
                body="Prior content",
            ))

            svc = PatchService(patch_dir, wiki_dir)
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)
            svc.approve_merge(patch, reviewer="alice", note="ok")
            assert patch.pre_merge_snapshot == "Prior content"
