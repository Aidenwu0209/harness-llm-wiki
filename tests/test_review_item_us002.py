"""Tests for US-002: Upgrade review items to run-level patch-set objects."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.review.queue import ReviewItem, ReviewItemType, ReviewQueue


class TestReviewItemPatchSetFields:
    """US-002: ReviewItem stores run-level patch-set fields."""

    def test_review_item_stores_run_id(self) -> None:
        """ReviewItem accepts run_id field."""
        item = ReviewItem(
            review_id="rv-001",
            item_type=ReviewItemType.PATCH,
            target_object_id="p-001",
            run_id="run-abc",
            source_id="src-123",
        )
        assert item.run_id == "run-abc"
        assert item.source_id == "src-123"

    def test_review_item_stores_patch_ids(self) -> None:
        """ReviewItem stores a list of related patch_ids."""
        item = ReviewItem(
            review_id="rv-002",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-xyz",
            run_id="run-xyz",
            patch_ids=["p-001", "p-002", "p-003"],
        )
        assert item.patch_ids == ["p-001", "p-002", "p-003"]

    def test_review_item_stores_gate_reasons(self) -> None:
        """ReviewItem persists gate reasons."""
        item = ReviewItem(
            review_id="rv-003",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-def",
            gate_reasons=["high_risk_score", "cross_page_change"],
        )
        assert item.gate_reasons == ["high_risk_score", "cross_page_change"]

    def test_review_item_stores_lint_summary(self) -> None:
        """ReviewItem persists lint summary."""
        item = ReviewItem(
            review_id="rv-004",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-ghi",
            lint_summary={"error": 1, "warning": 3},
        )
        assert item.lint_summary == {"error": 1, "warning": 3}

    def test_review_item_stores_harness_summary(self) -> None:
        """ReviewItem persists harness summary."""
        harness_data = {"overall_passed": False, "total_checks": 5, "passed_checks": 3}
        item = ReviewItem(
            review_id="rv-005",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-jkl",
            harness_summary=harness_data,
        )
        assert item.harness_summary == harness_data


class TestReviewItemPersistence:
    """US-002: Run-level review items can be saved and reloaded from disk."""

    def test_save_and_reload_run_level_item(self, tmp_path: Path) -> None:
        """A saved run-level review item can be reloaded with all patch references."""
        queue = ReviewQueue(tmp_path / "review")

        item = ReviewItem(
            review_id="rv-persist-001",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-persist-001",
            run_id="run-persist-001",
            source_id="src-persist-001",
            patch_ids=["p-100", "p-101", "p-102"],
            gate_reasons=["lint_errors", "harness_failed"],
            lint_summary={"error": 2, "warning": 1},
            harness_summary={"overall_passed": False, "total_checks": 4},
            reason="High-risk patch set requires manual review",
        )

        queue.add(item)

        # Create a new queue instance to reload from disk
        queue2 = ReviewQueue(tmp_path / "review")
        reloaded = queue2.get("rv-persist-001")

        assert reloaded is not None
        assert reloaded.run_id == "run-persist-001"
        assert reloaded.source_id == "src-persist-001"
        assert reloaded.patch_ids == ["p-100", "p-101", "p-102"]
        assert reloaded.gate_reasons == ["lint_errors", "harness_failed"]
        assert reloaded.lint_summary == {"error": 2, "warning": 1}
        assert reloaded.harness_summary == {"overall_passed": False, "total_checks": 4}
        assert reloaded.reason == "High-risk patch set requires manual review"

    def test_json_file_contains_patch_set_fields(self, tmp_path: Path) -> None:
        """Persisted JSON file contains all run-level patch-set fields."""
        queue = ReviewQueue(tmp_path / "review")

        item = ReviewItem(
            review_id="rv-json-001",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-json-001",
            run_id="run-json-001",
            patch_ids=["p-200"],
            gate_reasons=["cross_page_conflict"],
            lint_summary={"warning": 1},
            harness_summary={"overall_passed": True},
        )

        queue.add(item)

        # Read the persisted JSON file directly
        json_path = tmp_path / "review" / "queue" / "rv-json-001.json"
        assert json_path.exists()

        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["run_id"] == "run-json-001"
        assert data["patch_ids"] == ["p-200"]
        assert data["gate_reasons"] == ["cross_page_conflict"]
        assert data["lint_summary"] == {"warning": 1}
        assert data["harness_summary"] == {"overall_passed": True}

    def test_backward_compat_without_new_fields(self, tmp_path: Path) -> None:
        """Old review items without patch-set fields still load correctly."""
        queue = ReviewQueue(tmp_path / "review")

        # Create a minimal item without new fields
        item = ReviewItem(
            review_id="rv-old-001",
            item_type=ReviewItemType.CONFLICT_CLAIM,
            target_object_id="claim-001",
            source_id="src-old",
        )
        queue.add(item)

        # Reload
        queue2 = ReviewQueue(tmp_path / "review")
        reloaded = queue2.get("rv-old-001")

        assert reloaded is not None
        assert reloaded.run_id is None
        assert reloaded.patch_ids == []
        assert reloaded.gate_reasons == []
        assert reloaded.lint_summary == {}
        assert reloaded.harness_summary == {}

    def test_list_pending_includes_run_level_items(self, tmp_path: Path) -> None:
        """list_pending returns run-level items with patch-set fields."""
        queue = ReviewQueue(tmp_path / "review")

        item = ReviewItem(
            review_id="rv-list-001",
            item_type=ReviewItemType.PATCH,
            target_object_id="run-list-001",
            run_id="run-list-001",
            patch_ids=["p-300", "p-301"],
        )
        queue.add(item)

        pending = queue.list_pending()
        assert len(pending) == 1
        assert pending[0].run_id == "run-list-001"
        assert pending[0].patch_ids == ["p-300", "p-301"]
