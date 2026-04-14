"""US-022: Link review items to concrete patch IDs."""

import tempfile
from datetime import date
from pathlib import Path

from docos.artifact_stores import PatchStore, WikiPageState, WikiStore
from docos.models.patch import Change, ChangeType, MergeStatus, Patch
from docos.review.queue import ReviewDecision, ReviewItem, ReviewItemType, ReviewQueue
from docos.wiki.patch_service import PatchService


def _make_patch(patch_id: str = "pat_rv_001", risk: float = 0.5) -> Patch:
    return Patch(
        patch_id=patch_id,
        run_id="run_001",
        source_id="src_001",
        changes=[
            Change(type=ChangeType.UPDATE_PAGE, target="wiki/entities/test.md"),
        ],
        risk_score=risk,
    )


def _make_review_item_from_patch(patch: Patch) -> ReviewItem:
    """Create a review item linked to a specific patch ID."""
    return ReviewItem(
        review_id=f"rev_{patch.patch_id}",
        item_type=ReviewItemType.PATCH,
        target_object_id=patch.patch_id,
        source_id=patch.source_id,
        reason="High-risk patch requires review",
        risk_score=patch.risk_score,
        blast_radius_pages=patch.blast_radius.pages,
        patch_summary=f"{len(patch.changes)} change(s)",
    )


class TestReviewItemPatchLink:
    def test_review_item_stores_patch_id(self) -> None:
        """A review item stores the related patch_id in target_object_id."""
        patch = _make_patch()
        item = _make_review_item_from_patch(patch)
        assert item.target_object_id == "pat_rv_001"
        assert item.item_type == ReviewItemType.PATCH

    def test_review_item_from_high_risk_patch(self) -> None:
        """Review items carry risk metadata from the linked patch."""
        patch = _make_patch(risk=0.8)
        item = _make_review_item_from_patch(patch)
        assert item.risk_score == 0.8
        assert item.patch_summary is not None

    def test_load_patch_from_review_item(self) -> None:
        """The review queue can load the referenced patch artifact from stored patch_id."""
        with tempfile.TemporaryDirectory() as tmp:
            patch_dir = Path(tmp) / "patches"
            wiki_dir = Path(tmp) / "wiki"
            review_dir = Path(tmp) / "review"

            # Persist a patch
            svc = PatchService(patch_dir, wiki_dir)
            patch = _make_patch()
            svc.apply_patch(patch)

            # Create review item linked to the patch
            item = _make_review_item_from_patch(patch)
            queue = ReviewQueue(review_dir)
            queue.add(item)

            # Reload the review item and resolve the linked patch
            loaded_item = queue.get(f"rev_{patch.patch_id}")
            assert loaded_item is not None
            assert loaded_item.target_object_id == patch.patch_id

            # Load the patch from the stored patch_id
            loaded_patch = svc.get_patch(loaded_item.target_object_id)
            assert loaded_patch is not None
            assert loaded_patch.patch_id == "pat_rv_001"
            assert len(loaded_patch.changes) == 1

    def test_create_and_resolve_review_from_patch(self) -> None:
        """Test creating a review item from a patch and resolving it."""
        with tempfile.TemporaryDirectory() as tmp:
            patch_dir = Path(tmp) / "patches"
            wiki_dir = Path(tmp) / "wiki"
            review_dir = Path(tmp) / "review"

            # Persist and stage the patch
            svc = PatchService(patch_dir, wiki_dir)
            patch = _make_patch(risk=0.5)
            svc.apply_patch(patch)

            # Create review item
            item = _make_review_item_from_patch(patch)
            queue = ReviewQueue(review_dir)
            queue.add(item)
            assert item.status == ReviewDecision.PENDING

            # Resolve: approve
            resolved = queue.resolve(
                f"rev_{patch.patch_id}",
                action="approve",
                reviewer="alice",
                reason="Looks good after inspection",
            )
            assert resolved is not None
            assert resolved.status == ReviewDecision.APPROVED
            assert resolved.is_resolved

            # Now approve the patch merge
            svc.approve_merge(patch, reviewer="alice", note="Approved via review")
            assert patch.merge_status == MergeStatus.APPROVED
            assert patch.reviewer == "alice"

    def test_reject_review_rejects_patch(self) -> None:
        """Rejecting a review item leads to rejecting the linked patch."""
        with tempfile.TemporaryDirectory() as tmp:
            patch_dir = Path(tmp) / "patches"
            wiki_dir = Path(tmp) / "wiki"
            review_dir = Path(tmp) / "review"

            svc = PatchService(patch_dir, wiki_dir)
            patch = _make_patch(risk=0.6)
            svc.apply_patch(patch)

            item = _make_review_item_from_patch(patch)
            queue = ReviewQueue(review_dir)
            queue.add(item)

            # Reject the review
            resolved = queue.resolve(
                f"rev_{patch.patch_id}",
                action="reject",
                reviewer="bob",
                reason="Data quality issues",
            )
            assert resolved is not None
            assert resolved.status == ReviewDecision.REJECTED

            # Also reject the patch
            svc.reject(patch, reviewer="bob", reason="Data quality issues")
            assert patch.merge_status == MergeStatus.REJECTED
            assert patch.reviewer == "bob"

            # Verify patch is still auditable on disk
            loaded = svc.get_patch("pat_rv_001")
            assert loaded is not None
            assert loaded.merge_status == MergeStatus.REJECTED

    def test_review_item_persists_patch_link(self) -> None:
        """The patch_id link survives persistence and reload."""
        with tempfile.TemporaryDirectory() as tmp:
            review_dir = Path(tmp) / "review"
            patch = _make_patch()
            item = _make_review_item_from_patch(patch)

            # Save
            queue1 = ReviewQueue(review_dir)
            queue1.add(item)

            # Reload from disk (new ReviewQueue instance)
            queue2 = ReviewQueue(review_dir)
            loaded = queue2.get(f"rev_{patch.patch_id}")
            assert loaded is not None
            assert loaded.target_object_id == patch.patch_id
            assert loaded.item_type == ReviewItemType.PATCH
