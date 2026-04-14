"""US-019: Make patch IDs deterministic from canonical content."""

from datetime import date
from pathlib import Path

from docos.models.page import Frontmatter, PageType, PageStatus, ReviewStatus
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


class TestDeterministicPatchId:
    def test_same_content_same_id(self) -> None:
        """Same body content must produce identical patch_id."""
        compiled_a = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="# Hello\nWorld",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        compiled_b = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="# Hello\nWorld",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        patch_a = compiled_a.compute_patch(run_id="run_1", source_id="src_1")
        patch_b = compiled_b.compute_patch(run_id="run_2", source_id="src_2")
        assert patch_a.patch_id == patch_b.patch_id

    def test_different_content_different_id(self) -> None:
        """Different body content must produce different patch_id."""
        compiled_a = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="Content A",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        compiled_b = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="Content B",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        patch_a = compiled_a.compute_patch(run_id="run_1", source_id="src_1")
        patch_b = compiled_b.compute_patch(run_id="run_1", source_id="src_1")
        assert patch_a.patch_id != patch_b.patch_id

    def test_rerun_stability(self) -> None:
        """Running the same unchanged input twice produces the same patch_id."""
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="Stable content",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        first = compiled.compute_patch(run_id="r1", source_id="s1")
        second = compiled.compute_patch(run_id="r2", source_id="s2")
        assert first.patch_id == second.patch_id

    def test_patch_id_format(self) -> None:
        """Patch ID should start with 'pat_' and end with a hash suffix."""
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(page_id="source.my_doc"),
            body="test content",
            page_path=Path("wiki/sources/my_doc.md"),
            existing_body=None,
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        assert patch.patch_id.startswith("pat_source.my_doc_")
        # Last part after the final underscore is the SHA-256 truncated hash
        suffix = patch.patch_id.rsplit("_", 1)[-1]
        assert len(suffix) == 12

    def test_patch_id_uses_sha256_not_python_hash(self) -> None:
        """Verify patch_id is derived from SHA-256, not Python's built-in hash()."""
        import hashlib

        body = "Deterministic hash test"
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(page_id="source.hash_test"),
            body=body,
            page_path=Path("wiki/sources/hash_test.md"),
            existing_body=None,
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        expected_hash = hashlib.sha256(body.encode()).hexdigest()[:12]
        assert patch.patch_id == f"pat_source.hash_test_{expected_hash}"
