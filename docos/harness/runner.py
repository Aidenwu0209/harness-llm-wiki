"""Harness — evaluation runner and reporting.

Runs quality checks on every ingest and produces structured reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from docos.models.docir import DocIR
from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord
from docos.models.patch import Patch


# ---------------------------------------------------------------------------
# Harness report
# ---------------------------------------------------------------------------

@dataclass
class HarnessSection:
    name: str
    metrics: dict[str, float | int] = field(default_factory=dict)
    passed: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass
class HarnessReport:
    """Structured report from a harness run."""

    run_id: str
    source_id: str
    generated_at: datetime = field(default_factory=datetime.now)

    # Sections
    parse_quality: HarnessSection = field(default_factory=lambda: HarnessSection("parse_quality"))
    knowledge_quality: HarnessSection = field(default_factory=lambda: HarnessSection("knowledge_quality"))
    maintenance_quality: HarnessSection = field(default_factory=lambda: HarnessSection("maintenance_quality"))

    # Overall
    overall_passed: bool = True
    release_decision: str = "pending"  # pending | auto_merge | review_required | blocked
    release_reasoning: list[str] = field(default_factory=list)
    gate_blockers: list[str] = field(default_factory=list)

    def compute_overall(self) -> None:
        self.overall_passed = (
            self.parse_quality.passed
            and self.knowledge_quality.passed
            and self.maintenance_quality.passed
        )
        if self.overall_passed:
            self.release_decision = "auto_merge"
            self.release_reasoning = ["All quality sections passed"]
        else:
            self.release_decision = "review_required"
            reasons: list[str] = []
            if not self.parse_quality.passed:
                reasons.append(f"Parse quality failed: {'; '.join(self.parse_quality.notes)}")
            if not self.knowledge_quality.passed:
                reasons.append(f"Knowledge quality failed: {'; '.join(self.knowledge_quality.notes)}")
            if not self.maintenance_quality.passed:
                reasons.append(f"Maintenance quality failed: {'; '.join(self.maintenance_quality.notes)}")
            self.release_reasoning = reasons


# ---------------------------------------------------------------------------
# Harness runner
# ---------------------------------------------------------------------------

class HarnessRunner:
    """Runs quality evaluation on ingest results."""

    def run(
        self,
        run_id: str,
        source_id: str,
        docir: DocIR | None = None,
        claims: list[ClaimRecord] | None = None,
        entities: list[EntityRecord] | None = None,
        patch: Patch | None = None,
        previous_report: HarnessReport | None = None,
    ) -> HarnessReport:
        """Run full harness evaluation.

        Returns:
            HarnessReport with all sections filled.
        """
        report = HarnessReport(run_id=run_id, source_id=source_id)
        claims = claims or []
        entities = entities or []

        self._eval_parse_quality(report, docir)
        self._eval_knowledge_quality(report, claims)
        self._eval_maintenance_quality(report, entities, patch)

        # Regression check
        if previous_report:
            self._check_regression(report, previous_report)

        report.compute_overall()
        return report

    def _eval_parse_quality(self, report: HarnessReport, docir: DocIR | None) -> None:
        if docir is None:
            report.parse_quality.passed = False
            report.parse_quality.notes.append("No DocIR provided")
            return

        metrics = report.parse_quality.metrics
        metrics["page_count"] = docir.page_count
        metrics["block_count"] = len(docir.blocks)
        metrics["relation_count"] = len(docir.relations)
        metrics["warning_count"] = len(docir.warnings)
        metrics["confidence"] = docir.confidence

        # Check for unknown blocks (good — they're preserved, not dropped)
        unknown_blocks = sum(1 for b in docir.blocks if b.block_type.value == "unknown")
        metrics["unknown_block_count"] = unknown_blocks

        # Parse passes if confidence > 0.5 and no critical warnings
        critical_warnings = sum(1 for w in docir.warnings if w.severity == "high")
        report.parse_quality.passed = docir.confidence >= 0.5 and critical_warnings == 0

        if critical_warnings > 0:
            report.parse_quality.notes.append(f"{critical_warnings} high-severity warnings")

    def _eval_knowledge_quality(self, report: HarnessReport, claims: list[ClaimRecord]) -> None:
        metrics = report.knowledge_quality.metrics
        metrics["total_claims"] = len(claims)

        if not claims:
            report.knowledge_quality.passed = True
            return

        supported = [c for c in claims if c.status == ClaimStatus.SUPPORTED]
        inferred = [c for c in claims if c.status == ClaimStatus.INFERRED]
        conflicted = [c for c in claims if c.status == ClaimStatus.CONFLICTED]

        metrics["supported_claims"] = len(supported)
        metrics["inferred_claims"] = len(inferred)
        metrics["conflicted_claims"] = len(conflicted)

        # Citation coverage
        with_evidence = sum(1 for c in claims if c.evidence_anchors)
        coverage = with_evidence / len(claims) * 100 if claims else 100
        metrics["citation_coverage_pct"] = round(coverage, 1)

        # Unsupported rate
        unsupported = sum(1 for c in supported if not c.evidence_anchors)
        unsupported_rate = unsupported / len(supported) * 100 if supported else 0
        metrics["unsupported_claim_rate_pct"] = round(unsupported_rate, 1)

        # Quality gates
        report.knowledge_quality.passed = (
            coverage >= 95
            and unsupported_rate <= 2
        )

        if coverage < 95:
            report.knowledge_quality.notes.append(f"Citation coverage {coverage:.1f}% < 95%")
        if unsupported_rate > 2:
            report.knowledge_quality.notes.append(f"Unsupported rate {unsupported_rate:.1f}% > 2%")

    def _eval_maintenance_quality(
        self,
        report: HarnessReport,
        entities: list[EntityRecord],
        patch: Patch | None,
    ) -> None:
        metrics = report.maintenance_quality.metrics
        metrics["entity_count"] = len(entities)

        # Duplicate entity rate
        names: dict[str, int] = {}
        for e in entities:
            key = e.canonical_name.lower().strip()
            names[key] = names.get(key, 0) + 1

        dup_count = sum(c - 1 for c in names.values() if c > 1)
        dup_rate = dup_count / len(entities) * 100 if entities else 0
        metrics["duplicate_entity_rate_pct"] = round(dup_rate, 1)

        # Patch blast radius
        if patch:
            metrics["blast_pages"] = patch.blast_radius.pages
            metrics["blast_claims"] = patch.blast_radius.claims
            metrics["risk_score"] = patch.risk_score

        report.maintenance_quality.passed = dup_rate <= 3
        if dup_rate > 3:
            report.maintenance_quality.notes.append(f"Duplicate entity rate {dup_rate:.1f}% > 3%")

    def _check_regression(self, current: HarnessReport, previous: HarnessReport) -> None:
        """Compare current vs previous report for regression."""
        # If coverage dropped significantly
        curr_cov = current.knowledge_quality.metrics.get("citation_coverage_pct", 100)
        prev_cov = previous.knowledge_quality.metrics.get("citation_coverage_pct", 100)
        if curr_cov < prev_cov - 5:
            current.knowledge_quality.passed = False
            current.knowledge_quality.notes.append(
                f"Regression: citation coverage dropped from {prev_cov:.1f}% to {curr_cov:.1f}%"
            )
