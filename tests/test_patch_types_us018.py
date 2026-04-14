"""US-018: Generate patches for create, update, and delete page changes."""

from datetime import date
from pathlib import Path

from docos.models.page import Frontmatter, PageType, PageStatus, ReviewStatus
from docos.models.patch import ChangeType
from docos.wiki.compiler import CompiledPage


def _make_frontmatter(page_id: str = "source.test") -> Frontmatter:
    return Frontmatter(
        id=page_id,
        type=PageType.SOURCE,
        title="Test Page",
        status=PageStatus.AUTO,
        created_at=date(2026, 4, 15),
        updated_at=date(2026, 4, 15),
        review_status=ReviewStatus.PENDING,
    )


class TestCreatePagePatch:
    def test_new_page_returns_create_patch(self) -> None:
        """A new page (no existing content) returns CREATE_PAGE."""
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="# New page\nHello world",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        patch = compiled.compute_patch(run_id="run_1", source_id="src_1")
        assert patch is not None
        assert patch.changes[0].type == ChangeType.CREATE_PAGE
        assert patch.changes[0].summary == "New page creation"

    def test_create_patch_has_correct_target(self) -> None:
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="body",
            page_path=Path("wiki/sources/my_page.md"),
            existing_body=None,
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        assert str(patch.changes[0].target) == "wiki/sources/my_page.md"


class TestUpdatePagePatch:
    def test_changed_content_returns_update_patch(self) -> None:
        """An existing page with changed content returns UPDATE_PAGE."""
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="# Updated content\nNew stuff",
            page_path=Path("wiki/sources/test.md"),
            existing_body="# Old content\nOld stuff",
        )
        patch = compiled.compute_patch(run_id="run_1", source_id="src_1")
        assert patch is not None
        assert patch.changes[0].type == ChangeType.UPDATE_PAGE
        assert patch.changes[0].summary == "Page content update"

    def test_update_patch_has_risk_score(self) -> None:
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="new body",
            page_path=Path("wiki/sources/test.md"),
            existing_body="old body",
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        assert patch.risk_score == 0.3


class TestDeletePagePatch:
    def test_deleted_page_returns_delete_patch(self) -> None:
        """A page marked as deleted returns DELETE_PAGE."""
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="",
            page_path=Path("wiki/sources/test.md"),
            existing_body="old content",
            deleted=True,
        )
        patch = compiled.compute_patch(run_id="run_1", source_id="src_1")
        assert patch is not None
        assert patch.changes[0].type == ChangeType.DELETE_PAGE
        assert patch.changes[0].summary == "Page deletion"

    def test_delete_patch_has_higher_risk(self) -> None:
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="",
            page_path=Path("wiki/sources/test.md"),
            existing_body="content",
            deleted=True,
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        assert patch.risk_score == 0.5


class TestPatchNeverNone:
    def test_all_cases_return_patch(self) -> None:
        """compute_patch always returns a Patch, never None."""
        fm = _make_frontmatter()
        pp = Path("wiki/test.md")

        cases = [
            CompiledPage(frontmatter=fm, body="new", page_path=pp, existing_body=None),
            CompiledPage(frontmatter=fm, body="new", page_path=pp, existing_body="old"),
            CompiledPage(frontmatter=fm, body="", page_path=pp, existing_body="old", deleted=True),
        ]
        for case in cases:
            patch = case.compute_patch(run_id="r", source_id="s")
            assert patch is not None, "compute_patch must never return None"
            assert len(patch.changes) == 1
