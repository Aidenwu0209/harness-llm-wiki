"""Tests for parser and benchmark page compile coverage (US-033)."""

from datetime import date
from pathlib import Path

import pytest

from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    EvidenceAnchor,
)
from docos.models.page import (
    BenchmarkPageContent,
    Frontmatter,
    PageType,
    ParserPageContent,
    ReviewStatus,
)
from docos.wiki.compiler import WikiCompiler


@pytest.fixture
def compiler(tmp_path: Path) -> WikiCompiler:
    return WikiCompiler(tmp_path / "wiki")


# ---------------------------------------------------------------------------
# ParserPageContent model instantiation
# ---------------------------------------------------------------------------

class TestParserPageContentModel:
    def test_instantiate_with_defaults(self) -> None:
        content = ParserPageContent()
        assert content.parser_name == ""
        assert content.parser_version == ""
        assert content.capabilities == []
        assert content.supported_file_types == []
        assert content.route_assignments == []
        assert content.known_strengths == []
        assert content.known_limitations == []
        assert content.fallback_parsers == []
        assert content.quality_metrics == {}

    def test_instantiate_with_all_fields(self) -> None:
        content = ParserPageContent(
            parser_name="marker",
            parser_version="1.5.0",
            capabilities=["table extraction", "heading detection"],
            supported_file_types=["application/pdf"],
            route_assignments=["default_pdf"],
            known_strengths=["high fidelity on two-column layouts"],
            known_limitations=["slow on large files"],
            fallback_parsers=["pymupdf", "stdlib_pdf"],
            quality_metrics={"accuracy": 0.95, "speed": 0.7},
        )
        assert content.parser_name == "marker"
        assert content.parser_version == "1.5.0"
        assert len(content.capabilities) == 2
        assert len(content.fallback_parsers) == 2
        assert content.quality_metrics["accuracy"] == 0.95


# ---------------------------------------------------------------------------
# BenchmarkPageContent model instantiation
# ---------------------------------------------------------------------------

class TestBenchmarkPageContentModel:
    def test_instantiate_with_defaults(self) -> None:
        content = BenchmarkPageContent()
        assert content.benchmark_name == ""
        assert content.dataset_description == ""
        assert content.evaluation_dimensions == []
        assert content.ground_truth_source == ""
        assert content.parser_results == []
        assert content.comparison_charts == []
        assert content.open_issues == []

    def test_instantiate_with_all_fields(self) -> None:
        content = BenchmarkPageContent(
            benchmark_name="READOC v2",
            dataset_description="100-page benchmark with mixed layouts",
            evaluation_dimensions=["fidelity", "speed", "cost"],
            ground_truth_source="Manual annotation by domain experts",
            parser_results=["marker: 95%", "pymupdf: 88%"],
            comparison_charts=["accuracy_bar_chart.png"],
            open_issues=["OCR pathway not tested"],
        )
        assert content.benchmark_name == "READOC v2"
        assert len(content.evaluation_dimensions) == 3
        assert len(content.parser_results) == 2


# ---------------------------------------------------------------------------
# compile_parser_page()
# ---------------------------------------------------------------------------

