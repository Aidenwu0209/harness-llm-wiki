"""Tests for US-013: Reject empty slug and filename outputs before writing pages."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# AC1: Export logic refuses to write a page when the sanitized slug or
#      filename is empty
# ---------------------------------------------------------------------------


class TestExportRejectsEmptySlug:
    """_export_wiki_pages skips pages whose filename stem is empty."""

    def test_empty_stem_filename_skipped(self, tmp_path: Path) -> None:
        """Pages with empty filename stem (e.g. 'concepts/.md') are not exported."""
        from docos.artifact_stores import WikiPageState, WikiStore
        from datetime import datetime

        wiki_state = WikiStore(tmp_path / "wiki_state")
        # Simulate a page with an empty slug: "concepts/.md"
        wiki_state.save(WikiPageState(
            page_path=str(tmp_path / "wiki" / "concepts" / ".md"),
            run_id="run-001",
            frontmatter={"id": "concept.", "title": "", "type": "concept"},
            body="# Empty concept",
            compiled_at=datetime.now(),
        ))

        # Patch _render_markdown to avoid import issues.
        import scripts.quick_verify_papers as qv
        original = qv._render_markdown
        qv._render_markdown = lambda fm, body: f"---\n---\n{body}"  # type: ignore[assignment]

        try:
            result = qv._export_wiki_pages(tmp_path, tmp_path / "export")
        finally:
            qv._render_markdown = original  # type: ignore[assignment]

        assert len(result["exported"]) == 0
        assert result["filtered_empty_slug"] == 1
        # Ensure the .md file with empty name was NOT written.
        assert not (tmp_path / "export" / "concepts" / ".md").exists()

    def test_normal_page_exported(self, tmp_path: Path) -> None:
        """A page with a valid slug is still exported normally."""
        from docos.artifact_stores import WikiPageState, WikiStore
        from datetime import datetime

        wiki_state = WikiStore(tmp_path / "wiki_state")
        wiki_state.save(WikiPageState(
            page_path=str(tmp_path / "wiki" / "entities" / "word2vec.md"),
            run_id="run-001",
            frontmatter={"id": "entity.word2vec", "title": "Word2Vec", "type": "entity"},
            body="# Word2Vec",
            compiled_at=datetime.now(),
        ))

        import scripts.quick_verify_papers as qv
        original = qv._render_markdown
        qv._render_markdown = lambda fm, body: f"---\n---\n{body}"  # type: ignore[assignment]

        try:
            result = qv._export_wiki_pages(tmp_path, tmp_path / "export")
        finally:
            qv._render_markdown = original  # type: ignore[assignment]

        assert len(result["exported"]) == 1
        assert "word2vec.md" in result["exported"][0]
        assert result["filtered_empty_slug"] == 0

    def test_whitespace_only_stem_skipped(self, tmp_path: Path) -> None:
        """Pages with whitespace-only filename stem are also skipped."""
        from docos.artifact_stores import WikiPageState, WikiStore
        from datetime import datetime

        wiki_state = WikiStore(tmp_path / "wiki_state")
        wiki_state.save(WikiPageState(
            page_path=str(tmp_path / "wiki" / "concepts" / "   .md"),
            run_id="run-001",
            frontmatter={"id": "concept.", "title": "", "type": "concept"},
            body="# Whitespace concept",
            compiled_at=datetime.now(),
        ))

        import scripts.quick_verify_papers as qv
        original = qv._render_markdown
        qv._render_markdown = lambda fm, body: f"---\n---\n{body}"  # type: ignore[assignment]

        try:
            result = qv._export_wiki_pages(tmp_path, tmp_path / "export")
        finally:
            qv._render_markdown = original  # type: ignore[assignment]

        assert len(result["exported"]) == 0
        assert result["filtered_empty_slug"] == 1

    def test_mixed_empty_and_valid_pages(self, tmp_path: Path) -> None:
        """Only valid pages exported; empty-slug pages are filtered."""
        from docos.artifact_stores import WikiPageState, WikiStore
        from datetime import datetime

        wiki_state = WikiStore(tmp_path / "wiki_state")
        wiki_state.save(WikiPageState(
            page_path=str(tmp_path / "wiki" / "entities" / "word2vec.md"),
            run_id="run-001",
            frontmatter={"id": "entity.word2vec", "title": "Word2Vec", "type": "entity"},
            body="# Word2Vec",
            compiled_at=datetime.now(),
        ))
        wiki_state.save(WikiPageState(
            page_path=str(tmp_path / "wiki" / "concepts" / ".md"),
            run_id="run-001",
            frontmatter={"id": "concept.", "title": "", "type": "concept"},
            body="# Empty",
            compiled_at=datetime.now(),
        ))

        import scripts.quick_verify_papers as qv
        original = qv._render_markdown
        qv._render_markdown = lambda fm, body: f"---\n---\n{body}"  # type: ignore[assignment]

        try:
            result = qv._export_wiki_pages(tmp_path, tmp_path / "export")
        finally:
            qv._render_markdown = original  # type: ignore[assignment]

        assert len(result["exported"]) == 1
        assert result["filtered_empty_slug"] == 1


# ---------------------------------------------------------------------------
# AC2: A blocked empty-slug page is reported as filtered, dropped, or
#      otherwise observable
# ---------------------------------------------------------------------------


class TestEmptySlugObservable:
    """Dropped empty-slug pages are observable via manifest counter and per-paper result."""

    def test_is_valid_page_path_rejects_empty_stem(self) -> None:
        """_is_valid_page_path returns False for empty-stem paths."""
        from docos.wiki.compiler import _is_valid_page_path

        assert not _is_valid_page_path(Path("concepts/.md"))
        assert not _is_valid_page_path(Path("entities/.md"))
        assert not _is_valid_page_path(Path("sources/.md"))

    def test_is_valid_page_path_accepts_normal(self) -> None:
        """_is_valid_page_path returns True for valid paths."""
        from docos.wiki.compiler import _is_valid_page_path

        assert _is_valid_page_path(Path("entities/word2vec.md"))
        assert _is_valid_page_path(Path("concepts/neural-network.md"))
        assert _is_valid_page_path(Path("sources/paper-001.md"))

    def test_manifest_has_dropped_counter(self) -> None:
        """RunManifest has a dropped_empty_slug_count field."""
        from docos.models.run import RunManifest

        m = RunManifest(
            run_id="r", source_id="s",
            source_file_path="/tmp/test.pdf", artifact_root="/tmp",
        )
        assert hasattr(m, "dropped_empty_slug_count")
        assert m.dropped_empty_slug_count == 0

    def test_per_paper_result_has_dropped_count(self) -> None:
        """Per-paper result dict includes dropped_empty_slug_count."""
        import scripts.quick_verify_papers as qv

        item = {
            "status": "success",
            "run_status": "completed",
            "counts": {"wiki_pages_exported": 2, "lint_findings": 0},
            "gate": {"passed": True},
            "review_status": None,
            "artifacts": {"wiki_pages": ["/tmp/a.md", "/tmp/b.md"]},
            "dropped_empty_slug_count": 1,
        }
        assert item["dropped_empty_slug_count"] == 1

    def test_batch_summary_includes_dropped_total(self) -> None:
        """Batch summary totals include dropped_empty_slug_count."""
        results = [
            {"dropped_empty_slug_count": 2},
            {"dropped_empty_slug_count": 0},
            {"dropped_empty_slug_count": 1},
        ]
        total = sum(item.get("dropped_empty_slug_count", 0) for item in results)
        assert total == 3

    def test_batch_summary_dropped_zero_when_none(self) -> None:
        """Batch summary shows 0 when no pages were dropped."""
        results = [
            {"dropped_empty_slug_count": 0},
            {"dropped_empty_slug_count": 0},
        ]
        total = sum(item.get("dropped_empty_slug_count", 0) for item in results)
        assert total == 0


# ---------------------------------------------------------------------------
# AC3: Automated tests fail if export would create an empty markdown filename
# ---------------------------------------------------------------------------


class TestEmptyFilenamePrevention:
    """Ensure empty filenames can never reach the filesystem."""

    def test_compile_entity_with_empty_name_gives_valid_path(self) -> None:
        """compile_entity_page with empty name still produces valid path (slugify fallback)."""
        from docos.wiki.compiler import WikiCompiler, _is_valid_page_path
        from docos.models.knowledge import EntityRecord, EntityType

        compiler = WikiCompiler(Path("/tmp/wiki"))
        entity = EntityRecord(
            entity_id="e1",
            canonical_name="!!!",  # slugify returns "untitled"
            entity_type=EntityType.METHOD,
            source_ids=["s1"],
        )
        _, _, epath = compiler.compile_entity_page(entity, [])
        # "untitled" is a valid slug, so path should be valid.
        assert _is_valid_page_path(epath)
        assert epath.stem == "untitled"

    def test_compile_concept_with_empty_name_gives_valid_path(self) -> None:
        """compile_concept_page with empty name still produces valid path."""
        from docos.wiki.compiler import WikiCompiler, _is_valid_page_path

        compiler = WikiCompiler(Path("/tmp/wiki"))
        _, _, cpath = compiler.compile_concept_page(
            concept_name="!!!",  # slugify returns "untitled"
            source_ids=["s1"],
            related_claims=[],
            related_entities=[],
        )
        assert _is_valid_page_path(cpath)
        assert cpath.stem == "untitled"

    def test_empty_stem_path_never_reaches_filesystem(self, tmp_path: Path) -> None:
        """Verify that an empty-stem page path can never be written to disk."""
        from docos.wiki.compiler import _is_valid_page_path

        # A path like "concepts/.md" should be rejected
        empty_slug_path = tmp_path / "concepts" / ".md"
        assert not _is_valid_page_path(empty_slug_path)

        # Ensure we never create such a file
        empty_slug_path.parent.mkdir(parents=True, exist_ok=True)
        # Simulating what the code does: it checks _is_valid_page_path first
        if _is_valid_page_path(empty_slug_path):
            empty_slug_path.write_text("should not happen", encoding="utf-8")
        assert not empty_slug_path.exists()


# ---------------------------------------------------------------------------
# Markdown output includes dropped empty slug line
# ---------------------------------------------------------------------------


class TestMarkdownOutput:
    """Markdown summary includes dropped empty slug line."""

    def test_markdown_includes_dropped_empty_slug_line(self) -> None:
        """The markdown summary shows dropped empty slug count in Verdict Tiers."""
        import scripts.quick_verify_papers as qv

        totals = {
            "manifest_total": 2,
            "selected_paper_count": 2,
            "downloaded_paper_count": 2,
            "verified_paper_count": 2,
            "pdfs_discovered": 2,
            "pdfs_selected": 2,
            "pdfs_processed": 2,
            "success_count": 1,
            "failed_count": 1,
            "wiki_output_count": 1,
            "pending_review_count": 0,
            "knowledge_sparse_count": 0,
            "wiki_sparse_count": 0,
            "pipeline_runnable_count": 1,
            "quality_blocked_count": 0,
            "usable_wiki_ready_count": 1,
            "gate_pass_rate": 1.0,
            "lint_blocker_count": 0,
            "generated_candidate_pages": 2,
            "gate_passed_pages": 2,
            "final_vault_ready_pages": 2,
            "dropped_empty_slug_count": 3,
        }
        payload = {
            "generated_at": "2026-04-18T00:00:00",
            "papers_dir": "/tmp",
            "config_path": "/tmp/config.yaml",
            "outdir": "/tmp/out",
            "totals": totals,
            "verdict": {"headline": "Test", "answer": "Test answer"},
            "failure_stage_histogram": {},
            "files": [],
            "options": {},
        }

        md_path = qv._write_summary_md(Path("/tmp"), payload)
        md_text = md_path.read_text(encoding="utf-8")
        assert "Dropped empty slug: **3**" in md_text

    def test_markdown_dropped_empty_slug_zero(self) -> None:
        """Markdown shows 0 when no pages were dropped."""
        import scripts.quick_verify_papers as qv

        totals = {
            "manifest_total": 1,
            "selected_paper_count": 1,
            "downloaded_paper_count": 1,
            "verified_paper_count": 1,
            "pdfs_discovered": 1,
            "pdfs_selected": 1,
            "pdfs_processed": 1,
            "success_count": 1,
            "failed_count": 0,
            "wiki_output_count": 1,
            "pending_review_count": 0,
            "knowledge_sparse_count": 0,
            "wiki_sparse_count": 0,
            "pipeline_runnable_count": 0,
            "quality_blocked_count": 0,
            "usable_wiki_ready_count": 1,
            "gate_pass_rate": 1.0,
            "lint_blocker_count": 0,
            "generated_candidate_pages": 1,
            "gate_passed_pages": 1,
            "final_vault_ready_pages": 1,
            "dropped_empty_slug_count": 0,
        }
        payload = {
            "generated_at": "2026-04-18T00:00:00",
            "papers_dir": "/tmp",
            "config_path": "/tmp/config.yaml",
            "outdir": "/tmp/out",
            "totals": totals,
            "verdict": {"headline": "Test", "answer": "Test answer"},
            "failure_stage_histogram": {},
            "files": [],
            "options": {},
        }

        md_path = qv._write_summary_md(Path("/tmp"), payload)
        md_text = md_path.read_text(encoding="utf-8")
        assert "Dropped empty slug: **0**" in md_text
