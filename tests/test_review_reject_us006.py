"""Tests for US-006: Sync review rejection and changes-requested paths."""

from __future__ import annotations

import json
from pathlib import Path

from docos.artifact_stores import PatchStore
from docos.models.patch import BlastRadius, Change, ChangeType, MergeStatus, Patch
from docos.models.run import RunStatus
from docos.review.queue import ReviewItem, ReviewItemType, ReviewQueue
from docos.run_store import RunStore


def _setup_env(tmp_path: Path) -> tuple[RunStore, PatchStore, ReviewQueue, str, str]:
    """Set up stores and create a manifest + patch + review item."""
    store = RunStore(tmp_path / "runs")
    manifest = store.create(
        source_id="src-reject",
        source_hash="hash123",
        source_file_path="/tmp/test.pdf",
    )
    manifest.review_status = "pending"
    store.update(manifest)

    patch_store = PatchStore(tmp_path / "patches")
    patch = Patch(
        patch_id="p-reject-001",
        run_id=manifest.run_id,
        source_id="src-reject",
        changes=[Change(type=ChangeType.CREATE_PAGE, target="page.md")],
        risk_score=0.5,
        blast_radius=BlastRadius(pages=1),
    )
    patch.stage()
    patch_store.save(patch)

    queue = ReviewQueue(tmp_path / "review")
    item = ReviewItem(
        review_id="rv-reject-001",
        item_type=ReviewItemType.PATCH,
        target_object_id=manifest.run_id,
        run_id=manifest.run_id,
        source_id="src-reject",
        patch_ids=["p-reject-001"],
        gate_reasons=["high_risk"],
    )
    queue.add(item)

    return store, patch_store, queue, manifest.run_id, "rv-reject-001"


class TestReviewRejectionSync:
    """US-006: Reject and request-changes update runtime state correctly."""

    def test_reject_moves_patches_to_rejected(self, tmp_path: Path) -> None:
        """Rejecting a review item moves linked patches to rejected state."""
        store, patch_store, queue, run_id, review_id = _setup_env(tmp_path)

        item, report = queue.resolve_and_sync(
            review_id=review_id,
            action="reject",
            reviewer="alice",
            reason="Does not meet quality standards",
            patch_dir=tmp_path / "patches",
            run_dir=tmp_path / "runs",
        )

        assert item is not None
        assert item.status.value == "rejected"

        patch = patch_store.get("p-reject-001")
        assert patch is not None
        assert patch.merge_status == MergeStatus.REJECTED

    def test_reject_does_not_merge_wiki_state(self, tmp_path: Path) -> None:
        """Rejecting leaves wiki state unchanged — patch stays rejected, not merged."""
        store, patch_store, queue, run_id, review_id = _setup_env(tmp_path)

        queue.resolve_and_sync(
            review_id=review_id,
            action="reject",
            reviewer="bob",
            reason="Poor quality",
            patch_dir=tmp_path / "patches",
            run_dir=tmp_path / "runs",
        )

        patch = patch_store.get("p-reject-001")
        assert patch is not None
        # Patch should be rejected, not any merged state
        assert patch.merge_status not in (MergeStatus.AUTO_MERGED, MergeStatus.APPROVED)
        assert patch.merge_status == MergeStatus.REJECTED
        assert patch.merged_at is None

    def test_reject_writes_resolution_artifact(self, tmp_path: Path) -> None:
        """Reject writes a resolution artifact that can be reloaded."""
        store, patch_store, queue, run_id, review_id = _setup_env(tmp_path)

        _, report = queue.resolve_and_sync(
            review_id=review_id,
            action="reject",
            reviewer="carol",
            reason="Wrong data",
            patch_dir=tmp_path / "patches",
            run_dir=tmp_path / "runs",
        )

        assert "resolution_artifact" in report
        resolution_path = Path(report["resolution_artifact"])
        assert resolution_path.exists()

        data = json.loads(resolution_path.read_text(encoding="utf-8"))
        assert data["action"] == "reject"
        assert data["reviewer"] == "carol"
        assert "p-reject-001" in data["patches_updated"]

    def test_request_changes_sets_manifest_status(self, tmp_path: Path) -> None:
        """Request-changes sets manifest to changes_requested without merging."""
        store, patch_store, queue, run_id, review_id = _setup_env(tmp_path)

        _, report = queue.resolve_and_sync(
            review_id=review_id,
            action="request_changes",
            reviewer="dave",
            reason="Needs more detail",
            patch_dir=tmp_path / "patches",
            run_dir=tmp_path / "runs",
        )

        manifest = store.get(run_id)
        assert manifest is not None
        assert manifest.review_status == "changes_requested"
        assert any("dave" in r for r in manifest.release_reasoning)

        # Patch should still be in pending state (not merged, not rejected)
        patch = patch_store.get("p-reject-001")
        assert patch is not None
        assert patch.merge_status == MergeStatus.PENDING

    def test_request_changes_writes_resolution_artifact(self, tmp_path: Path) -> None:
        """Request-changes writes a resolution artifact."""
        store, patch_store, queue, run_id, review_id = _setup_env(tmp_path)

        _, report = queue.resolve_and_sync(
            review_id=review_id,
            action="request_changes",
            reviewer="eve",
            reason="Add more citations",
            patch_dir=tmp_path / "patches",
            run_dir=tmp_path / "runs",
        )

        resolution_path = Path(report["resolution_artifact"])
        assert resolution_path.exists()
        data = json.loads(resolution_path.read_text(encoding="utf-8"))
        assert data["action"] == "request_changes"
        assert data["reviewer"] == "eve"
