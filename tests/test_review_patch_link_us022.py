"""US-022: Link review items to concrete patch IDs."""

import tempfile
from pathlib import Path

from docos.artifact_stores import PatchStore
from docos.models.patch import Change, ChangeType, Patch
from docos.review.queue import ReviewAction, ReviewDecision, ReviewItem, ReviewItemType, ReviewQueue


def _make_patch(patch_id: str = "pat_review_001") -> Patch:
    return Patch(
        patch_id=patch_id,
        run_id="run_001",
        source_id="src_001",
        changes=[
            Change(type=ChangeType.UPDATE_PAGE, target="wiki/sources/test.md"),
        ],
        risk_score=0.5,
        review_required=True,
    )


class TestReviewItemPatchLink:
    def test_review_item_stores_patch_id(self) -> None:
        """A review item for a patch stores the patch_id in target_object_id."""
        patch = _make_patch()
        item = ReviewItem(
            review_id="rev_001",
            item_type=ReviewItemType.PATCH,
            target_object_id=patch.patch_id,
            source_id="src_001",
            reason="High risk patch requires review",
            risk_score=0.5,
        )
        assert item.target_object_id == "pat_review_001"
        assert item.item_type == ReviewItemType.PATCH

    def test_review_item_patch_summary(self) -> None:
        """Review item stores a summary of the linked patch."""
        patch = _make_patch()
        item = ReviewItem(
            review_id="rev_002",
            item_type=ReviewItemType.PATCH,
            target_object_id=patch.patch_id,
            patch_summary=f"Update page with {len(patch.changes)} changes",
        )
        assert "1 changes" in item.patch_summary

    def test_review_action_links_patch_id(self) -> None:
        """A review action can reference the linked patch_id."""
        action = ReviewAction(
            reviewer="alice",
            decision=ReviewDecision.APPROVED,
            reason="Looks good",
            linked_patch_id="pat_review_001",
        )
        assert action.linked_patch_id == "pat_review_001"


class TestReviewQueuePatchResolution:
    def test_create_review_from_patch_and_resolve(self) -> None:
        """Create a review item from a patch, add to queue, and resolve it."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            patch_store = PatchStore(tmp_path / "patches")
            review_queue = ReviewQueue(tmp_path / "review")

            # Create and persist patch
            patch = _make_patch()
            patch_store.save(patch)

            # Create review item from patch
            item = ReviewItem(
                review_id="rev_003",
                item_type=ReviewItemType.PATCH,
                target_object_id=patch.patch_id,
                source_id=patch.source_id,
                reason="High risk patch",
                risk_score=patch.risk_score,
            )
            review_queue.add(item)

            # Verify it's in pending list
            pending = review_queue.list_pending()
            assert len(pending) == 1
            assert pending[0].target_object_id == patch.patch_id

            # Resolve the review
            resolved = review_queue.resolve("rev_003", "approve", "alice", "Approved")
            assert resolved is not None
            assert resolved.status == ReviewDecision.APPROVED

    def test_load_patch_from_review_item(self) -> None:
        """The review queue can load the referenced patch artifact from stored patch_id."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            patch_store = PatchStore(tmp_path / "patches")
            review_queue = ReviewQueue(tmp_path / "review")

            # Persist patch
            patch = _make_patch("pat_cross_ref")
            patch_store.save(patch)

            # Create review item referencing the patch
            item = ReviewItem(
                review_id="rev_cross_ref",
                item_type=ReviewItemType.PATCH,
                target_object_id=patch.patch_id,
            )
            review_queue.add(item)

            # Simulate loading: get the review item, then load the patch
            loaded_item = review_queue.get("rev_cross_ref")
            assert loaded_item is not None

            loaded_patch = patch_store.get(loaded_item.target_object_id)
            assert loaded_patch is not None
            assert loaded_patch.patch_id == "pat_cross_ref"
            assert loaded_patch.risk_score == 0.5
