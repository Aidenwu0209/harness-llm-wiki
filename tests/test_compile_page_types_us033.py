"""Tests for US-033: Add compile coverage for parser and benchmark page types."""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.models.page import (
    BenchmarkPageContent,
    ParserPageContent,
)
from docos.wiki.compiler import WikiCompiler


class TestCompileParserPage:
    """Test compile_parser_page compilation path."""

    def test_compile_parser_page_produces_frontmatter(self, tmp_path: Path) -> None:
        """Parser page compile produces valid frontmatter."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = ParserPageContent(
            parser_name="stdlib_pdf",
            parser_version="1.0.0",
            capabilities=["text_extraction", "reading_order"],
            supported_file_types=["application/pdf"],
            route_assignments=["fast_text_route"],
            known_strengths=["Fast for text-heavy PDFs"],
            known_limitations=["No OCR support", "Basic layout analysis"],
            fallback_parsers=["basic_text_fallback"],
            quality_metrics={"confidence": 0.8},
        )

        fm, body, page_path = compiler.compile_parser_page(
            parser_name="stdlib_pdf",
            content=content,
        )

        assert fm.type.value == "parser"
        assert "stdlib" in fm.id
        assert fm.title == "Parser: stdlib_pdf"

    def test_compile_parser_page_produces_body(self, tmp_path: Path) -> None:
        """Parser page body includes version, capabilities, limitations."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = ParserPageContent(
            parser_name="stdlib_pdf",
            parser_version="1.0.0",
            capabilities=["text_extraction", "reading_order"],
            known_limitations=["No OCR support"],
            fallback_parsers=["basic_text_fallback"],
        )

        fm, body, page_path = compiler.compile_parser_page(
            parser_name="stdlib_pdf",
            content=content,
        )

        assert "1.0.0" in body
        assert "text_extraction" in body
        assert "No OCR support" in body
        assert "basic_text_fallback" in body

    def test_compile_parser_page_path(self, tmp_path: Path) -> None:
        """Parser page is placed in the parsers directory."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = ParserPageContent(parser_name="stdlib_pdf", parser_version="1.0.0")

        fm, body, page_path = compiler.compile_parser_page(
            parser_name="stdlib_pdf",
            content=content,
        )

        assert "parsers" in str(page_path)
        assert "stdlib-pdf" in str(page_path)

    def test_compile_parser_page_with_full_content(self, tmp_path: Path) -> None:
        """Parser page with all content fields produces complete output."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = ParserPageContent(
            parser_name="basic_text_fallback",
            parser_version="1.0.0",
            capabilities=["text_extraction"],
            supported_file_types=["application/pdf"],
            route_assignments=["fallback_safe_route"],
            known_strengths=["Robust", "Always produces output"],
            known_limitations=["No layout analysis"],
            fallback_parsers=[],
            quality_metrics={"confidence": 0.5},
        )

        fm, body, page_path = compiler.compile_parser_page(
            parser_name="basic_text_fallback",
            content=content,
        )

        rendered = compiler.render_page(fm, body)
        assert "basic_text_fallback" in rendered
        assert "Capabilities" in rendered
        assert "Known Limitations" in rendered
        assert "text_extraction" in rendered


