"""Tests for Wiki Compilation (US-017, US-018, US-019, US-020)."""

from datetime import date
from pathlib import Path

import pytest

from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    EvidenceAnchor,
)
from docos.models.page import PageType, ReviewStatus
from docos.models.source import SourceRecord
from docos.wiki.compiler import WikiCompiler


@pytest.fixture
def compiler(tmp_path: Path) -> WikiCompiler:
    return WikiCompiler(tmp_path / "wiki")


@pytest.fixture
def sample_docir() -> DocIR:
    blocks = [
        Block(block_id="title", page_no=1, block_type=BlockType.TITLE,
              reading_order=0, bbox=(0, 0, 500, 50),
              text_plain="Test Document", source_parser="test", source_node_id="n0"),
        Block(block_id="h1", page_no=1, block_type=BlockType.HEADING,
              reading_order=1, bbox=(0, 60, 500, 90),
              text_plain="Introduction", text_md="## Introduction",
              source_parser="test", source_node_id="n1"),
        Block(block_id="p1", page_no=1, block_type=BlockType.PARAGRAPH,
              reading_order=2, bbox=(0, 100, 500, 300),
              text_plain="Some introductory text about the topic.",
              source_parser="test", source_node_id="n2"),
    ]
    page = Page(page_no=1, width=612, height=792, blocks=["title", "h1", "p1"])
    return DocIR(doc_id="doc_test", source_id="src_test", parser="test",
                 page_count=1, pages=[page], blocks=blocks)


@pytest.fixture
def sample_entities() -> list[EntityRecord]:
    return [
        EntityRecord(entity_id="ent_1", canonical_name="Test Document",
                     entity_type=EntityType.DOCUMENT, source_ids=["src_test"]),
        EntityRecord(entity_id="ent_2", canonical_name="Introduction",
                     entity_type=EntityType.CONCEPT, source_ids=["src_test"]),
    ]


@pytest.fixture
def sample_claims() -> list[ClaimRecord]:
    return [
        ClaimRecord(
            claim_id="cl_1",
            statement="Introduction discusses the topic.",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[
                EvidenceAnchor(anchor_id="a1", source_id="src_test",
                               doc_id="doc_test", page_no=1, block_id="p1")
            ],
            supporting_sources=["src_test"],
        ),
    ]


@pytest.fixture
def sample_source() -> SourceRecord:
    return SourceRecord(
        source_id="src_test", source_hash="abc",
        file_name="test.pdf", mime_type="application/pdf", byte_size=1000,
    )


# ---------------------------------------------------------------------------
# US-017: Source page
# ---------------------------------------------------------------------------

class TestSourcePage:
    def test_compile_source_page(self, compiler: WikiCompiler, sample_source, sample_docir,
                                 sample_entities, sample_claims) -> None:
        fm, body, path = compiler.compile_source_page(
            sample_source, sample_docir, sample_entities, sample_claims
        )
        assert fm.type == PageType.SOURCE
        assert "test.pdf" in body
        assert "src_test" in body
        assert "Introduction" in body

    def test_source_page_frontmatter(self, compiler: WikiCompiler, sample_source,
                                      sample_docir, sample_entities, sample_claims) -> None:
        fm, _, _ = compiler.compile_source_page(
            sample_source, sample_docir, sample_entities, sample_claims
        )
        assert fm.source_docs == ["src_test"]
        assert len(fm.related_entities) >= 1
        assert len(fm.related_claims) >= 1
        assert fm.review_status == ReviewStatus.PENDING

    def test_source_page_has_section_outline(self, compiler: WikiCompiler, sample_source,
                                              sample_docir, sample_entities, sample_claims) -> None:
        _, body, _ = compiler.compile_source_page(
            sample_source, sample_docir, sample_entities, sample_claims
        )
        assert "Section Outline" in body
        assert "Introduction" in body

    def test_source_page_render(self, compiler: WikiCompiler, sample_source,
                                 sample_docir, sample_entities, sample_claims) -> None:
        fm, body, _ = compiler.compile_source_page(
            sample_source, sample_docir, sample_entities, sample_claims
        )
        rendered = WikiCompiler.render_page(fm, body)
        assert rendered.startswith("---")
        assert "type: source" in rendered
        assert "test.pdf" in rendered


# ---------------------------------------------------------------------------
# US-018: Entity page
# ---------------------------------------------------------------------------

