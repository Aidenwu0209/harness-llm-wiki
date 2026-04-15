"""Tests for US-005: Sync review approval with patch and manifest state."""

from __future__ import annotations

import json
from pathlib import Path

from docos.artifact_stores import PatchStore
from docos.models.patch import BlastRadius, Change, ChangeType, MergeStatus, Patch
from docos.models.run import RunStatus, StageStatus
from docos.review.queue import ReviewItem, ReviewItemType, ReviewQueue
from docos.run_store import RunStore


def _setup_env(tmp_path: Path) -> tuple[RunStore, PatchStore, ReviewQueue, str, str]:
    """Set up stores and create a manifest + patch + review item."""
    store = RunStore(tmp_path / "runs")
    manifest = store.create(
        source_id="src-sync",
        source_hash="hash123",
        source_file_path="/tmp/test.pdf",
    )
    manifest.status = RunStatus.RUNNING
    manifest.review_status = "pending"
    store.update(manifest)

    patch_store = PatchStore(tmp_path / "patches")
    patch = Patch(
        patch_id="p-sync-001",
        run_id=manifest.run_id,
        source_id="src-sync",
        changes=[Change(type=ChangeType.CREATE_PAGE, target="page.md")],
        risk_score=0.5,
        blast_radius=BlastRadius(pages=1),
    )
    patch.stage()
    patch_store.save(patch)

    queue = ReviewQueue(tmp_path / "review")
    item = ReviewItem(
        review_id="rv-sync-001",
        item_type=ReviewItemType.PATCH,
        target_object_id=manifest.run_id,
        run_id=manifest.run_id,
        source_id="src-sync",
        patch_ids=["p-sync-001"],
        gate_reasons=["high_risk"],
    )
    queue.add(item)

    return store, patch_store, queue, manifest.run_id, "rv-sync-001"


class TestReviewApprovalSync:
    """US-005: Approving a review item updates patch and manifest state."""

    def test_approval_transitions_linked_patches(self, tmp_path: Path) -> None:
        """Approving a review item transitions all linked patches to approved/merged."""
        store, patch_store, queue, run_id, review_id = _setup_env(tmp_path)

        item, report = queue.resolve_and_sync(
            review_id=review_id,
            action="approve",
            reviewer="alice",
            reason="LGTM",
            patch_dir=tmp_path / "patches",
            run_dir=tmp_path / "runs",
        )

        assert item is not None
        assert item.status.value == "approved"

        # Verify patch is now approved/merged
        patch = patch_store.get("p-sync-001")
        assert patch is not None
        assert patch.merge_status == MergeStatus.APPROVED
        assert "p-sync-001" in report["patches_updated"]

    def test_approval_updates_manifest_review_status(self, tmp_path: Path) -> None:
        """Approving updates manifest review_status and release_decision."""
        store, patch_store, queue, run_id, review_id = _setup_env(tmp_path)

        _, report = queue.resolve_and_sync(
            review_id=review_id,
            action="approve",
            reviewer="bob",
            reason="Approved after review",
            patch_dir=tmp_path / "patches",
            run_dir=tmp_path / "runs",
        )

        manifest = store.get(run_id)
        assert manifest is not None
        assert manifest.review_status == "approved"
        assert any("bob" in r for r in manifest.release_reasoning)
        assert report["manifest_updated"]

    def test_approval_writes_resolution_artifact(self, tmp_path: Path) -> None:
        """Approval writes a resolution artifact visible from artifact inspection."""
        store, patch_store, queue, run_id, review_id = _setup_env(tmp_path)

        _, report = queue.resolve_and_sync(
            review_id=review_id,
            action="approve",
            reviewer="carol",
            reason="Looks good",
            patch_dir=tmp_path / "patches",
            run_dir=tmp_path / "runs",
        )

        assert "resolution_artifact" in report
        resolution_path = Path(report["resolution_artifact"])
        assert resolution_path.exists()

        data = json.loads(resolution_path.read_text(encoding="utf-8"))
        assert data["review_id"] == "rv-sync-001"
        assert data["action"] == "approve"
        assert data["reviewer"] == "carol"
        assert data["run_id"] == run_id
        assert "p-sync-001" in data["patches_updated"]

    def test_approval_with_multiple_patches(self, tmp_path: Path) -> None:
        """Approving transitions all linked patches, not just the first."""
        store = RunStore(tmp_path / "runs")
        manifest = store.create(
            source_id="src-multi",
            source_hash="hash123",
            source_file_path="/tmp/test.pdf",
        )
        manifest.review_status = "pending"
        store.update(manifest)

        patch_store = PatchStore(tmp_path / "patches")
        patch_ids = []
        for i in range(3):
            pid = f"p-multi-{i:03d}"
            patch_ids.append(pid)
            p = Patch(
                patch_id=pid,
                run_id=manifest.run_id,
                source_id="src-multi",
                changes=[Change(type=ChangeType.CREATE_PAGE, target=f"page_{i}.md")],
                risk_score=0.5,
                blast_radius=BlastRadius(pages=1),
            )
            p.stage()
            patch_store.save(p)

        queue = ReviewQueue(tmp_path / "review")
        item = ReviewItem(
            review_id="rv-multi-001",
            item_type=ReviewItemType.PATCH,
            target_object_id=manifest.run_id,
            run_id=manifest.run_id,
            source_id="src-multi",
            patch_ids=patch_ids,
        )
        queue.add(item)

        _, report = queue.resolve_and_sync(
            review_id="rv-multi-001",
            action="approve",
            reviewer="dave",
            patch_dir=tmp_path / "patches",
            run_dir=tmp_path / "runs",
        )

        assert len(report["patches_updated"]) == 3
        for pid in patch_ids:
            patch = patch_store.get(pid)
            assert patch is not None
            assert patch.merge_status == MergeStatus.APPROVED