class TestCompileBenchmarkPage:
    """Test compile_benchmark_page compilation path."""

    def test_compile_benchmark_page_produces_frontmatter(self, tmp_path: Path) -> None:
        """Benchmark page compile produces valid frontmatter."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = BenchmarkPageContent(
            benchmark_name="PDF Text Extraction v1",
            dataset_description="100-page PDF corpus with mixed layouts",
            evaluation_dimensions=["precision", "recall", "f1_score"],
            ground_truth_source="Manual annotation by domain experts",
            parser_results=["stdlib_pdf: F1=0.85", "basic_text_fallback: F1=0.65"],
            comparison_charts=["F1 by parser"],
            open_issues=["OCR-heavy documents not covered"],
        )

        fm, body, page_path = compiler.compile_benchmark_page(
            benchmark_name="PDF Text Extraction v1",
            content=content,
        )

        assert fm.type.value == "benchmark"
        assert "pdf-text-extraction-v1" in fm.id.lower() or "benchmark" in fm.id

    def test_compile_benchmark_page_produces_body(self, tmp_path: Path) -> None:
        """Benchmark page body includes dataset, dimensions, and results."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = BenchmarkPageContent(
            benchmark_name="PDF Parse Quality",
            dataset_description="Test corpus of 50 PDFs",
            evaluation_dimensions=["precision", "recall"],
            parser_results=["stdlib_pdf: precision=0.90", "stdlib_pdf: recall=0.85"],
        )

        fm, body, page_path = compiler.compile_benchmark_page(
            benchmark_name="PDF Parse Quality",
            content=content,
        )

        assert "Test corpus of 50 PDFs" in body
        assert "precision" in body
        assert "stdlib_pdf: precision=0.90" in body

    def test_compile_benchmark_page_path(self, tmp_path: Path) -> None:
        """Benchmark page is placed in the benchmarks directory."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = BenchmarkPageContent(
            benchmark_name="OCR Accuracy",
            dataset_description="Scanned document test set",
        )

        fm, body, page_path = compiler.compile_benchmark_page(
            benchmark_name="OCR Accuracy",
            content=content,
        )

        assert "benchmarks" in str(page_path)

    def test_compile_benchmark_page_with_full_content(self, tmp_path: Path) -> None:
        """Benchmark page with all content fields produces complete output."""
        compiler = WikiCompiler(tmp_path / "wiki")
        content = BenchmarkPageContent(
            benchmark_name="Full Pipeline Benchmark",
            dataset_description="Comprehensive test set",
            evaluation_dimensions=["accuracy", "coverage", "latency"],
            ground_truth_source="Expert annotations",
            parser_results=["stdlib_pdf: accuracy=0.88", "basic_text_fallback: accuracy=0.70"],
            comparison_charts=["Accuracy comparison chart"],
            open_issues=["Formula-heavy pages not covered"],
        )

        fm, body, page_path = compiler.compile_benchmark_page(
            benchmark_name="Full Pipeline Benchmark",
            content=content,
        )

        rendered = compiler.render_page(fm, body)
        assert "Benchmark: Full Pipeline Benchmark" in rendered
        assert "Evaluation Dimensions" in rendered
        assert "Parser Results" in rendered


class TestExistingPageTypesStillCompile:
    """Existing page types continue to compile successfully."""

    def test_source_page_compiles(self, tmp_path: Path) -> None:
        """Source page type still compiles."""
        from docos.models.docir import DocIR, Page
        from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord, EntityType, EvidenceAnchor
        from docos.models.source import SourceRecord

        compiler = WikiCompiler(tmp_path / "wiki")

        source = SourceRecord(
            source_id="src_test",
            source_hash="abc123",
            file_name="test.pdf",
            mime_type="application/pdf",
            byte_size=1000,
        )
        docir = DocIR(
            doc_id="doc_test",
            source_id="src_test",
            parser="stdlib_pdf",
            page_count=1,
            pages=[Page(page_no=1, width=612.0, height=792.0)],
        )

        entities = [EntityRecord(
            entity_id="ent_test",
            canonical_name="Test",
            entity_type=EntityType.DOCUMENT,
            source_ids=["src_test"],
        )]
        claims = [ClaimRecord(
            claim_id="clm_test",
            statement="Test claim",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[EvidenceAnchor(
                anchor_id="anc_test",
                source_id="src_test",
                doc_id="doc_test",
                page_no=1,
                block_id="blk_test",
            )],
        )]

        fm, body, page_path = compiler.compile_source_page(source, docir, entities, claims)
        assert fm.type.value == "source"
        assert body  # non-empty

    def test_entity_page_compiles(self, tmp_path: Path) -> None:
        """Entity page type still compiles."""
        from docos.models.knowledge import EntityRecord, EntityType

        compiler = WikiCompiler(tmp_path / "wiki")
        entity = EntityRecord(
            entity_id="ent_test",
            canonical_name="Machine Learning",
            entity_type=EntityType.CONCEPT,
            aliases=["ML"],
            defining_description="A subfield of AI",
        )

        fm, body, page_path = compiler.compile_entity_page(entity, claims=[])
        assert fm.type.value == "entity"
        assert "Machine Learning" in body

    def test_concept_page_compiles(self, tmp_path: Path) -> None:
        """Concept page type still compiles."""
        compiler = WikiCompiler(tmp_path / "wiki")
        fm, body, page_path = compiler.compile_concept_page(
            concept_name="Neural Networks",
            source_ids=["src_test"],
            related_claims=[],
            related_entities=[],
        )
        assert fm.type.value == "concept"

    def test_failure_page_compiles(self, tmp_path: Path) -> None:
        """Failure page type still compiles."""
        compiler = WikiCompiler(tmp_path / "wiki")
        fm, body, page_path = compiler.compile_failure_page(
            failure_name="Cross-page table split",
            trigger_patterns=["Table spans more than one page"],
            impacted_parsers=["stdlib_pdf"],
        )
        assert fm.type.value == "failure"

    def test_comparison_page_compiles(self, tmp_path: Path) -> None:
        """Comparison page type still compiles."""
        compiler = WikiCompiler(tmp_path / "wiki")
        fm, body, page_path = compiler.compile_comparison_page(
            title="Parser Comparison",
            objects=["stdlib_pdf", "basic_text_fallback"],
            dimensions=["accuracy", "speed"],
            differences=["stdlib_pdf has layout analysis"],
        )
        assert fm.type.value == "comparison"

    def test_decision_page_compiles(self, tmp_path: Path) -> None:
        """Decision page type still compiles."""
        compiler = WikiCompiler(tmp_path / "wiki")
        fm, body, page_path = compiler.compile_decision_page(
            statement="Use stdlib_pdf as primary parser",
            context="Need a dependency-free parser",
            rationale="Standard library only, no external deps",
            alternatives=["Use pymupdf"],
        )
        assert fm.type.value == "decision"
