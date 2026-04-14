"""Lint — structural, knowledge, and operational quality checks.

Runs before merge to catch schema violations, broken links,
unsupported claims, duplicate entities, and other quality issues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from docos.models.docir import DocIR
from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord
from docos.models.page import Frontmatter, PageType
from docos.models.patch import Patch


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

class LintSeverity(str, Enum):
    P0 = "P0"  # Blocks merge
    P1 = "P1"  # Must fix before merge
    P2 = "P2"  # Track but can merge
    P3 = "P3"  # Suggestion


# ---------------------------------------------------------------------------
# Lint finding
# ---------------------------------------------------------------------------

@dataclass
class LintFinding:
    code: str
    message: str
    severity: LintSeverity
    page_id: str | None = None
    block_id: str | None = None
    claim_id: str | None = None
    entity_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Linter
# ---------------------------------------------------------------------------

class WikiLinter:
    """Runs all lint checks on wiki state.

    Categories:
    - Structural: frontmatter, schema, links, IDs
    - Knowledge: evidence, inference, conflicts, duplicates
    - Operational: parser version, review status, risk score
    """

    def lint(
        self,
        pages: list[Frontmatter],
        claims: list[ClaimRecord],
        entities: list[EntityRecord],
        docir: DocIR | None = None,
        patch: Patch | None = None,
        page_bodies: dict[str, str] | None = None,
    ) -> list[LintFinding]:
        findings: list[LintFinding] = []
        findings.extend(self._lint_structure(pages))
        findings.extend(self._lint_knowledge(claims, entities))
        findings.extend(self._lint_operational(pages, patch))
        if page_bodies:
            findings.extend(self._lint_body(pages, page_bodies, claims, docir))
        return findings

    # ------------------------------------------------------------------
    # Structural lint
    # ------------------------------------------------------------------

    def _lint_structure(self, pages: list[Frontmatter]) -> list[LintFinding]:
        findings: list[LintFinding] = []

        seen_ids: set[str] = set()
        for page in pages:
            # Missing ID
            if not page.id:
                findings.append(LintFinding(
                    code="MISSING_ID", message="Page has no ID",
                    severity=LintSeverity.P0, page_id=page.id,
                ))
                continue

            # Duplicate ID
            if page.id in seen_ids:
                findings.append(LintFinding(
                    code="DUPLICATE_ID", message=f"Duplicate page ID: {page.id}",
                    severity=LintSeverity.P0, page_id=page.id,
                ))
            seen_ids.add(page.id)

            # Invalid page type
            try:
                PageType(page.type)
            except ValueError:
                findings.append(LintFinding(
                    code="INVALID_PAGE_TYPE", message=f"Invalid page type: {page.type}",
                    severity=LintSeverity.P0, page_id=page.id,
                ))

            # Missing title
            if not page.title:
                findings.append(LintFinding(
                    code="MISSING_TITLE", message=f"Page {page.id} has no title",
                    severity=LintSeverity.P1, page_id=page.id,
                ))

        return findings

    # ------------------------------------------------------------------
    # Knowledge lint
    # ------------------------------------------------------------------

    def _lint_knowledge(
        self, claims: list[ClaimRecord], entities: list[EntityRecord]
    ) -> list[LintFinding]:
        findings: list[LintFinding] = []

        for claim in claims:
            # Supported claim without evidence
            if claim.status == ClaimStatus.SUPPORTED and not claim.evidence_anchors:
                findings.append(LintFinding(
                    code="UNSUPPORTED_CLAIM_NO_EVIDENCE",
                    message=f"Claim {claim.claim_id} is SUPPORTED but has no evidence anchors",
                    severity=LintSeverity.P1,
                    claim_id=claim.claim_id,
                ))

            # Inferred claim without inference note
            if claim.status == ClaimStatus.INFERRED and not claim.inference_note:
                findings.append(LintFinding(
                    code="INFERRED_CLAIM_NO_NOTE",
                    message=f"Claim {claim.claim_id} is INFERRED but has no inference_note",
                    severity=LintSeverity.P1,
                    claim_id=claim.claim_id,
                ))

            # Conflicted claim without conflicting sources
            if claim.status == ClaimStatus.CONFLICTED and not claim.conflicting_sources:
                findings.append(LintFinding(
                    code="CONFLICTED_CLAIM_NO_SOURCES",
                    message=f"Claim {claim.claim_id} is CONFLICTED but has no conflicting sources",
                    severity=LintSeverity.P1,
                    claim_id=claim.claim_id,
                ))

        # Duplicate entity candidates
        entity_names: dict[str, list[str]] = {}
        for ent in entities:
            key = ent.canonical_name.lower().strip()
            entity_names.setdefault(key, []).append(ent.entity_id)

        for name, ids in entity_names.items():
            if len(ids) > 1:
                findings.append(LintFinding(
                    code="DUPLICATE_ENTITY_CANDIDATES",
                    message=f"Potential duplicate entities for '{name}': {ids}",
                    severity=LintSeverity.P2,
                    entity_id=ids[0],
                ))

        return findings

    def _lint_body(
        self,
        pages: list[Frontmatter],
        page_bodies: dict[str, str],
        claims: list[ClaimRecord],
        docir: DocIR | None = None,
    ) -> list[LintFinding]:
        """Lint page body content: wikilinks, anchors, schema-body consistency."""
        import re
        findings: list[LintFinding] = []

        page_ids = {p.id for p in pages}
        claim_ids = {c.claim_id for c in claims}
        block_ids = {b.block_id for b in docir.blocks} if docir else set()

        for page in pages:
            body = page_bodies.get(page.id, "")
            if not body:
                continue

            # Broken wikilinks: [[target]] where target not in page_ids
            wikilinks = re.findall(r"\[\[([^\]]+)\]\]", body)
            for link in wikilinks:
                link_id = link.split("|")[0].strip().split(".")[-1]
                if link_id and link_id not in page_ids and link_id not in claim_ids:
                    findings.append(LintFinding(
                        code="BROKEN_WIKILINK",
                        message=f"Broken wikilink [[{link}]] on page {page.id}",
                        severity=LintSeverity.P1, page_id=page.id,
                    ))

            # Missing or invalid anchors: [[anchor#...]] reference to non-existent blocks
            anchor_refs = re.findall(r"#(blk_\w+)", body)
            for ref in anchor_refs:
                if block_ids and ref not in block_ids:
                    findings.append(LintFinding(
                        code="INVALID_ANCHOR",
                        message=f"Invalid anchor #{ref} on page {page.id}",
                        severity=LintSeverity.P1, page_id=page.id,
                    ))

            # Schema-body mismatch: page claims to have source_docs but body is empty
            if page.source_docs and len(body) < 50:
                findings.append(LintFinding(
                    code="SCHEMA_BODY_MISMATCH",
                    message=f"Page {page.id} has source_docs but empty body",
                    severity=LintSeverity.P2, page_id=page.id,
                ))

        return findings

    # ------------------------------------------------------------------
    # Operational lint
    # ------------------------------------------------------------------

    def _lint_operational(
        self, pages: list[Frontmatter], patch: Patch | None
    ) -> list[LintFinding]:
        findings: list[LintFinding] = []

        if patch is not None:
            # Patch missing risk score
            if patch.risk_score == 0.0 and patch.changes:
                findings.append(LintFinding(
                    code="PATCH_NO_RISK_SCORE",
                    message=f"Patch {patch.patch_id} has risk_score=0 with changes",
                    severity=LintSeverity.P2,
                ))

            # High blast radius without review
            if patch.blast_radius.pages > 3 and not patch.review_required:
                findings.append(LintFinding(
                    code="HIGH_BLAST_NO_REVIEW",
                    message=f"Patch {patch.patch_id} has blast_radius.pages={patch.blast_radius.pages} but review_required=False",
                    severity=LintSeverity.P1,
                ))

        return findings


# ---------------------------------------------------------------------------
# Release gate
# ---------------------------------------------------------------------------

class ReleaseGate:
    """Determines whether a patch can be auto-merged.

    A patch is blocked from auto-merge if any P0/P1 lint exists,
    harness hasn't run, or regression exceeds thresholds.
    """

    def __init__(self, config: Any = None) -> None:
        self._config = config

    def check(
        self,
        findings: list[LintFinding],
        harness_passed: bool | None = None,
        regression_ok: bool | None = None,
        unsupported_claim_increase: bool = False,
        fallback_low_confidence: bool = False,
    ) -> tuple[bool, list[str]]:
        """Check if auto-merge is allowed.

        Reads blocking conditions from config if available, otherwise
        uses sensible defaults.

        Returns:
            (can_merge, list of blocking reasons)
        """
        reasons: list[str] = []

        # Read config thresholds
        block_p0 = True
        block_p1 = True
        block_missing_harness = True
        if self._config is not None:
            gates = getattr(self._config, "release_gates", None)
            if gates is not None:
                block_p0 = getattr(gates, "block_on_p0_lint", True)
                block_p1 = getattr(gates, "block_on_p1_lint", True)
                block_missing_harness = getattr(gates, "block_on_missing_harness", True)

        # P0 lint blocks
        p0 = [f for f in findings if f.severity == LintSeverity.P0]
        if p0 and block_p0:
            reasons.append(f"P0 lint exists ({len(p0)} findings)")

        # P1 lint blocks
        p1 = [f for f in findings if f.severity == LintSeverity.P1]
        if p1 and block_p1:
            reasons.append(f"P1 lint exists ({len(p1)} findings)")

        # Harness not run
        if harness_passed is None and block_missing_harness:
            reasons.append("Harness has not run")
        elif harness_passed is False:
            reasons.append("Harness failed")

        # Regression exceeded
        if regression_ok is False:
            reasons.append("Regression exceeds thresholds")

        # Unsupported claim increase
        if unsupported_claim_increase:
            reasons.append("Unsupported claims increased")

        # Fallback with low confidence
        if fallback_low_confidence:
            reasons.append("Fallback output below confidence policy")

        can_merge = len(reasons) == 0
        return can_merge, reasons
