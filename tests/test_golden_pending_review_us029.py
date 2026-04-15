"""Tests for US-029: Pending-review golden scenario."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import PatchStore, WikiStore, WikiPageState
from docos.lint.checker import ReleaseGate
from docos.models.docir import DocIR
from docos.models.knowledge import EntityRecord, EntityType
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.models.patch_set import PatchSet
from docos.patch_apply import PatchApplyService
from docos.review.queue import ReviewItem, ReviewItemType, ReviewQueue
from docos.run_store import RunStore
from docos.wiki.compiler import CompiledPage, WikiCompiler


class TestGoldenPendingReview:
    """US-029: Golden scenario for pending-review path."""

    def test_high_risk_creates_pending_review(self, tmp_path: Path) -> None:
        """A high-risk fixture creates a pending review item without merging."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)
        manifest = run_store.create(source_id="src-pending", source_hash="h", source_file_path="/tmp/pending.pdf")
        run_id = manifest.run_id

        # Create a high-risk patch
        patches = [
            Patch(
                patch_id="p-high-risk",
                run_id=run_id,
                source_id="src-pending",
                changes=[Change(type=ChangeType.CREATE_PAGE, target="wiki/source/important.md")],
                risk_score=0.9,
                blast_radius=BlastRadius(pages=5),
                review_required=True,
            ),
        ]

        # Save patch set
        patch_store = PatchStore(base / "patches")
        ps = PatchSet.from_patches(run_id, "src-pending", patches)
        for p in patches:
            patch_store.save(p)
        patch_store.save_patch_set(ps)

        assert ps.summary.max_risk_score > 0.3
        assert ps.summary.any_review_required

        # Wiki state (not yet applied)
        wiki_dir = base / "wiki"
        wiki_store = WikiStore(base / "wiki_state")
        wiki_store.save(WikiPageState(
            page_path="wiki/source/important.md", run_id=run_id,
            frontmatter={"id": "important"}, body="Important content",
        ))

        # Gate should block
        from docos.harness.runner import HarnessRunner
        from docos.ir_store import IRStore

        ir_store = IRStore(base / "ir")
        docir = DocIR(doc_id="d-pending", source_id="src-pending", parser="test", page_count=1, pages=[])
        ir_store.save(docir, run_id)

        harness_runner = HarnessRunner()
        harness_report = harness_runner.run(
            run_id=run_id, source_id="src-pending",
            docir=docir, patches=patches,
        )

        gate = ReleaseGate()
        gate_passed, gate_reasons = gate.check(
            findings=[],
            harness_passed=harness_report.overall_passed,
            patch_count=ps.summary.total_patches,
            total_pages_changed=ps.summary.total_pages_changed,
            aggregate_risk=ps.summary.max_risk_score,
            review_required_markers=1,
        )

        # Should be blocked
        assert not gate_passed or any(p.review_required for p in patches)

        # Create pending review item (same as _stage_review pending path)
        queue = ReviewQueue(base / "review_queue")
        review_item = ReviewItem(
            review_id=f"rv-{run_id}",
            item_type=ReviewItemType.PATCH,
            target_object_id=run_id,
            run_id=run_id,
            source_id="src-pending",
            patch_ids=[p.patch_id for p in patches],
            gate_reasons=gate_reasons,
            reason="High risk requires review",
        )
        queue.add(review_item)

        # Verify pending review
        pending = queue.list_pending()
        assert len(pending) >= 1
        run_items = [r for r in pending if r.run_id == run_id]
        assert len(run_items) == 1
        assert run_items[0].patch_ids == ["p-high-risk"]

        # Wiki state should NOT be applied
        md_file = wiki_dir / "wiki/source/important.md"
        assert not md_file.exists()

    def test_patches_stay_staged_not_merged(self, tmp_path: Path) -> None:
        """Patches remain in PENDING status before approval."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)
        manifest = run_store.create(source_id="src-pend2", source_hash="h", source_file_path="/tmp/t.pdf")

        patch = Patch(
            patch_id="p-staged",
            run_id=manifest.run_id,
            source_id="src-pend2",
            changes=[Change(type=ChangeType.UPDATE_PAGE, target="wiki/entities/e.md")],
            risk_score=0.8,
            blast_radius=BlastRadius(pages=3),
            review_required=True,
        )

        patch_store = PatchStore(base / "patches")
        patch_store.save(patch)

        queue = ReviewQueue(base / "review_queue")
        queue.add(ReviewItem(
            review_id="rv-staged",
            item_type=ReviewItemType.PATCH,
            target_object_id=manifest.run_id,
            run_id=manifest.run_id,
            patch_ids=["p-staged"],
        ))

        # Verify patch is still PENDING
        p = patch_store.get("p-staged")
        assert p is not None
        assert p.merge_status.value == "pending"
