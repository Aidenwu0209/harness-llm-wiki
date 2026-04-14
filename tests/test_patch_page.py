"""Tests for Patch and Page schemas."""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from docos.models.page import (
    ComparisonPageContent,
    ConceptPageContent,
    DecisionPageContent,
    EntityPageContent,
    FailurePageContent,
    Frontmatter,
    PAGE_CONTENT_MAP,
    PageStatus,
    PageType,
    ReviewStatus,
    SourcePageContent,
)
from docos.models.patch import (
    BlastRadius,
    Change,
    ChangeType,
    MergeStatus,
    Patch,
)


# ---------------------------------------------------------------------------
# Patch tests
# ---------------------------------------------------------------------------

class TestPatch:
    def test_minimal_patch(self) -> None:
        p = Patch(
            patch_id="patch_001",
            run_id="run_001",
            source_id="src_001",
        )
        assert p.merge_status == MergeStatus.PENDING
        assert p.review_required is False
        assert p.risk_score == 0.0

    def test_patch_with_changes(self) -> None:
        p = Patch(
            patch_id="patch_002",
            run_id="run_002",
            source_id="src_001",
            changes=[
                Change(type=ChangeType.CREATE_PAGE, target="wiki/sources/src_001.md"),
                Change(
                    type=ChangeType.UPDATE_PAGE,
                    target="wiki/concepts/reading-order.md",
                    summary="Add new evidence",
                ),
            ],
            blast_radius=BlastRadius(pages=2, claims=4, links=7),
            risk_score=0.31,
        )
        assert len(p.changes) == 2
        assert p.blast_radius.pages == 2

    def test_all_change_types(self) -> None:
        for ct in ChangeType:
            c = Change(type=ct, target="test_target")
            assert c.type == ct

    def test_all_merge_statuses(self) -> None:
        for ms in MergeStatus:
            p = Patch(patch_id="p", run_id="r", source_id="s", merge_status=ms)
            assert p.merge_status == ms

    def test_risk_score_range(self) -> None:
        with pytest.raises(ValidationError):
            Patch(patch_id="p", run_id="r", source_id="s", risk_score=1.5)

    def test_patch_from_requirements_example(self) -> None:
        """Replicate the example from requirements.md section 38.4."""
        p = Patch(
            patch_id="patch_20260413_001",
            run_id="run_20260413_001",
            source_id="src_0001",
            generated_at=datetime(2026, 4, 13, 10, 0, 0),
            changes=[
                Change(type=ChangeType.CREATE_PAGE, target="wiki/sources/src_0001.md"),
                Change(type=ChangeType.UPDATE_PAGE, target="wiki/concepts/reading-order.md"),
            ],
            blast_radius=BlastRadius(pages=2, claims=4, links=7),
            risk_score=0.31,
            review_required=False,
            merge_status=MergeStatus.PENDING,
        )
        assert p.patch_id == "patch_20260413_001"
        assert p.blast_radius.claims == 4


# ---------------------------------------------------------------------------
# Frontmatter tests
# ---------------------------------------------------------------------------

class TestFrontmatter:
    def test_minimal_frontmatter(self) -> None:
        fm = Frontmatter(
            id="concept.reading_order",
            type=PageType.CONCEPT,
            title="Reading Order",
            created_at=date(2026, 4, 13),
            updated_at=date(2026, 4, 13),
        )
        assert fm.status == PageStatus.DRAFT
        assert fm.review_status == ReviewStatus.PENDING
        assert fm.schema_version == "1"

    def test_full_frontmatter(self) -> None:
        fm = Frontmatter(
            id="concept.reading_order",
            type=PageType.CONCEPT,
            title="Reading Order",
            status=PageStatus.AUTO,
            schema_version="1",
            created_at=date(2026, 4, 13),
            updated_at=date(2026, 4, 13),
            source_docs=["src_0001"],
            related_entities=["parser.docir_router"],
            related_claims=["claim_001"],
            review_status=ReviewStatus.PENDING,
        )
        assert fm.source_docs == ["src_0001"]


# ---------------------------------------------------------------------------
# Page content tests
# ---------------------------------------------------------------------------

class TestPageContent:
    def test_source_page(self) -> None:
        c = SourcePageContent(
            file_name="readoc.pdf",
            mime_type="application/pdf",
            page_count=12,
            parser_route="complex_pdf_route",
            high_level_summary="A benchmark for document structure extraction.",
        )
        assert c.file_name == "readoc.pdf"

    def test_entity_page(self) -> None:
        c = EntityPageContent(
            canonical_name="READOC",
            aliases=["Readoc Benchmark"],
            entity_type="benchmark",
            defining_description="End-to-end document structure extraction benchmark",
        )
        assert c.canonical_name == "READOC"
        assert "Readoc Benchmark" in c.aliases

    def test_concept_page(self) -> None:
        c = ConceptPageContent(
            concept_definition="Reading order is the sequence in which blocks are meant to be read.",
        )
        assert c.concept_definition != ""

    def test_failure_page(self) -> None:
        c = FailurePageContent(
            failure_definition="Cross-page table splitting",
            trigger_patterns=["Table spans 2+ pages"],
            impacted_parsers=["parser_a"],
        )
        assert len(c.trigger_patterns) == 1

    def test_comparison_page(self) -> None:
        c = ComparisonPageContent(
            compared_objects=["parser_a", "parser_b"],
            comparison_dimensions=["fidelity", "cost", "speed"],
        )
        assert len(c.compared_objects) == 2

    def test_decision_page(self) -> None:
        c = DecisionPageContent(
            decision_statement="Use parser_a as primary for academic PDFs",
            rationale="Higher fidelity on two-column layouts",
        )
        assert c.decision_statement != ""

    def test_page_type_content_map(self) -> None:
        """All page types with a content model are in PAGE_CONTENT_MAP."""
        assert PageType.SOURCE in PAGE_CONTENT_MAP
        assert PageType.ENTITY in PAGE_CONTENT_MAP
        assert PageType.CONCEPT in PAGE_CONTENT_MAP
        assert PageType.FAILURE in PAGE_CONTENT_MAP
        assert PageType.COMPARISON in PAGE_CONTENT_MAP
        assert PageType.DECISION in PAGE_CONTENT_MAP

    def test_all_page_types(self) -> None:
        for pt in PageType:
            assert isinstance(pt.value, str)
