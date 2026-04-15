"""Tests for US-026: Make review approval apply pending wiki changes."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import PatchStore, WikiStore, WikiPageState
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.review.queue import ReviewItem, ReviewItemType, ReviewQueue
from docos.run_store import RunStore


def _setup_pending_review(tmp_path: Path) -> tuple[str, str, Path, Path]:
    """Create a run with pending review item and patches."""
    base = tmp_path / "artifacts"
    run_store = RunStore(base)
    manifest = run_store.create(source_id="src-approve", source_hash="h", source_file_path="/tmp/t.pdf")
    run_id = manifest.run_id

    # Create patches
    patch_store = PatchStore(base / "patches")
    patch = Patch(
        patch_id="p-approve-1",
        run_id=run_id,
        source_id="src-approve",
        changes=[Change(type=ChangeType.CREATE_PAGE, target="wiki/source/test.md")],
        risk_score=0.8,
        blast_radius=BlastRadius(pages=1),
        review_required=True,
    )
    patch_store.save(patch)

    # Create pending review item
    queue = ReviewQueue(base / "review_queue")
    review_item = ReviewItem(
        review_id=f"rv-{run_id}",
        item_type=ReviewItemType.PATCH,
        target_object_id=run_id,
        run_id=run_id,
        source_id="src-approve",
        patch_ids=["p-approve-1"],
        gate_reasons=["High risk"],
        reason="High risk requires review",
    )
    queue.add(review_item)

    # Save wiki state
    wiki_store = WikiStore(base / "wiki_state")
    wiki_store.save(WikiPageState(
        page_path="wiki/source/test.md", run_id=run_id,
        frontmatter={"id": "test", "title": "Approved Page"},
        body="# Approved\nThis is the approved content.",
    ))

    return run_id, f"rv-{run_id}", base, tmp_path / "artifacts" / "wiki"


class TestReviewApprovalApply:
    """US-026: Approving review item applies wiki state."""

    def test_approval_applies_wiki_files(self, tmp_path: Path) -> None:
        """After approval, wiki files are written through PatchApplyService."""
        run_id, review_id, base, wiki_dir = _setup_pending_review(tmp_path)

        queue = ReviewQueue(base / "review_queue")
        item, report = queue.resolve_and_sync(
            review_id=review_id,
            action="approve",
            reviewer="test_user",
            reason="Looks good",
            patch_dir=base / "patches",
            run_dir=base,
            wiki_dir=wiki_dir,
            wiki_state_dir=base / "wiki_state",
        )

        assert item is not None
        assert item.actions[-1].decision.value == "approved"
        assert report.get("wiki_applied", 0) > 0

        # Verify wiki file exists
        md_file = wiki_dir / "wiki/source/test.md"
        assert md_file.exists()
        content = md_file.read_text()
        assert "approved content" in content

    def test_approval_updates_patch_status(self, tmp_path: Path) -> None:
        """After approval, patches are in APPROVED status."""
        run_id, review_id, base, wiki_dir = _setup_pending_review(tmp_path)

        queue = ReviewQueue(base / "review_queue")
        queue.resolve_and_sync(
            review_id=review_id,
            action="approve",
            reviewer="test_user",
            patch_dir=base / "patches",
            run_dir=base,
            wiki_dir=wiki_dir,
            wiki_state_dir=base / "wiki_state",
        )

        # Verify patch status
        patch_store = PatchStore(base / "patches")
        patch = patch_store.get("p-approve-1")
        assert patch is not None
        assert patch.merge_status.value == "approved"

    def test_approval_updates_manifest(self, tmp_path: Path) -> None:
        """After approval, manifest review_status is 'approved'."""
        run_id, review_id, base, wiki_dir = _setup_pending_review(tmp_path)

        queue = ReviewQueue(base / "review_queue")
        queue.resolve_and_sync(
            review_id=review_id,
            action="approve",
            reviewer="test_user",
            patch_dir=base / "patches",
            run_dir=base,
            wiki_dir=wiki_dir,
            wiki_state_dir=base / "wiki_state",
        )

        run_store = RunStore(base)
        manifest = run_store.get(run_id)
        assert manifest is not None
        assert manifest.review_status == "approved"