class TestEntityPage:
    def test_compile_entity_page(self, compiler: WikiCompiler, sample_entities, sample_claims) -> None:
        entity = sample_entities[0]
        fm, body, path = compiler.compile_entity_page(entity, sample_claims)
        assert fm.type == PageType.ENTITY
        assert entity.canonical_name in body
        assert "Related Claims" in body

    def test_entity_page_aliases(self, compiler: WikiCompiler) -> None:
        entity = EntityRecord(
            entity_id="e1", canonical_name="READOC",
            entity_type=EntityType.BENCHMARK,
            aliases=["Readoc Benchmark", "READOC Dataset"],
            source_ids=["src_001"],
        )
        fm, body, _ = compiler.compile_entity_page(entity, [])
        assert "Readoc Benchmark" in body
        assert "READOC Dataset" in body

    def test_entity_page_candidate_duplicates(self, compiler: WikiCompiler) -> None:
        entity = EntityRecord(
            entity_id="e1", canonical_name="Test",
            entity_type=EntityType.CONCEPT,
            candidate_duplicates=["e2", "e3"],
        )
        _, body, _ = compiler.compile_entity_page(entity, [])
        assert "Candidate Duplicates" in body


# ---------------------------------------------------------------------------
# US-019: Concept page
# ---------------------------------------------------------------------------

class TestConceptPage:
    def test_compile_concept_page(self, compiler: WikiCompiler, sample_claims, sample_entities) -> None:
        fm, body, path = compiler.compile_concept_page(
            concept_name="Reading Order",
            source_ids=["src_test"],
            related_claims=sample_claims,
            related_entities=sample_entities,
        )
        assert fm.type == PageType.CONCEPT
        assert "Reading Order" in body
        assert "Evidence-Backed Claims" in body

    def test_concept_page_with_empty_data(self, compiler: WikiCompiler) -> None:
        fm, body, _ = compiler.compile_concept_page(
            concept_name="Empty Concept", source_ids=[], related_claims=[], related_entities=[]
        )
        assert fm.type == PageType.CONCEPT
        assert "Empty Concept" in body


# ---------------------------------------------------------------------------
# US-020: Failure / Comparison / Decision pages
# ---------------------------------------------------------------------------

class TestFailurePage:
    def test_compile_failure_page(self, compiler: WikiCompiler) -> None:
        fm, body, path = compiler.compile_failure_page(
            failure_name="Cross-Page Table Split",
            trigger_patterns=["Table spans 2+ pages", "No explicit end marker"],
            impacted_parsers=["marker", "pymupdf"],
            description="Tables break across pages without continuity relations",
        )
        assert fm.type == PageType.FAILURE
        assert "Cross-Page Table Split" in body
        assert "marker" in body

    def test_failure_page_path(self, compiler: WikiCompiler) -> None:
        _, _, path = compiler.compile_failure_page("Test Failure", ["t1"], ["p1"])
        assert "failures" in str(path)


class TestComparisonPage:
    def test_compile_comparison_page(self, compiler: WikiCompiler) -> None:
        fm, body, path = compiler.compile_comparison_page(
            title="Marker vs PyMuPDF",
            objects=["marker", "pymupdf"],
            dimensions=["fidelity", "speed", "cost"],
            differences=["marker is slower but more accurate", "pymupdf is faster"],
        )
        assert fm.type == PageType.COMPARISON
        assert "marker" in body
        assert "pymupdf" in body


class TestDecisionPage:
    def test_compile_decision_page(self, compiler: WikiCompiler) -> None:
        fm, body, path = compiler.compile_decision_page(
            statement="Use marker as primary parser",
            context="Complex PDFs need high fidelity",
            rationale="marker achieves 95% accuracy on two-column layouts",
            alternatives=["Use pymupdf only", "Use both and compare"],
        )
        assert fm.type == PageType.DECISION
        assert "Alternatives Considered" in body
        assert "pymupdf" in body


class TestPageRender:
    def test_render_page_format(self, compiler: WikiCompiler) -> None:
        from docos.models.page import Frontmatter
        fm = Frontmatter(
            id="test.page", type=PageType.SOURCE, title="Test",
            created_at=date(2026, 4, 14), updated_at=date(2026, 4, 14),
        )
        rendered = WikiCompiler.render_page(fm, "# Test\n\nBody text.")
        assert rendered.startswith("---")
        assert "type: source" in rendered
        assert "---" in rendered  # closing frontmatter delimiter
        assert "# Test" in rendered
