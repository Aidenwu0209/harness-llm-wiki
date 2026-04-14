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
    BenchmarkPageContent,
    ComparisonPageContent,
    ConceptPageContent,
    DecisionPageContent,
    EntityPageContent,
    FailurePageContent,
    Frontmatter,
    PageStatus,
    PageType,
    ParserPageContent,
    ReviewStatus,
    SourcePageContent,
)
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.models.source import SourceRecord

# Sentinel for deleted pages
_DELETED_BODY = "__DELETED_PAGE__"


# ---------------------------------------------------------------------------
# Compiled page result
# ---------------------------------------------------------------------------

class CompiledPage:
    """Result of compiling a wiki page — state before any file write."""

    def __init__(
        self,
        frontmatter: Frontmatter,
        body: str,
        page_path: Path,
        run_id: str = "",
        existing_body: str | None = None,
        deleted: bool = False,
    ) -> None:
        self.frontmatter = frontmatter
        self.body = body
        self.page_path = page_path
        self.run_id = run_id
        self.existing_body = existing_body
        self.deleted = deleted

    def compute_patch(self, run_id: str = "", source_id: str = "") -> Patch:
        """Compute a patch diff against existing page content.

        Returns a CREATE_PAGE patch for a new page, an UPDATE_PAGE patch
        for changed existing content, or a DELETE_PAGE patch when the
        page should be removed.

        Blast radius and risk are derived from real diff data:
        - **pages**: number of changed pages (always 1 per CompiledPage)
        - **claims**: extracted from ``related_claims`` in frontmatter
        - **links**: extracted from ``related_entities`` in frontmatter
        - **risk**: proportional to the change magnitude (line-level diff
          ratio for updates, fixed baselines for create/delete)
        """
        import hashlib
        import difflib

        content_for_hash = self.body
        if self.deleted:
            change_type = ChangeType.DELETE_PAGE
            summary = "Page deletion"
        elif self.existing_body is None:
            change_type = ChangeType.CREATE_PAGE
            summary = "New page creation"
        else:
            change_type = ChangeType.UPDATE_PAGE
            summary = "Page content update"

        # Deterministic hash from canonical content
        content_hash = hashlib.sha256(content_for_hash.encode()).hexdigest()[:12]
        patch_id = f"pat_{self.frontmatter.id}_{content_hash}"

        # -- Compute blast radius from real data --
        pages_affected = 1
        claims_affected = len(self.frontmatter.related_claims) if self.frontmatter.related_claims else 0
        links_affected = len(self.frontmatter.related_entities) if self.frontmatter.related_entities else 0

        # Count actual line-level changes for updates
        lines_added = 0
        lines_removed = 0
        if self.existing_body is not None and not self.deleted:
            old_lines = self.existing_body.splitlines(keepends=True)
            new_lines = self.body.splitlines(keepends=True)
            diff = list(difflib.unified_diff(old_lines, new_lines, n=0))
            for line in diff:
                if line.startswith("+") and not line.startswith("+++"):
                    lines_added += 1
                elif line.startswith("-") and not line.startswith("---"):
                    lines_removed += 1

        blast = BlastRadius(
            pages=pages_affected,
            claims=claims_affected,
            links=links_affected,
        )

        # -- Compute risk from real diff data --
        risk = 0.0
        if self.deleted:
            # Deletions are inherently higher risk
            risk = 0.5 + 0.1 * min(pages_affected + claims_affected, 5) / 5
        elif self.existing_body is None:
            # New pages: risk scales with content size
            new_line_count = len(self.body.splitlines()) if self.body else 0
            risk = min(0.1 + new_line_count * 0.005, 0.4)
        else:
            # Updates: risk proportional to change ratio
            total_old_lines = max(len(self.existing_body.splitlines()), 1)
            changed_lines = lines_added + lines_removed
            change_ratio = changed_lines / total_old_lines
            risk = min(0.1 + change_ratio * 0.6, 0.8)

        risk = round(min(risk, 1.0), 4)

        return Patch(
            patch_id=patch_id,
            run_id=run_id,
            source_id=source_id,
            changes=[
                Change(type=change_type, target=str(self.page_path), summary=summary),
            ],
            blast_radius=blast,
            risk_score=risk,
        )

    @property
    def full_content(self) -> str:
        return _frontmatter_yaml(self.frontmatter) + "\n\n" + self.body


