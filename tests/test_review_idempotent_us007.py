"""Tests for US-007: Make review stage creation idempotent and recoverable."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import PatchStore
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.models.run import RunStatus, StageStatus
from docos.pipeline.runner import PipelineResult, PipelineRunner
from docos.review.queue import ReviewDecision, ReviewItem, ReviewItemType, ReviewQueue
from docos.run_store import RunStore


def _setup_env(tmp_path: Path) -> tuple[RunStore, str]:
    """Create store and manifest with all pre-review stages completed."""
    store = RunStore(tmp_path / "artifacts")
    manifest = store.create(
        source_id="src-idem",
        source_hash="hash123",
        source_file_path="/tmp/test.pdf",
    )
    manifest.status = RunStatus.RUNNING
    manifest.started_at = manifest.created_at

    for stage_name in ("ingest", "route", "parse", "normalize", "extract", "compile", "patch", "lint", "harness", "gate"):
        manifest.mark_stage(stage_name, StageStatus.COMPLETED)
    store.update(manifest)
    return store, manifest.run_id


def _make_patch(patch_id: str, run_id: str, risk_score: float = 0.5) -> Patch:
    p = Patch(
        patch_id=patch_id,
        run_id=run_id,
        source_id="src-idem",
        changes=[Change(type=ChangeType.CREATE_PAGE, target=f"{patch_id}.md")],
        risk_score=risk_score,
        blast_radius=BlastRadius(pages=1),
    )
    p.stage()
    return p


class TestReviewIdempotent:
    """US-007: Review stage creation is idempotent and recoverable."""

    def test_re_entering_review_does_not_create_duplicate(self, tmp_path: Path) -> None:
        """Re-entering review stage for same run does not create duplicate items."""
        store, run_id = _setup_env(tmp_path)
        patch = _make_patch("p-idem-001", run_id, risk_score=0.8)
        PatchStore(tmp_path / "artifacts" / "patches").save(patch)

        result = PipelineResult(run_id=run_id, source_id="src-idem", status=RunStatus.RUNNING)
        runner = PipelineRunner.__new__(PipelineRunner)
        runner._base = tmp_path / "artifacts"
        runner._run_store = store

        # First call — creates review item
        runner._stage_review(
            manifest=store.get(run_id),
            gate_passed=False,
            gate_reasons=["high_risk"],
            patches=[patch],
            result=result,
        )

        # Second call — should reuse, not create duplicate
        manifest = store.get(run_id)
        # Reset review stage to RUNNING to simulate re-entry
        manifest.mark_stage("review", StageStatus.RUNNING)
        store.update(manifest)

        result2 = PipelineResult(run_id=run_id, source_id="src-idem", status=RunStatus.RUNNING)
        runner._stage_review(
            manifest=manifest,
            gate_passed=False,
            gate_reasons=["high_risk"],
            patches=[patch],
            result=result2,
        )

        queue = ReviewQueue(tmp_path / "artifacts" / "review_queue")
        all_items = queue.list_all()
        run_items = [i for i in all_items if i.run_id == run_id]
        assert len(run_items) == 1

    def test_find_by_run_id_returns_existing_item(self, tmp_path: Path) -> None:
        """System can find an existing review item by run_id."""
        queue = ReviewQueue(tmp_path / "review")
        item = ReviewItem(
            review_id="rv-find-001",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-find-001",
            run_id="run-find-001",
            source_id="src-find",
            patch_ids=["p-001"],
        )
        queue.add(item)

        found = queue.find_by_run_id("run-find-001")
        assert found is not None
        assert found.review_id == "rv-find-001"

    def test_find_by_run_id_returns_none_for_unknown(self, tmp_path: Path) -> None:
        """find_by_run_id returns None for non-existent run."""
        queue = ReviewQueue(tmp_path / "review")
        assert queue.find_by_run_id("nonexistent") is None

    def test_new_run_creates_new_item_without_overwriting(self, tmp_path: Path) -> None:
        """Rerunning same source under new run creates new item, keeps old."""
        queue = ReviewQueue(tmp_path / "review")

        # First run's review item
        item1 = ReviewItem(
            review_id="rv-run-001",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-001",
            run_id="run-001",
            source_id="src-shared",
            patch_ids=["p-001"],
            reason="First run blocked",
        )
        queue.add(item1)

        # Second run's review item (same source, different run)
        item2 = ReviewItem(
            review_id="rv-run-002",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-002",
            run_id="run-002",
            source_id="src-shared",
            patch_ids=["p-002"],
            reason="Second run blocked",
        )
        queue.add(item2)

        # Both items exist independently
        assert queue.find_by_run_id("run-001") is not None
        assert queue.find_by_run_id("run-002") is not None

        all_items = queue.list_all()
        assert len(all_items) == 2
        run_ids = {i.run_id for i in all_items}
        assert run_ids == {"run-001", "run-002"}
