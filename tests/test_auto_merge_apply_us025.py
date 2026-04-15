"""Tests for US-025: Make auto-merge apply wiki state for merged patches."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import WikiStore, WikiPageState
from docos.models.patch import BlastRadius, Change, ChangeType, MergeStatus, Patch
from docos.patch_apply import PatchApplyService


def _make_mergeable_patch(
    patch_id: str = "p-1",
    target: str = "wiki/source/test.md",
) -> Patch:
    """Create a low-risk patch that is merge-eligible."""
    return Patch(
        patch_id=patch_id,
        run_id="run-auto",
        source_id="src-auto",
        changes=[Change(type=ChangeType.CREATE_PAGE, target=target)],
        risk_score=0.1,
        blast_radius=BlastRadius(pages=1),
        review_required=False,
    )


class TestAutoMergeApply:
    """US-025: Auto-merge path applies wiki state through PatchApplyService."""

    def test_auto_merge_writes_wiki_files(self, tmp_path: Path) -> None:
        """After auto-merge, markdown files exist with merged content."""
        wiki_dir = tmp_path / "wiki"
        wiki_store = WikiStore(tmp_path / "wiki_state")

        # Pre-populate wiki state
        wiki_store.save(WikiPageState(
            page_path="wiki/source/test.md", run_id="run-auto",
            frontmatter={"id": "test", "title": "Test Page"},
            body="# Test\nMerged content here.",
        ))

        patches = [_make_mergeable_patch()]

        # Apply through PatchApplyService (same as auto-merge path)
        apply_svc = PatchApplyService(wiki_dir, wiki_store)
        results = apply_svc.apply_batch(patches)

        assert all(r.applied for r in results)
        md_file = wiki_dir / "wiki/source/test.md"
        assert md_file.exists()
        content = md_file.read_text()
        assert "Merged content here." in content

    def test_auto_merge_multiple_patches(self, tmp_path: Path) -> None:
        """Auto-merge applies all patches in the batch."""
        wiki_dir = tmp_path / "wiki"
        wiki_store = WikiStore(tmp_path / "wiki_state")

        wiki_store.save(WikiPageState(
            page_path="wiki/source/a.md", run_id="run-auto",
            frontmatter={"id": "a"}, body="Page A",
        ))
        wiki_store.save(WikiPageState(
            page_path="wiki/entities/b.md", run_id="run-auto",
            frontmatter={"id": "b"}, body="Entity B",
        ))

        patches = [
            _make_mergeable_patch("p-a", "wiki/source/a.md"),
            _make_mergeable_patch("p-b", "wiki/entities/b.md"),
        ]

        apply_svc = PatchApplyService(wiki_dir, wiki_store)
        results = apply_svc.apply_batch(patches)

        assert len(results) == 2
        assert (wiki_dir / "wiki/source/a.md").exists()
        assert (wiki_dir / "wiki/entities/b.md").exists()

    def test_auto_merge_idempotent(self, tmp_path: Path) -> None:
        """Re-applying auto-merged patches does not create extra diffs."""
        wiki_dir = tmp_path / "wiki"
        wiki_store = WikiStore(tmp_path / "wiki_state")

        wiki_store.save(WikiPageState(
            page_path="wiki/source/test.md", run_id="run-auto",
            frontmatter={"id": "test"}, body="content",
        ))

        patches = [_make_mergeable_patch()]
        apply_svc = PatchApplyService(wiki_dir, wiki_store)

        # First apply
        apply_svc.apply_batch(patches)
        md_file = wiki_dir / "wiki/source/test.md"
        first_content = md_file.read_text()

        # Second apply (should be no-op)
        apply_svc.apply_batch(patches)
        second_content = md_file.read_text()

        assert first_content == second_content