# ---------------------------------------------------------------------------
# Markdown builder helpers
# ---------------------------------------------------------------------------

def _frontmatter_yaml(fm: Frontmatter) -> str:
    """Serialize frontmatter to YAML block using YAML serializer."""
    import yaml  # type: ignore[import-untyped]

    data: dict[str, Any] = {
        "id": fm.id,
        "type": fm.type.value,
        "title": fm.title,
        "status": fm.status.value,
        "schema_version": fm.schema_version,
        "created_at": str(fm.created_at),
        "updated_at": str(fm.updated_at),
        "review_status": fm.review_status.value,
    }
    if fm.source_docs:
        data["source_docs"] = fm.source_docs
    if fm.related_entities:
        data["related_entities"] = fm.related_entities
    if fm.related_claims:
        data["related_claims"] = fm.related_claims

    yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return f"---\n{yaml_str}---"


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

    def compile_parser_page(
        self,
        parser_name: str,
        content: ParserPageContent,
        source_ids: list[str] | None = None,
    ) -> tuple[Frontmatter, str, Path]:
        """Compile a parser info page."""
        today = date.today()
        fm = Frontmatter(
            id=f"parser-{_slug(parser_name)}",
            type=PageType.PARSER,
            title=f"Parser: {parser_name}",
            created_at=today,
            updated_at=today,
            source_docs=source_ids or [],
            review_status=ReviewStatus.NOT_NEEDED,
        )
        lines = [
            f"# Parser: {parser_name}",
            "",
            f"**Version:** {content.parser_version}",
            "",
        ]
        if content.capabilities:
            lines.append("## Capabilities")
            for cap in content.capabilities:
                lines.append(f"- {cap}")
            lines.append("")
        if content.known_limitations:
            lines.append("## Known Limitations")
            for lim in content.known_limitations:
                lines.append(f"- {lim}")
            lines.append("")
        if content.fallback_parsers:
            lines.append("## Fallback Parsers")
            for fb in content.fallback_parsers:
                lines.append(f"- {fb}")
            lines.append("")
        body = "\n".join(lines)
        page_path = self._wiki_dir / "parsers" / f"{_slug(parser_name)}.md"
        return fm, body, page_path

    def compile_benchmark_page(
        self,
        benchmark_name: str,
        content: BenchmarkPageContent,
        source_ids: list[str] | None = None,
    ) -> tuple[Frontmatter, str, Path]:
        """Compile a benchmark page."""
        today = date.today()
        fm = Frontmatter(
            id=f"benchmark-{_slug(benchmark_name)}",
            type=PageType.BENCHMARK,
            title=f"Benchmark: {benchmark_name}",
            created_at=today,
            updated_at=today,
            source_docs=source_ids or [],
            review_status=ReviewStatus.NOT_NEEDED,
        )
        lines = [
            f"# Benchmark: {benchmark_name}",
            "",
            f"**Dataset:** {content.dataset_description}",
            "",
        ]
        if content.evaluation_dimensions:
            lines.append("## Evaluation Dimensions")
            for dim in content.evaluation_dimensions:
                lines.append(f"- {dim}")
            lines.append("")
        if content.parser_results:
            lines.append("## Parser Results")
            for res in content.parser_results:
                lines.append(f"- {res}")
            lines.append("")
        body = "\n".join(lines)
        page_path = self._wiki_dir / "benchmarks" / f"{_slug(benchmark_name)}.md"
        return fm, body, page_path

    # ------------------------------------------------------------------
    # Full page to string
    # ------------------------------------------------------------------

    @staticmethod
    def render_page(frontmatter: Frontmatter, body: str) -> str:
        """Render a complete wiki page with frontmatter."""
        return _frontmatter_yaml(frontmatter) + "\n\n" + body
