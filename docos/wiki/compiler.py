"""Wiki compiler — generates and updates Markdown wiki pages.

Pages are never written directly. The compiler produces Markdown content
and patch artifacts that go through the lint → review → merge flow.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from docos.models.docir import DocIR
from docos.models.knowledge import (
    ClaimRecord,
    EntityRecord,
    EvidenceAnchor,
    KnowledgeRelation,
)
from docos.models.page import (
    ComparisonPageContent,
    ConceptPageContent,
    DecisionPageContent,
    EntityPageContent,
    FailurePageContent,
    Frontmatter,
    PageStatus,
    PageType,
    ReviewStatus,
    SourcePageContent,
)
from docos.models.patch import Change, ChangeType, Patch
from docos.models.source import SourceRecord


# ---------------------------------------------------------------------------
# Markdown builder helpers
# ---------------------------------------------------------------------------

def _frontmatter_yaml(fm: Frontmatter) -> str:
    """Serialize frontmatter to YAML block."""
    lines = ["---"]
    lines.append(f"id: {fm.id}")
    lines.append(f"type: {fm.type.value}")
    lines.append(f"title: {fm.title!r}")
    lines.append(f"status: {fm.status.value}")
    lines.append(f"schema_version: {fm.schema_version!r}")
    lines.append(f"created_at: {fm.created_at}")
    lines.append(f"updated_at: {fm.updated_at}")
    if fm.source_docs:
        lines.append(f"source_docs: {fm.source_docs}")
    if fm.related_entities:
        lines.append(f"related_entities: {fm.related_entities}")
    if fm.related_claims:
        lines.append(f"related_claims: {fm.related_claims}")
    lines.append(f"review_status: {fm.review_status.value}")
    lines.append("---")
    return "\n".join(lines)


def _slug(text: str) -> str:
    """Create a slug from text."""
    import re
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s[:80].strip("-")


# ---------------------------------------------------------------------------
# Page compiler
# ---------------------------------------------------------------------------

class WikiCompiler:
    """Compiles DocIR + knowledge objects into wiki pages.

    Each compile method returns a tuple of (frontmatter, markdown_body, page_path).
    The caller wraps these into a Patch for the lint → review → merge flow.
    """

    def __init__(self, wiki_dir: Path) -> None:
        self._wiki_dir = wiki_dir

    # ------------------------------------------------------------------
    # Source page (US-017)
    # ------------------------------------------------------------------

    def compile_source_page(
        self,
        source: SourceRecord,
        docir: DocIR,
        entities: list[EntityRecord],
        claims: list[ClaimRecord],
    ) -> tuple[Frontmatter, str, Path]:
        """Compile a source summary page."""
        today = date.today()
        fm = Frontmatter(
            id=f"source.{source.source_id}",
            type=PageType.SOURCE,
            title=source.file_name,
            status=PageStatus.AUTO,
            created_at=today,
            updated_at=today,
            source_docs=[source.source_id],
            related_entities=[e.entity_id for e in entities],
            related_claims=[c.claim_id for c in claims],
            review_status=ReviewStatus.PENDING,
        )

        # Content
        summary_lines = [
            f"# {source.file_name}",
            "",
            f"**Source ID:** `{source.source_id}`  ",
            f"**MIME Type:** {source.mime_type}  ",
            f"**Pages:** {docir.page_count}  ",
            f"**Parser:** {docir.parser} v{docir.parser_version}  ",
            f"**Schema:** v{docir.schema_version}  ",
            "",
        ]

        # Section outline
        headings = [b for b in docir.blocks if b.block_type.value == "heading"]
        if headings:
            summary_lines.append("## Section Outline")
            summary_lines.append("")
            for h in headings:
                indent = "  " if h.text_md.startswith("###") else ""
                summary_lines.append(f"{indent}- {h.text_plain.strip()}")
            summary_lines.append("")

        # Entities
        if entities:
            summary_lines.append("## Extracted Entities")
            summary_lines.append("")
            for e in entities[:20]:
                summary_lines.append(f"- **{e.canonical_name}** ({e.entity_type.value})")
            summary_lines.append("")

        # Key claims
        if claims:
            summary_lines.append("## Key Claims")
            summary_lines.append("")
            for c in claims[:15]:
                status_badge = f"`{c.status.value}`"
                summary_lines.append(f"- {status_badge} {c.statement[:120]}")
                for anc in c.evidence_anchors[:1]:
                    summary_lines.append(f"  - → p{anc.page_no}, block `{anc.block_id}`")
            summary_lines.append("")

        # Warnings
        if docir.warnings:
            summary_lines.append("## Warnings")
            summary_lines.append("")
            for w in docir.warnings[:10]:
                summary_lines.append(f"- [{w.severity}] {w.code}: {w.message}")
            summary_lines.append("")

        body = "\n".join(summary_lines)
        page_path = self._wiki_dir / "sources" / f"{_slug(source.source_id)}.md"

        return fm, body, page_path

    # ------------------------------------------------------------------
    # Entity pages (US-018)
    # ------------------------------------------------------------------

    def compile_entity_page(
        self,
        entity: EntityRecord,
        claims: list[ClaimRecord],
    ) -> tuple[Frontmatter, str, Path]:
        """Compile an entity page."""
        today = date.today()
        fm = Frontmatter(
            id=f"entity.{_slug(entity.canonical_name)}",
            type=PageType.ENTITY,
            title=entity.canonical_name,
            status=PageStatus.AUTO,
            created_at=today,
            updated_at=today,
            source_docs=entity.source_ids,
            related_claims=[c.claim_id for c in claims],
            related_entities=entity.related_entity_ids,
            review_status=ReviewStatus.PENDING,
        )

        lines = [
            f"# {entity.canonical_name}",
            "",
            f"**Type:** {entity.entity_type.value}  ",
        ]
        if entity.aliases:
            lines.append(f"**Aliases:** {', '.join(entity.aliases)}  ")
        lines.append("")

        if entity.defining_description:
            lines.append("## Description")
            lines.append("")
            lines.append(entity.defining_description)
            lines.append("")

        if entity.source_ids:
            lines.append("## Supporting Sources")
            lines.append("")
            for sid in entity.source_ids:
                lines.append(f"- [[source.{sid}]]")
            lines.append("")

        if claims:
            lines.append("## Related Claims")
            lines.append("")
            for c in claims[:10]:
                lines.append(f"- [{c.status.value}] {c.statement[:100]}")
            lines.append("")

        if entity.candidate_duplicates:
            lines.append("## Candidate Duplicates")
            lines.append("")
            for dup_id in entity.candidate_duplicates:
                lines.append(f"- `{dup_id}` (requires review)")
            lines.append("")

        body = "\n".join(lines)
        page_path = self._wiki_dir / "entities" / f"{_slug(entity.canonical_name)}.md"
        return fm, body, page_path

    # ------------------------------------------------------------------
    # Concept pages (US-019)
    # ------------------------------------------------------------------

    def compile_concept_page(
        self,
        concept_name: str,
        source_ids: list[str],
        related_claims: list[ClaimRecord],
        related_entities: list[EntityRecord],
    ) -> tuple[Frontmatter, str, Path]:
        """Compile a concept page."""
        today = date.today()
        fm = Frontmatter(
            id=f"concept.{_slug(concept_name)}",
            type=PageType.CONCEPT,
            title=concept_name,
            status=PageStatus.AUTO,
            created_at=today,
            updated_at=today,
            source_docs=source_ids,
            related_claims=[c.claim_id for c in related_claims],
            related_entities=[e.entity_id for e in related_entities],
            review_status=ReviewStatus.PENDING,
        )

        lines = [
            f"# {concept_name}",
            "",
            "## Definition",
            "",
            f"*{concept_name}* is a concept encountered in the document corpus.",
            "",
        ]

        if related_claims:
            lines.append("## Evidence-Backed Claims")
            lines.append("")
            for c in related_claims[:10]:
                lines.append(f"- {c.statement[:120]}")
                for anc in c.evidence_anchors[:1]:
                    lines.append(f"  - Evidence: p{anc.page_no}, `{anc.block_id}`")
            lines.append("")

        if related_entities:
            lines.append("## Related Entities")
            lines.append("")
            for e in related_entities:
                lines.append(f"- [[entity.{_slug(e.canonical_name)}]] — {e.canonical_name}")
            lines.append("")

        body = "\n".join(lines)
        page_path = self._wiki_dir / "concepts" / f"{_slug(concept_name)}.md"
        return fm, body, page_path

    # ------------------------------------------------------------------
    # Failure / Comparison / Decision pages (US-020)
    # ------------------------------------------------------------------

    def compile_failure_page(
        self,
        failure_name: str,
        trigger_patterns: list[str],
        impacted_parsers: list[str],
        description: str = "",
        source_ids: list[str] | None = None,
    ) -> tuple[Frontmatter, str, Path]:
        today = date.today()
        fm = Frontmatter(
            id=f"failure.{_slug(failure_name)}",
            type=PageType.FAILURE,
            title=failure_name,
            status=PageStatus.AUTO,
            created_at=today,
            updated_at=today,
            source_docs=source_ids or [],
            review_status=ReviewStatus.PENDING,
        )
        lines = [
            f"# Failure: {failure_name}",
            "",
            f"**Description:** {description or 'N/A'}",
            "",
            "## Trigger Patterns",
        ]
        for p in trigger_patterns:
            lines.append(f"- {p}")
        lines.append("")
        lines.append("## Impacted Parsers")
        for p in impacted_parsers:
            lines.append(f"- {p}")
        lines.append("")

        body = "\n".join(lines)
        page_path = self._wiki_dir / "failures" / f"{_slug(failure_name)}.md"
        return fm, body, page_path

    def compile_comparison_page(
        self,
        title: str,
        objects: list[str],
        dimensions: list[str],
        differences: list[str],
        source_ids: list[str] | None = None,
    ) -> tuple[Frontmatter, str, Path]:
        today = date.today()
        fm = Frontmatter(
            id=f"comparison.{_slug(title)}",
            type=PageType.COMPARISON,
            title=title,
            status=PageStatus.AUTO,
            created_at=today,
            updated_at=today,
            source_docs=source_ids or [],
            review_status=ReviewStatus.PENDING,
        )
        lines = [
            f"# Comparison: {title}",
            "",
            f"**Objects:** {', '.join(objects)}",
            "",
            "## Dimensions",
        ]
        for d in dimensions:
            lines.append(f"- {d}")
        lines.append("")
        lines.append("## Differences")
        for d in differences:
            lines.append(f"- {d}")
        lines.append("")

        body = "\n".join(lines)
        page_path = self._wiki_dir / "comparisons" / f"{_slug(title)}.md"
        return fm, body, page_path

    def compile_decision_page(
        self,
        statement: str,
        context: str,
        rationale: str,
        alternatives: list[str] | None = None,
        source_ids: list[str] | None = None,
    ) -> tuple[Frontmatter, str, Path]:
        today = date.today()
        fm = Frontmatter(
            id=f"decision.{_slug(statement)}",
            type=PageType.DECISION,
            title=statement,
            status=PageStatus.AUTO,
            created_at=today,
            updated_at=today,
            source_docs=source_ids or [],
            review_status=ReviewStatus.PENDING,
        )
        lines = [
            f"# Decision: {statement}",
            "",
            f"**Context:** {context}",
            "",
            f"**Rationale:** {rationale}",
            "",
        ]
        if alternatives:
            lines.append("## Alternatives Considered")
            for a in alternatives:
                lines.append(f"- {a}")
            lines.append("")

        body = "\n".join(lines)
        page_path = self._wiki_dir / "decisions" / f"{_slug(statement)}.md"
        return fm, body, page_path

    # ------------------------------------------------------------------
    # Full page to string
    # ------------------------------------------------------------------

    @staticmethod
    def render_page(frontmatter: Frontmatter, body: str) -> str:
        """Render a complete wiki page with frontmatter."""
        return _frontmatter_yaml(frontmatter) + "\n\n" + body