class TestCompileParserPage:
    def test_returns_tuple(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(
            parser_name="marker",
            parser_version="1.5.0",
        )
        result = compiler.compile_parser_page("marker", content)
        assert isinstance(result, tuple)
        assert len(result) == 3
        fm, body, path = result
        assert isinstance(fm, Frontmatter)
        assert isinstance(body, str)
        assert isinstance(path, Path)

    def test_frontmatter_type_is_parser(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(parser_version="2.0")
        fm, _, _ = compiler.compile_parser_page("marker", content)
        assert fm.type == PageType.PARSER

    def test_frontmatter_id_and_title(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(parser_version="1.0")
        fm, _, _ = compiler.compile_parser_page("marker", content)
        assert fm.id.startswith("parser-")
        assert "marker" in fm.title
        assert fm.review_status == ReviewStatus.NOT_NEEDED

    def test_body_contains_version(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(parser_version="1.5.0")
        _, body, _ = compiler.compile_parser_page("marker", content)
        assert "1.5.0" in body

    def test_body_contains_capabilities(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(
            parser_version="1.0",
            capabilities=["table extraction", "heading detection"],
        )
        _, body, _ = compiler.compile_parser_page("marker", content)
        assert "## Capabilities" in body
        assert "table extraction" in body
        assert "heading detection" in body

    def test_body_contains_known_limitations(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(
            parser_version="1.0",
            known_limitations=["slow on large files", "no OCR support"],
        )
        _, body, _ = compiler.compile_parser_page("marker", content)
        assert "## Known Limitations" in body
        assert "slow on large files" in body

    def test_body_contains_fallback_parsers(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(
            parser_version="1.0",
            fallback_parsers=["pymupdf", "stdlib_pdf"],
        )
        _, body, _ = compiler.compile_parser_page("marker", content)
        assert "## Fallback Parsers" in body
        assert "pymupdf" in body
        assert "stdlib_pdf" in body

    def test_page_path_under_parsers_dir(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(parser_version="1.0")
        _, _, path = compiler.compile_parser_page("marker", content)
        assert "parsers" in str(path)
        assert str(path).endswith(".md")

    def test_with_source_ids(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(parser_version="1.0")
        fm, _, _ = compiler.compile_parser_page(
            "marker", content, source_ids=["src_001", "src_002"]
        )
        assert fm.source_docs == ["src_001", "src_002"]

    def test_minimal_content_no_optional_sections(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(parser_version="1.0")
        _, body, _ = compiler.compile_parser_page("basic_text", content)
        assert "## Capabilities" not in body
        assert "## Known Limitations" not in body
        assert "## Fallback Parsers" not in body


# ---------------------------------------------------------------------------
# compile_benchmark_page()
# ---------------------------------------------------------------------------

class TestCompileBenchmarkPage:
    def test_returns_tuple(self, compiler: WikiCompiler) -> None:
        content = BenchmarkPageContent(
            dataset_description="Test dataset",
        )
        result = compiler.compile_benchmark_page("perf-test", content)
        assert isinstance(result, tuple)
        assert len(result) == 3
        fm, body, path = result
        assert isinstance(fm, Frontmatter)
        assert isinstance(body, str)
        assert isinstance(path, Path)

    def test_frontmatter_type_is_benchmark(self, compiler: WikiCompiler) -> None:
        content = BenchmarkPageContent(dataset_description="Test")
        fm, _, _ = compiler.compile_benchmark_page("perf-test", content)
        assert fm.type == PageType.BENCHMARK

    def test_frontmatter_id_and_title(self, compiler: WikiCompiler) -> None:
        content = BenchmarkPageContent(dataset_description="Test")
        fm, _, _ = compiler.compile_benchmark_page("perf-test", content)
        assert fm.id.startswith("benchmark-")
        assert "perf-test" in fm.title
        assert fm.review_status == ReviewStatus.NOT_NEEDED

    def test_body_contains_dataset_description(self, compiler: WikiCompiler) -> None:
        content = BenchmarkPageContent(
            dataset_description="100-page benchmark with mixed layouts",
        )
        _, body, _ = compiler.compile_benchmark_page("perf-test", content)
        assert "100-page benchmark with mixed layouts" in body

    def test_body_contains_evaluation_dimensions(self, compiler: WikiCompiler) -> None:
        content = BenchmarkPageContent(
            dataset_description="Test",
            evaluation_dimensions=["fidelity", "speed", "cost"],
        )
        _, body, _ = compiler.compile_benchmark_page("perf-test", content)
        assert "## Evaluation Dimensions" in body
        assert "fidelity" in body
        assert "speed" in body

    def test_body_contains_parser_results(self, compiler: WikiCompiler) -> None:
        content = BenchmarkPageContent(
            dataset_description="Test",
            parser_results=["marker: 95%", "pymupdf: 88%", "stdlib_pdf: 72%"],
        )
        _, body, _ = compiler.compile_benchmark_page("perf-test", content)
        assert "## Parser Results" in body
        assert "marker: 95%" in body
        assert "pymupdf: 88%" in body

    def test_page_path_under_benchmarks_dir(self, compiler: WikiCompiler) -> None:
        content = BenchmarkPageContent(dataset_description="Test")
        _, _, path = compiler.compile_benchmark_page("perf-test", content)
        assert "benchmarks" in str(path)
        assert str(path).endswith(".md")

    def test_with_source_ids(self, compiler: WikiCompiler) -> None:
        content = BenchmarkPageContent(dataset_description="Test")
        fm, _, _ = compiler.compile_benchmark_page(
            "perf-test", content, source_ids=["src_001"]
        )
        assert fm.source_docs == ["src_001"]

    def test_minimal_content_no_optional_sections(self, compiler: WikiCompiler) -> None:
        content = BenchmarkPageContent(dataset_description="Minimal")
        _, body, _ = compiler.compile_benchmark_page("minimal", content)
        assert "## Evaluation Dimensions" not in body
        assert "## Parser Results" not in body


# ---------------------------------------------------------------------------
# Existing page types still compile (regression guard)
# ---------------------------------------------------------------------------

class TestExistingPageTypesStillCompile:
    """Verify that source, entity, and concept pages continue to compile."""

    def test_source_page_still_compiles(self, compiler: WikiCompiler) -> None:
        from docos.models.docir import Block, BlockType, DocIR, Page
        from docos.models.source import SourceRecord

        source = SourceRecord(
            source_id="src_reg", source_hash="h1",
            file_name="reg.pdf", mime_type="application/pdf", byte_size=500,
        )
        blocks = [
            Block(
                block_id="h1", page_no=1, block_type=BlockType.HEADING,
                reading_order=0, bbox=(0, 0, 500, 50),
                text_plain="Regression Heading", text_md="## Regression Heading",
                source_parser="test", source_node_id="n1",
            ),
        ]
        page = Page(page_no=1, width=612, height=792, blocks=["h1"])
        docir = DocIR(
            doc_id="doc_reg", source_id="src_reg", parser="test",
            page_count=1, pages=[page], blocks=blocks,
        )
        fm, body, path = compiler.compile_source_page(source, docir, [], [])
        assert fm.type == PageType.SOURCE
        assert "reg.pdf" in body

    def test_entity_page_still_compiles(self, compiler: WikiCompiler) -> None:
        entity = EntityRecord(
            entity_id="ent_reg", canonical_name="Regression Entity",
            entity_type=EntityType.CONCEPT, source_ids=["src_reg"],
        )
        fm, body, path = compiler.compile_entity_page(entity, [])
        assert fm.type == PageType.ENTITY
        assert "Regression Entity" in body

    def test_concept_page_still_compiles(self, compiler: WikiCompiler) -> None:
        fm, body, path = compiler.compile_concept_page(
            concept_name="Regression Concept",
            source_ids=["src_reg"],
            related_claims=[],
            related_entities=[],
        )
        assert fm.type == PageType.CONCEPT
        assert "Regression Concept" in body


# ---------------------------------------------------------------------------
# Page render with parser and benchmark types
# ---------------------------------------------------------------------------

class TestPageRenderParserBenchmark:
    def test_render_parser_page(self, compiler: WikiCompiler) -> None:
        content = ParserPageContent(
            parser_version="1.0",
            capabilities=["table extraction"],
        )
        fm, body, _ = compiler.compile_parser_page("marker", content)
        rendered = WikiCompiler.render_page(fm, body)
        assert rendered.startswith("---")
        assert "type: parser" in rendered
        assert "# Parser: marker" in rendered

    def test_render_benchmark_page(self, compiler: WikiCompiler) -> None:
        content = BenchmarkPageContent(
            dataset_description="Test dataset for render",
            parser_results=["marker: 95%"],
        )
        fm, body, _ = compiler.compile_benchmark_page("perf-test", content)
        rendered = WikiCompiler.render_page(fm, body)
        assert rendered.startswith("---")
        assert "type: benchmark" in rendered
        assert "# Benchmark: perf-test" in rendered
