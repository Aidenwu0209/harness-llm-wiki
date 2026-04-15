"""Tests for US-013: Add a PatchSet model for run-level changes."""

from __future__ import annotations

from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.models.patch_set import PatchSet, PatchSetSummary


def _make_patch(
    patch_id: str,
    change_type: ChangeType = ChangeType.CREATE_PAGE,
    risk_score: float = 0.1,
    review_required: bool = False,
) -> Patch:
    p = Patch(
        patch_id=patch_id,
        run_id="run-001",
        source_id="src-001",
        changes=[Change(type=change_type, target=f"{patch_id}.md")],
        risk_score=risk_score,
        blast_radius=BlastRadius(pages=1),
    )
    p.review_required = review_required
    return p


class TestPatchSetModel:
    """US-013: PatchSet model with serialization/deserialization."""

    def test_patch_set_stores_run_and_source_ids(self) -> None:
        """PatchSet stores run_id, source_id, and patch_ids."""
        ps = PatchSet(
            run_id="run-001",
            source_id="src-001",
            patch_ids=["p-001", "p-002"],
        )
        assert ps.run_id == "run-001"
        assert ps.source_id == "src-001"
        assert ps.patch_ids == ["p-001", "p-002"]

    def test_patch_set_from_patches_computes_summary(self) -> None:
        """PatchSet.from_patches computes aggregate summary from linked patches."""
        patches = [
            _make_patch("p-001", ChangeType.CREATE_PAGE, risk_score=0.1),
            _make_patch("p-002", ChangeType.UPDATE_PAGE, risk_score=0.5),
            _make_patch("p-003", ChangeType.DELETE_PAGE, risk_score=0.3, review_required=True),
        ]

        ps = PatchSet.from_patches("run-002", "src-002", patches)

        assert ps.summary.total_patches == 3
        assert ps.summary.create_page_count == 1
        assert ps.summary.update_page_count == 1
        assert ps.summary.delete_page_count == 1
        assert ps.summary.total_pages_changed == 3
        assert ps.summary.max_risk_score == 0.5
        assert ps.summary.any_review_required is True

    def test_patch_set_serialization_roundtrip(self) -> None:
        """PatchSet can be serialized and deserialized with all fields intact."""
        patches = [
            _make_patch("p-010", ChangeType.CREATE_PAGE, risk_score=0.2),
        ]
        ps = PatchSet.from_patches("run-003", "src-003", patches)

        json_str = ps.model_dump_json()
        restored = PatchSet.model_validate_json(json_str)

        assert restored.run_id == "run-003"
        assert restored.source_id == "src-003"
        assert restored.patch_ids == ["p-010"]
        assert restored.summary.total_patches == 1
        assert len(restored.patches) == 1
        assert restored.patches[0].patch_id == "p-010"

    def test_empty_patch_set(self) -> None:
        """PatchSet works with empty patches list."""
        ps = PatchSet.from_patches("run-empty", "src-empty", [])

        assert ps.summary.total_patches == 0
        assert ps.summary.max_risk_score == 0.0
        assert ps.summary.any_review_required is False
        assert ps.patch_ids == []
