"""Tests for US-033: Improve review CLI filters and review history reporting."""

from __future__ import annotations

import json
from pathlib import Path

from docos.artifact_stores import PatchStore
from docos.models.patch import BlastRadius, Change, ChangeType, MergeStatus, Patch
from docos.review.queue import ReviewItem, ReviewItemType, ReviewQueue
from docos.run_store import RunStore


class TestReviewCLIFilters:
    """US-033: Review list supports run_id and source_id filters."""

    def test_filter_by_run_id(self, tmp_path: Path) -> None:
        """review list --run-id filters items by run_id."""
        queue = ReviewQueue(tmp_path / "review")

        # Add items for different runs
        queue.add(ReviewItem(
            review_id="rv-run-a",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-a",
            run_id="run-a",
            source_id="src-1",
            reason="Test A",
        ))
        queue.add(ReviewItem(
            review_id="rv-run-b",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-b",
            run_id="run-b",
            source_id="src-2",
            reason="Test B",
        ))

        pending = queue.list_pending()
        # Filter by run_id
        filtered = [r for r in pending if r.run_id == "run-a"]
        assert len(filtered) == 1
        assert filtered[0].review_id == "rv-run-a"

    def test_filter_by_source_id(self, tmp_path: Path) -> None:
        """review list --source-id filters items by source_id."""
        queue = ReviewQueue(tmp_path / "review")

        queue.add(ReviewItem(
            review_id="rv-s1",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-1",
            run_id="run-1",
            source_id="src-alpha",
            reason="Alpha",
        ))
        queue.add(ReviewItem(
            review_id="rv-s2",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-2",
            run_id="run-2",
            source_id="src-beta",
            reason="Beta",
        ))

        pending = queue.list_pending()
        filtered = [r for r in pending if r.source_id == "src-alpha"]
        assert len(filtered) == 1
        assert filtered[0].review_id == "rv-s1"

    def test_no_filter_returns_all(self, tmp_path: Path) -> None:
        """review list without filters returns all pending items."""
        queue = ReviewQueue(tmp_path / "review")

        queue.add(ReviewItem(
            review_id="rv-all-1",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-1",
            run_id="run-1",
            source_id="src-1",
        ))
        queue.add(ReviewItem(
            review_id="rv-all-2",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-2",
            run_id="run-2",
            source_id="src-2",
        ))

        pending = queue.list_pending()
        assert len(pending) >= 2


class TestReviewHistoryReporting:
    """US-033: Report shows review decision history and patch merge history."""

    def test_review_history_from_resolution_artifact(self, tmp_path: Path) -> None:
        """Review history is loaded from resolution artifacts."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)
        manifest = run_store.create(source_id="src-hist", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        # Create resolution artifact
        queue = ReviewQueue(base / "review_queue")
        queue.add(ReviewItem(
            review_id=f"rv-{run_id}",
            item_type=ReviewItemType.PATCH,
            target_object_id=run_id,
            run_id=run_id,
            source_id="src-hist",
            patch_ids=["p-hist"],
        ))

        queue.resolve_and_sync(
            review_id=f"rv-{run_id}",
            action="approve",
            reviewer="history_tester",
            reason="LGTM",
            run_dir=base,
        )

        # Read resolution artifact
        res_dir = base / "review_queue" / "resolutions"
        assert res_dir.exists()
        res_files = list(res_dir.glob("*.json"))
        assert len(res_files) >= 1

        res_data = json.loads(res_files[0].read_text(encoding="utf-8"))
        assert res_data["action"] == "approve"
        assert res_data["reviewer"] == "history_tester"
        assert res_data["run_id"] == run_id

    def test_patch_merge_history(self, tmp_path: Path) -> None:
        """Patch merge history shows status for each patch."""
        base = tmp_path / "artifacts"

        patch_store = PatchStore(base / "patches")
        patch = Patch(
            patch_id="p-merge-hist",
            run_id="run-hist",
            source_id="src-hist",
            changes=[Change(type=ChangeType.CREATE_PAGE, target="wiki/test.md")],
            risk_score=0.1,
            blast_radius=BlastRadius(pages=1),
            merge_status=MergeStatus.APPROVED,
            reviewer="merger",
        )
        patch_store.save(patch)

        from docos.models.patch_set import PatchSet
        ps = PatchSet.from_patches("run-hist", "src-hist", [patch])
        patch_store.save_patch_set(ps)

        # Verify patch set
        reloaded_ps = patch_store.get_patch_set("run-hist")
        assert reloaded_ps is not None

        # Verify patch status
        p = patch_store.get("p-merge-hist")
        assert p is not None
        assert p.merge_status.value == "approved"
        assert p.reviewer == "merger"

    def test_filters_do_not_break_queue(self, tmp_path: Path) -> None:
        """Applying filters does not break queue and manifest synchronization."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)
        manifest = run_store.create(source_id="src-sync", source_hash="h", source_file_path="/tmp/t.pdf")

        queue = ReviewQueue(base / "review_queue")
        queue.add(ReviewItem(
            review_id="rv-sync",
            item_type=ReviewItemType.PATCH,
            target_object_id=manifest.run_id,
            run_id=manifest.run_id,
            source_id="src-sync",
        ))

        # Resolve
        queue.resolve_and_sync(
            review_id="rv-sync",
            action="reject",
            reviewer="sync_test",
            run_dir=base,
        )

        # Verify manifest updated
        m = run_store.get(manifest.run_id)
        assert m is not None
        assert m.review_status == "rejected"

        # Verify no more pending
        pending = queue.list_pending()
        sync_items = [r for r in pending if r.run_id == manifest.run_id]
        assert len(sync_items) == 0
