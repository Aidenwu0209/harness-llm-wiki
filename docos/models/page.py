"""Page schema — template contracts for wiki pages.

Every wiki page in the system follows a typed template with mandatory
frontmatter fields. This module defines the page types and their
structural contracts.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Page types
# ---------------------------------------------------------------------------

class PageType(str, Enum):
    """Supported wiki page types (v1)."""

    SOURCE = "source"
    ENTITY = "entity"
    CONCEPT = "concept"
    PARSER = "parser"
    BENCHMARK = "benchmark"
    FAILURE = "failure"
    COMPARISON = "comparison"
    DECISION = "decision"


class PageStatus(str, Enum):
    """Wiki page lifecycle status."""

    DRAFT = "draft"
    AUTO = "auto"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class ReviewStatus(str, Enum):
    """Review status for a page."""

    PENDING = "pending"
    NOT_NEEDED = "not_needed"
    APPROVED = "approved"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Frontmatter — required for ALL pages
# ---------------------------------------------------------------------------

class Frontmatter(BaseModel):
    """Mandatory frontmatter for every wiki page.

    Every page in the wiki must carry this metadata.
    No page may exist without valid frontmatter.
    """

    id: str = Field(description="Stable page identifier (slug)")
    type: PageType
    title: str
    status: PageStatus = PageStatus.DRAFT
    schema_version: str = "1"
    created_at: date
    updated_at: date
    source_docs: list[str] = Field(
        default_factory=list,
        description="Source IDs this page derives from",
    )
    related_entities: list[str] = Field(default_factory=list)
    related_claims: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.PENDING


# ---------------------------------------------------------------------------
# Page-specific contracts
# ---------------------------------------------------------------------------

class SourcePageContent(BaseModel):
    """Content structure for a source page."""

    # Metadata
    file_name: str = ""
    mime_type: str = ""
    page_count: int = 0
    parser_route: str = ""
    ingest_status: str = ""

    # Summary
    high_level_summary: str = ""
    section_outline: list[str] = Field(default_factory=list)

    # Knowledge links
    extracted_entities: list[str] = Field(default_factory=list)
    key_claims: list[str] = Field(default_factory=list)
    known_warnings: list[str] = Field(default_factory=list)

    # Evidence
    evidence_links: list[str] = Field(default_factory=list)
    review_report_link: str | None = None


class EntityPageContent(BaseModel):
    """Content structure for an entity page."""

    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    entity_type: str = ""
    defining_description: str = ""
    related_claims: list[str] = Field(default_factory=list)
    supporting_sources: list[str] = Field(default_factory=list)
    related_entities: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class ConceptPageContent(BaseModel):
    """Content structure for a concept page."""

    concept_definition: str = ""
    boundary: str = Field(default="", description="Scope boundaries / non-goals")
    related_methods_systems: list[str] = Field(default_factory=list)
    claims_and_evidence: list[str] = Field(default_factory=list)
    comparison_notes: list[str] = Field(default_factory=list)
    unresolved_issues: list[str] = Field(default_factory=list)


class FailurePageContent(BaseModel):
    """Content structure for a failure page."""

    failure_definition: str = ""
    trigger_patterns: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    impacted_parsers: list[str] = Field(default_factory=list)
    repair_strategy: str = ""
    review_checklist: list[str] = Field(default_factory=list)


class ComparisonPageContent(BaseModel):
    """Content structure for a comparison page."""

    compared_objects: list[str] = Field(default_factory=list)
    comparison_dimensions: list[str] = Field(default_factory=list)
    evidence_backed_differences: list[str] = Field(default_factory=list)
    open_uncertainty: list[str] = Field(default_factory=list)
    recommendation: str = ""


class DecisionPageContent(BaseModel):
    """Content structure for a decision page."""

    decision_statement: str = ""
    context: str = ""
    alternatives: list[str] = Field(default_factory=list)
    rationale: str = ""
    consequences: list[str] = Field(default_factory=list)
    review_date: date | None = None


class ParserPageContent(BaseModel):
    """Content structure for a parser page."""

    parser_name: str = ""
    parser_version: str = ""
    capabilities: list[str] = Field(default_factory=list)
    supported_file_types: list[str] = Field(default_factory=list)
    route_assignments: list[str] = Field(default_factory=list)
    known_strengths: list[str] = Field(default_factory=list)
    known_limitations: list[str] = Field(default_factory=list)
    fallback_parsers: list[str] = Field(default_factory=list)
    quality_metrics: dict[str, float] = Field(default_factory=dict)


class BenchmarkPageContent(BaseModel):
    """Content structure for a benchmark page."""

    benchmark_name: str = ""
    dataset_description: str = ""
    evaluation_dimensions: list[str] = Field(default_factory=list)
    ground_truth_source: str = ""
    parser_results: list[str] = Field(default_factory=list)
    comparison_charts: list[str] = Field(default_factory=list)
    open_issues: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Page union — any typed page in the wiki
# ---------------------------------------------------------------------------

# Map page type → content model
PAGE_CONTENT_MAP: dict[PageType, type[BaseModel]] = {
    PageType.SOURCE: SourcePageContent,
    PageType.ENTITY: EntityPageContent,
    PageType.CONCEPT: ConceptPageContent,
    PageType.FAILURE: FailurePageContent,
    PageType.COMPARISON: ComparisonPageContent,
    PageType.DECISION: DecisionPageContent,
    PageType.PARSER: ParserPageContent,
    PageType.BENCHMARK: BenchmarkPageContent,
}
