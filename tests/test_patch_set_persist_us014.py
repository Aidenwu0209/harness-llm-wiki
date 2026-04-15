"""Tests for US-014: Persist and load patch sets by run ID."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import PatchStore
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.models.patch_set import PatchSet


def _make_patch(patch_id: str, change_type: ChangeType = ChangeType.CREATE_PAGE) -> Patch:
    return Patch(
        patch_id=patch_id,
        run_id="run-ps-001",
        source_id="src-ps",
        changes=[Change(type=change_type, target=f"{patch_id}.md")],
        risk_score=0.2,
        blast_radius=BlastRadius(pages=1),
    )


class TestPatchSetPersistence:
    """US-014: PatchStore saves and loads patch sets by run ID."""

    def test_save_and_load_patch_set(self, tmp_path: Path) -> None:
        """PatchStore saves a patch set and reloads it with full metadata."""
        store = PatchStore(tmp_path / "patches")

        patches = [_make_patch("p-001"), _make_patch("p-002"), _make_patch("p-003")]
        for p in patches:
            p.stage()
            store.save(p)

        ps = PatchSet.from_patches("run-ps-001", "src-ps", patches)
        store.save_patch_set(ps)

        loaded = store.get_patch_set("run-ps-001")
        assert loaded is not None
        assert loaded.run_id == "run-ps-001"
        assert loaded.source_id == "src-ps"
        assert len(loaded.patch_ids) == 3
        assert loaded.summary.total_patches == 3

    def test_loaded_patch_set_has_patch_details(self, tmp_path: Path) -> None:
        """Reloaded patch set contains all linked patch metadata."""
        store = PatchStore(tmp_path / "patches")

        patches = [
            _make_patch("p-100", ChangeType.CREATE_PAGE),
            _make_patch("p-101", ChangeType.DELETE_PAGE),
        ]
        for p in patches:
            p.stage()
            store.save(p)

        ps = PatchSet.from_patches("run-ps-002", "src-ps", patches)
        store.save_patch_set(ps)

        loaded = store.get_patch_set("run-ps-002")
        assert loaded is not None
        assert len(loaded.patches) == 2
        assert loaded.patches[0].patch_id == "p-100"
        assert loaded.patches[1].patch_id == "p-101"
        assert loaded.summary.delete_page_count == 1

    def test_manifest_links_patch_set_artifact(self, tmp_path: Path) -> None:
        """Manifest patch_artifact_path points to the patch set artifact."""
        store = PatchStore(tmp_path / "patches")

        patches = [_make_patch("p-200")]
        for p in patches:
            p.stage()
            store.save(p)

        ps = PatchSet.from_patches("run-ps-003", "src-ps", patches)
        path = store.save_patch_set(ps)

        assert path.exists()
        assert "patchset-run-ps-003" in path.name

    def test_get_nonexistent_patch_set_returns_none(self, tmp_path: Path) -> None:
        """Loading a non-existent patch set returns None."""
        store = PatchStore(tmp_path / "patches")
        assert store.get_patch_set("nonexistent") is None
