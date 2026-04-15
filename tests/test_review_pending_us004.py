"""Tests for US-004: Implement the review stage pending-review path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.artifact_stores import PatchStore
from docos.models.patch import BlastRadius, Change, ChangeType, MergeStatus, Patch
from docos.models.run import RunManifest, RunStatus, StageStatus
from docos.pipeline.runner import PipelineResult, PipelineRunner
from docos.review.queue import ReviewDecision, ReviewQueue
from docos.run_store import RunStore


def _setup_manifest_and_store(tmp_path: Path) -> tuple[RunStore, RunManifest]:
    """Create a RunStore and manifest with all pre-review stages completed."""
    store = RunStore(tmp_path / "artifacts")
    manifest = store.create(
        source_id="src-test",
        source_hash="hash123",
        source_file_path="/tmp/test.pdf",
    )
    manifest.status = RunStatus.RUNNING
    manifest.started_at = manifest.created_at

    for stage_name in ("ingest", "route", "parse", "normalize", "extract", "compile", "patch", "lint", "harness", "gate"):
        manifest.mark_stage(stage_name, StageStatus.COMPLETED)
    store.update(manifest)
    return store, manifest


def _make_patch(patch_id: str, run_id: str, risk_score: float = 0.1, pages: int = 1) -> Patch:
    """Create and stage a test patch."""
    p = Patch(
        patch_id=patch_id,
        run_id=run_id,
        source_id="src-test",
        changes=[Change(type=ChangeType.CREATE_PAGE, target=f"{patch_id}.md")],
        risk_score=risk_score,
        blast_radius=BlastRadius(pages=pages),
    )
    p.stage()
    return p


class TestPendingReviewPath:
    """US-004: High-risk or blocked runs create pending review items."""

    def test_high_risk_patch_creates_pending_review_item(self, tmp_path: Path) -> None:
        """When gate passes but a patch requires review, creates pending review item."""
        store, manifest = _setup_manifest_and_store(tmp_path)
        high_risk_patch = _make_patch("p-high-001", manifest.run_id, risk_score=0.8, pages=5)
        assert high_risk_patch.review_required is True

        PatchStore(tmp_path / "artifacts" / "patches").save(high_risk_patch)

        result = PipelineResult(run_id=manifest.run_id, source_id="src-test", status=RunStatus.RUNNING)

        runner = PipelineRunner.__new__(PipelineRunner)
        runner._base = tmp_path / "artifacts"
        runner._run_store = store

        runner._stage_review(
            manifest=manifest,
            gate_passed=True,
            gate_reasons=[],
            patches=[high_risk_patch],
            result=result,
        )

        queue = ReviewQueue(tmp_path / "artifacts" / "review_queue")
        all_items = queue.list_all()
        assert len(all_items) == 1
        assert all_items[0].run_id == manifest.run_id
        assert "p-high-001" in all_items[0].patch_ids
        assert all_items[0].status == ReviewDecision.PENDING

    def test_pending_review_item_references_all_patch_ids(self, tmp_path: Path) -> None:
        """Pending review item references all patch IDs in the run-level change set."""
        store, manifest = _setup_manifest_and_store(tmp_path)

        patches = [
            _make_patch(f"p-multi-{i:03d}", manifest.run_id, risk_score=0.8 if i == 1 else 0.1)
            for i in range(3)
        ]
        patch_store = PatchStore(tmp_path / "artifacts" / "patches")
        for p in patches:
            patch_store.save(p)

        result = PipelineResult(run_id=manifest.run_id, source_id="src-test", status=RunStatus.RUNNING)

        runner = PipelineRunner.__new__(PipelineRunner)
        runner._base = tmp_path / "artifacts"
        runner._run_store = store

        runner._stage_review(
            manifest=manifest,
            gate_passed=True,
            gate_reasons=[],
            patches=patches,
            result=result,
        )

        queue = ReviewQueue(tmp_path / "artifacts" / "review_queue")
        all_items = queue.list_all()
        assert len(all_items) == 1
        assert len(all_items[0].patch_ids) == 3
        for pid in ("p-multi-000", "p-multi-001", "p-multi-002"):
            assert pid in all_items[0].patch_ids

    def test_manifest_stores_review_ids_for_pending_path(self, tmp_path: Path) -> None:
        """RunManifest stores review_ids for the pending review path."""
        store, manifest = _setup_manifest_and_store(tmp_path)
        high_risk_patch = _make_patch("p-hr-002", manifest.run_id, risk_score=0.9, pages=5)
        PatchStore(tmp_path / "artifacts" / "patches").save(high_risk_patch)

        result = PipelineResult(run_id=manifest.run_id, source_id="src-test", status=RunStatus.RUNNING)

        runner = PipelineRunner.__new__(PipelineRunner)
        runner._base = tmp_path / "artifacts"
        runner._run_store = store

        runner._stage_review(
            manifest=manifest,
            gate_passed=False,
            gate_reasons=["lint_error", "harness_failed"],
            patches=[high_risk_patch],
            result=result,
        )

        assert manifest.review_status == "pending"
        assert len(manifest.review_ids) == 1
        assert manifest.review_ids[0].startswith("rv-")
        assert manifest.review_artifact_path is not None

        review_path = Path(manifest.review_artifact_path)
        assert review_path.exists()
        review_data = json.loads(review_path.read_text(encoding="utf-8"))
        assert review_data["review_status"] == "pending"
        assert review_data["release_decision"] == "blocked"

    def test_gate_blocked_with_normal_patches_creates_pending_item(self, tmp_path: Path) -> None:
        """When gate blocks but patches are low-risk, still creates pending review."""
        store, manifest = _setup_manifest_and_store(tmp_path)
        low_risk_patch = _make_patch("p-lr-003", manifest.run_id, risk_score=0.1, pages=1)
        PatchStore(tmp_path / "artifacts" / "patches").save(low_risk_patch)

        result = PipelineResult(run_id=manifest.run_id, source_id="src-test", status=RunStatus.RUNNING)

        runner = PipelineRunner.__new__(PipelineRunner)
        runner._base = tmp_path / "artifacts"
        runner._run_store = store

        runner._stage_review(
            manifest=manifest,
            gate_passed=False,
            gate_reasons=["lint_error"],
            patches=[low_risk_patch],
            result=result,
        )

        assert manifest.review_status == "pending"
        assert len(manifest.review_ids) == 1

        queue = ReviewQueue(tmp_path / "artifacts" / "review_queue")
        all_items = queue.list_all()
        assert len(all_items) == 1
        assert all_items[0].gate_reasons == ["lint_error"]
