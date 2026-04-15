"""Tests for US-032: Extend compile to remaining operational page types."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import WikiStore, WikiPageState
from docos.models.page import BenchmarkPageContent, ParserPageContent
from docos.models.patch_set import PatchSet
from docos.run_store import RunStore
from docos.wiki.compiler import CompiledPage, WikiCompiler


class TestCompileParserPage:
    """US-032: Parser page compilation."""

    def test_parser_page_produces_deterministic_path(self, tmp_path: Path) -> None:
        """Parser page path is deterministic from parser name."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = ParserPageContent(
            parser_name="stdlib_pdf",
            parser_version="1.0",
            capabilities=["pdf", "text"],
            supported_file_types=["application/pdf"],
        )
        fm, body, path = compiler.compile_parser_page("stdlib_pdf", content)

        assert "parser" in str(path)
        assert "stdlib" in str(path)  # slug: stdlib-pdf
        assert fm.type.value == "parser"
        assert fm.id == "parser-stdlib-pdf"

    def test_parser_page_patch_generation(self, tmp_path: Path) -> None:
        """Parser page generates a valid patch."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = ParserPageContent(
            parser_name="basic_text_fallback",
            parser_version="2.0",
            capabilities=["text recovery"],
        )
        fm, body, path = compiler.compile_parser_page("basic_text_fallback", content)

        compiled = CompiledPage(frontmatter=fm, body=body, page_path=path, run_id="run-parser")
        patch = compiled.compute_patch(run_id="run-parser", source_id="src-parser")

        assert patch is not None
        assert len(patch.changes) > 0

    def test_parser_page_frontmatter_validation(self, tmp_path: Path) -> None:
        """Parser page has required frontmatter fields."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = ParserPageContent(parser_name="test_parser")
        fm, _, _ = compiler.compile_parser_page("test_parser", content)

        assert fm.id is not None
        assert fm.type.value == "parser"
        assert fm.title is not None
        assert fm.updated_at is not None


class TestCompileBenchmarkPage:
    """US-032: Benchmark page compilation."""

    def test_benchmark_page_produces_deterministic_path(self, tmp_path: Path) -> None:
        """Benchmark page path is deterministic from benchmark name."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = BenchmarkPageContent(
            benchmark_name="pdf_quality_v1",
            dataset_description="PDF parsing quality benchmark",
            evaluation_dimensions=["accuracy", "speed"],
        )
        fm, body, path = compiler.compile_benchmark_page("pdf_quality_v1", content)

        assert "benchmark" in str(path)
        assert "pdf-quality" in str(path)  # slug: pdf-quality-v1
        assert fm.type.value == "benchmark"
        assert fm.id == "benchmark-pdf-quality-v1"

    def test_benchmark_page_patch_generation(self, tmp_path: Path) -> None:
        """Benchmark page generates a valid patch."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = BenchmarkPageContent(
            benchmark_name="test_bench",
            dataset_description="Test benchmark",
        )
        fm, body, path = compiler.compile_benchmark_page("test_bench", content)

        compiled = CompiledPage(frontmatter=fm, body=body, page_path=path, run_id="run-bench")
        patch = compiled.compute_patch(run_id="run-bench", source_id="src-bench")

        assert patch is not None
        assert len(patch.changes) > 0

    def test_benchmark_page_frontmatter_validation(self, tmp_path: Path) -> None:
        """Benchmark page has required frontmatter fields."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = BenchmarkPageContent(benchmark_name="bench_test")
        fm, _, _ = compiler.compile_benchmark_page("bench_test", content)

        assert fm.id is not None
        assert fm.type.value == "benchmark"
        assert fm.title is not None
        assert fm.updated_at is not None

    def test_parser_and_benchmark_in_patch_set(self, tmp_path: Path) -> None:
        """Parser and benchmark pages can be part of a PatchSet."""
        compiler = WikiCompiler(tmp_path / "wiki")

        # Parser page
        p_content = ParserPageContent(parser_name="p1", parser_version="1.0")
        pfm, pbody, ppath = compiler.compile_parser_page("p1", p_content)
        p_compiled = CompiledPage(frontmatter=pfm, body=pbody, page_path=ppath, run_id="run-ops")
        p_patch = p_compiled.compute_patch(run_id="run-ops", source_id="src-ops")

        # Benchmark page
        b_content = BenchmarkPageContent(benchmark_name="b1", dataset_description="test")
        bfm, bbody, bpath = compiler.compile_benchmark_page("b1", b_content)
        b_compiled = CompiledPage(frontmatter=bfm, body=bbody, page_path=bpath, run_id="run-ops")
        b_patch = b_compiled.compute_patch(run_id="run-ops", source_id="src-ops")

        patches = [p for p in [p_patch, b_patch] if p is not None]
        ps = PatchSet.from_patches("run-ops", "src-ops", patches)

        assert ps.summary.total_patches == 2
        assert ps.summary.create_page_count == 2
