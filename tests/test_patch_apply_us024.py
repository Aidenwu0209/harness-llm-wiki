"""Tests for US-024: Add PatchApplyService for create, update, and delete writes."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import WikiStore, WikiPageState
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.patch_apply import PatchApplyService


def _make_patch(
    patch_id: str = "p-1",
    run_id: str = "run-1",
    source_id: str = "src-1",
    changes: list[Change] | None = None,
) -> Patch:
    return Patch(
        patch_id=patch_id,
        run_id=run_id,
        source_id=source_id,
        changes=changes or [],
        risk_score=0.1,
        blast_radius=BlastRadius(pages=1),
    )


class TestPatchApplyService:
    """US-024: PatchApplyService handles create, update, and delete."""

    def test_create_page_writes_file(self, tmp_path: Path) -> None:
        """Applying a CREATE_PAGE patch writes the markdown file."""
        wiki_dir = tmp_path / "wiki"
        wiki_state_dir = tmp_path / "wiki_state"
        wiki_store = WikiStore(wiki_state_dir)

        # Pre-populate wiki state
        wiki_store.save(WikiPageState(
            page_path="wiki/source/test.md", run_id="run-1",
            frontmatter={"id": "test", "title": "Test"},
            body="# Test\nHello world.",
        ))

        service = PatchApplyService(wiki_dir, wiki_store)
        patch = _make_patch(changes=[
            Change(type=ChangeType.CREATE_PAGE, target="wiki/source/test.md"),
        ])

        result = service.apply(patch)
        assert result.applied
        assert result.changes_applied == 1

        # Verify file exists
        md_file = wiki_dir / "wiki/source/test.md"
        assert md_file.exists()
        content = md_file.read_text()
        assert "Hello world." in content

    def test_update_page_overwrites_file(self, tmp_path: Path) -> None:
        """Applying an UPDATE_PAGE patch overwrites the markdown file."""
        wiki_dir = tmp_path / "wiki"
        wiki_state_dir = tmp_path / "wiki_state"
        wiki_store = WikiStore(wiki_state_dir)

        # Create initial file
        md_file = wiki_dir / "wiki/source/test.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text("old content")

        # Update wiki state with new content
        wiki_store.save(WikiPageState(
            page_path="wiki/source/test.md", run_id="run-1",
            frontmatter={"id": "test", "title": "Updated"},
            body="# Updated\nNew content.",
        ))

        service = PatchApplyService(wiki_dir, wiki_store)
        patch = _make_patch(changes=[
            Change(type=ChangeType.UPDATE_PAGE, target="wiki/source/test.md"),
        ])

        result = service.apply(patch)
        assert result.applied
        assert result.changes_applied == 1

        content = md_file.read_text()
        assert "New content." in content

    def test_delete_page_removes_file(self, tmp_path: Path) -> None:
        """Applying a DELETE_PAGE patch removes the markdown file."""
        wiki_dir = tmp_path / "wiki"
        wiki_state_dir = tmp_path / "wiki_state"
        wiki_store = WikiStore(wiki_state_dir)

        # Create initial file
        md_file = wiki_dir / "wiki/entities/old.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text("to be deleted")

        service = PatchApplyService(wiki_dir, wiki_store)
        patch = _make_patch(changes=[
            Change(type=ChangeType.DELETE_PAGE, target="wiki/entities/old.md"),
        ])

        result = service.apply(patch)
        assert result.applied
        assert result.changes_applied == 1
        assert not md_file.exists()

    def test_idempotent_apply(self, tmp_path: Path) -> None:
        """Applying the same patch twice does not create extra writes."""
        wiki_dir = tmp_path / "wiki"
        wiki_state_dir = tmp_path / "wiki_state"
        wiki_store = WikiStore(wiki_state_dir)

        wiki_store.save(WikiPageState(
            page_path="wiki/source/test.md", run_id="run-1",
            frontmatter={"id": "test"}, body="content",
        ))

        service = PatchApplyService(wiki_dir, wiki_store)
        patch = _make_patch(changes=[
            Change(type=ChangeType.CREATE_PAGE, target="wiki/source/test.md"),
        ])

        result1 = service.apply(patch)
        assert result1.applied
        assert result1.changes_applied == 1

        result2 = service.apply(patch)
        assert result2.applied
        assert result2.changes_applied == 0
        assert "already_applied" in result2.skipped

    def test_apply_batch(self, tmp_path: Path) -> None:
        """Apply multiple patches in order."""
        wiki_dir = tmp_path / "wiki"
        wiki_state_dir = tmp_path / "wiki_state"
        wiki_store = WikiStore(wiki_state_dir)

        wiki_store.save(WikiPageState(
            page_path="wiki/source/a.md", run_id="run-1",
            frontmatter={"id": "a"}, body="Page A",
        ))
        wiki_store.save(WikiPageState(
            page_path="wiki/source/b.md", run_id="run-1",
            frontmatter={"id": "b"}, body="Page B",
        ))

        service = PatchApplyService(wiki_dir, wiki_store)
        p1 = _make_patch(patch_id="p-a", changes=[
            Change(type=ChangeType.CREATE_PAGE, target="wiki/source/a.md"),
        ])
        p2 = _make_patch(patch_id="p-b", changes=[
            Change(type=ChangeType.CREATE_PAGE, target="wiki/source/b.md"),
        ])

        results = service.apply_batch([p1, p2])
        assert len(results) == 2
        assert all(r.applied for r in results)

        assert (wiki_dir / "wiki/source/a.md").exists()
        assert (wiki_dir / "wiki/source/b.md").exists()

    def test_rollback_restores_state(self, tmp_path: Path) -> None:
        """Rollback removes applied state and writes rollback artifact."""
        wiki_dir = tmp_path / "wiki"
        wiki_state_dir = tmp_path / "wiki_state"
        wiki_store = WikiStore(wiki_state_dir)

        wiki_store.save(WikiPageState(
            page_path="wiki/entities/e.md", run_id="run-1",
            frontmatter={"id": "e"}, body="Entity page",
        ))

        service = PatchApplyService(wiki_dir, wiki_store)
        patch = _make_patch(patch_id="p-del", changes=[
            Change(type=ChangeType.DELETE_PAGE, target="wiki/entities/e.md"),
        ])

        # Create the file first
        md_file = wiki_dir / "wiki/entities/e.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text("Entity page content")

        # Apply delete
        service.apply(patch)
        assert not md_file.exists()

        # Rollback — restore the deleted page from wiki state
        rollback_result = service.rollback(patch)
        assert rollback_result.applied

        # Rollback artifact exists
        assert (wiki_dir / f"rollback-p-del.json").exists()
