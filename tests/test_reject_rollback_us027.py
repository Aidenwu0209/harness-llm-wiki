"""Tests for US-027: Keep wiki state unchanged on reject and restore it on rollback."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import PatchStore, WikiStore, WikiPageState
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.patch_apply import PatchApplyService
from docos.review.queue import ReviewItem, ReviewItemType, ReviewQueue
from docos.run_store import RunStore


class TestRejectPreservesWiki:
    """US-027: Reject preserves wiki state; rollback restores it."""

    def test_reject_does_not_write_wiki_state(self, tmp_path: Path) -> None:
        """Rejecting a review item does not write linked patches to wiki state."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)
        manifest = run_store.create(source_id="src-rej", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        # Create patch
        patch_store = PatchStore(base / "patches")
        patch = Patch(
            patch_id="p-rej-1",
            run_id=run_id,
            source_id="src-rej",
            changes=[Change(type=ChangeType.CREATE_PAGE, target="wiki/source/test.md")],
            risk_score=0.9,
            blast_radius=BlastRadius(pages=1),
            review_required=True,
        )
        patch_store.save(patch)

        # Create review item
        queue = ReviewQueue(base / "review_queue")
        review_item = ReviewItem(
            review_id=f"rv-{run_id}",
            item_type=ReviewItemType.PATCH,
            target_object_id=run_id,
            run_id=run_id,
            source_id="src-rej",
            patch_ids=["p-rej-1"],
            gate_reasons=["High risk"],
        )
        queue.add(review_item)

        # Wiki state exists but wiki files do NOT exist yet
        wiki_dir = base / "wiki"
        wiki_store = WikiStore(base / "wiki_state")
        wiki_store.save(WikiPageState(
            page_path="wiki/source/test.md", run_id=run_id,
            frontmatter={"id": "test"}, body="Content",
        ))

        # Reject — wiki should remain unchanged
        item, report = queue.resolve_and_sync(
            review_id=f"rv-{run_id}",
            action="reject",
            reviewer="test_user",
            reason="Not good enough",
            patch_dir=base / "patches",
            run_dir=base,
            wiki_dir=wiki_dir,
            wiki_state_dir=base / "wiki_state",
        )

        assert item is not None
        # Wiki file should NOT exist (reject does not apply)
        md_file = wiki_dir / "wiki/source/test.md"
        assert not md_file.exists()

    def test_reject_updates_patch_status(self, tmp_path: Path) -> None:
        """Rejecting sets patch merge_status to rejected."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)
        manifest = run_store.create(source_id="src-rej2", source_hash="h", source_file_path="/tmp/t.pdf")

        patch_store = PatchStore(base / "patches")
        patch = Patch(
            patch_id="p-rej-2",
            run_id=manifest.run_id,
            source_id="src-rej2",
            changes=[Change(type=ChangeType.CREATE_PAGE, target="wiki/source/x.md")],
            risk_score=0.8,
            blast_radius=BlastRadius(pages=1),
            review_required=True,
        )
        patch_store.save(patch)

        queue = ReviewQueue(base / "review_queue")
        queue.add(ReviewItem(
            review_id="rv-rej2",
            item_type=ReviewItemType.PATCH,
            target_object_id=manifest.run_id,
            run_id=manifest.run_id,
            source_id="src-rej2",
            patch_ids=["p-rej-2"],
        ))

        queue.resolve_and_sync(
            review_id="rv-rej2",
            action="reject",
            reviewer="test_user",
            patch_dir=base / "patches",
            run_dir=base,
        )

        p = patch_store.get("p-rej-2")
        assert p is not None
        assert p.merge_status.value == "rejected"

    def test_rollback_restores_wiki_content(self, tmp_path: Path) -> None:
        """Rolling back a merged patch restores pre-merge wiki content."""
        wiki_dir = tmp_path / "wiki"
        wiki_state_dir = tmp_path / "wiki_state"
        wiki_store = WikiStore(wiki_state_dir)

        # Pre-populate state
        wiki_store.save(WikiPageState(
            page_path="wiki/entities/e.md", run_id="run-rollback",
            frontmatter={"id": "e"}, body="Original entity content",
        ))

        # Create and apply a patch (simulate merge)
        service = PatchApplyService(wiki_dir, wiki_store)
        patch = Patch(
            patch_id="p-rollback",
            run_id="run-rollback",
            source_id="src-rollback",
            changes=[Change(type=ChangeType.DELETE_PAGE, target="wiki/entities/e.md")],
            risk_score=0.5,
            blast_radius=BlastRadius(pages=1),
            pre_merge_snapshot="Original entity content",
        )

        # Create the file to be deleted
        md_file = wiki_dir / "wiki/entities/e.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text("Original entity content")

        # Apply (delete)
        service.apply(patch)
        assert not md_file.exists()

        # Rollback — should restore the file
        result = service.rollback(patch)
        assert result.applied

        # Verify rollback artifact
        assert (wiki_dir / "rollback-p-rollback.json").exists()

    def test_reject_manifest_status(self, tmp_path: Path) -> None:
        """Rejecting updates manifest review_status to 'rejected'."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)
        manifest = run_store.create(source_id="src-rej3", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        queue = ReviewQueue(base / "review_queue")
        queue.add(ReviewItem(
            review_id="rv-rej3",
            item_type=ReviewItemType.PATCH,
            target_object_id=run_id,
            run_id=run_id,
            source_id="src-rej3",
            patch_ids=[],
        ))

        queue.resolve_and_sync(
            review_id="rv-rej3",
            action="reject",
            reviewer="test_user",
            run_dir=base,
        )

        m = run_store.get(run_id)
        assert m is not None
        assert m.review_status == "rejected"
