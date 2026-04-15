"""Tests for US-030: Approve-closes-loop golden scenario."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import PatchStore, WikiStore, WikiPageState
from docos.models.patch import BlastRadius, Change, ChangeType, MergeStatus, Patch
from docos.patch_apply import PatchApplyService
from docos.review.queue import ReviewItem, ReviewItemType, ReviewQueue
from docos.run_store import RunStore


class TestGoldenApproveClosesLoop:
    """US-030: Golden scenario proving approval merges wiki and closes loop."""

    def test_approve_closes_loop(self, tmp_path: Path) -> None:
        """Starting from pending, approving merges wiki state and closes loop."""
        base = tmp_path / "artifacts"

        # Setup run
        run_store = RunStore(base)
        manifest = run_store.create(source_id="src-approve", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        # Create high-risk patch (pending review)
        patch = Patch(
            patch_id="p-loop",
            run_id=run_id,
            source_id="src-approve",
            changes=[Change(type=ChangeType.CREATE_PAGE, target="wiki/entities/loop.md")],
            risk_score=0.8,
            blast_radius=BlastRadius(pages=3),
            review_required=True,
        )
        patch_store = PatchStore(base / "patches")
        patch_store.save(patch)

        # Wiki state
        wiki_dir = base / "wiki"
        wiki_store = WikiStore(base / "wiki_state")
        wiki_store.save(WikiPageState(
            page_path="wiki/entities/loop.md", run_id=run_id,
            frontmatter={"id": "loop", "type": "entity", "title": "Loop Entity"},
            body="# Loop Entity\nThis entity was approved through the review loop.",
        ))

        # Create pending review
        queue = ReviewQueue(base / "review_queue")
        review_id = f"rv-{run_id}"
        queue.add(ReviewItem(
            review_id=review_id,
            item_type=ReviewItemType.PATCH,
            target_object_id=run_id,
            run_id=run_id,
            source_id="src-approve",
            patch_ids=["p-loop"],
            gate_reasons=["High risk"],
        ))

        # Verify initial state: wiki not written
        assert not (wiki_dir / "wiki/entities/loop.md").exists()

        # Approve
        item, report = queue.resolve_and_sync(
            review_id=review_id,
            action="approve",
            reviewer="golden_tester",
            reason="All checks pass, content verified",
            patch_dir=base / "patches",
            run_dir=base,
            wiki_dir=wiki_dir,
            wiki_state_dir=base / "wiki_state",
        )

        # Verify approval
        assert item is not None
        assert item.actions[-1].decision.value == "approved"

        # Verify patches are approved
        p = patch_store.get("p-loop")
        assert p is not None
        assert p.merge_status.value == "approved"

        # Verify wiki state applied
        assert report.get("wiki_applied", 0) > 0
        md_file = wiki_dir / "wiki/entities/loop.md"
        assert md_file.exists()
        content = md_file.read_text()
        assert "Loop Entity" in content

        # Verify manifest updated
        m = run_store.get(run_id)
        assert m is not None
        assert m.review_status == "approved"

    def test_report_shows_approved_after_approval(self, tmp_path: Path) -> None:
        """Report output reflects approved status after approval."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)
        manifest = run_store.create(source_id="src-rpt", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        # Set up manifest with pending review
        manifest.review_status = "pending"
        manifest.review_ids = ["rv-rpt"]
        run_store.update(manifest)

        # Create review item
        queue = ReviewQueue(base / "review_queue")
        queue.add(ReviewItem(
            review_id="rv-rpt",
            item_type=ReviewItemType.PATCH,
            target_object_id=run_id,
            run_id=run_id,
            source_id="src-rpt",
            patch_ids=[],
        ))

        # Approve
        queue.resolve_and_sync(
            review_id="rv-rpt",
            action="approve",
            reviewer="tester",
            run_dir=base,
        )

        m = run_store.get(run_id)
        assert m is not None
        assert m.review_status == "approved"
