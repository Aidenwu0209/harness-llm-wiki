"""US-025: Enforce release gate rules and report gate decisions."""

import tempfile
from pathlib import Path
from dataclasses import dataclass

from docos.lint.checker import LintFinding, LintSeverity, ReleaseGate, WikiLinter
from docos.models.config import AppConfig, ReleaseGates
from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    EvidenceAnchor,
)
from docos.models.page import Frontmatter, PageStatus, PageType, ReviewStatus
from docos.models.patch import BlastRadius, Change, ChangeType, Patch


def _p0_finding() -> LintFinding:
    return LintFinding(
        code="MISSING_ID",
        message="Page has no ID",
        severity=LintSeverity.P0,
    )


def _p1_finding() -> LintFinding:
    return LintFinding(
        code="MISSING_TITLE",
        message="Page has no title",
        severity=LintSeverity.P1,
    )


def _make_claims() -> list[ClaimRecord]:
    return [
        ClaimRecord(
            claim_id="clm_001",
            statement="Test claim",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[
                EvidenceAnchor(
                    anchor_id="anc_001",
                    source_id="src_001",
                    doc_id="doc_001",
                    page_no=1,
                    block_id="blk_001",
                ),
            ],
        ),
    ]


def _make_entities() -> list[EntityRecord]:
    return [
        EntityRecord(
            entity_id="ent_001",
            canonical_name="Test Entity",
            entity_type=EntityType.CONCEPT,
        ),
    ]


def _make_pages() -> list[Frontmatter]:
    return [
        Frontmatter(
            id="source.test",
            type=PageType.SOURCE,
            title="Test Page",
            status=PageStatus.AUTO,
            created_at=__import__("datetime").date(2026, 4, 15),
            updated_at=__import__("datetime").date(2026, 4, 15),
            review_status=ReviewStatus.PENDING,
        ),
    ]


class TestGateBlocksOnP0Lint:
    def test_p0_lint_blocks_auto_merge(self) -> None:
        """P0 lint finding blocks auto-merge."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(findings=[_p0_finding()])
        assert can_merge is False
        assert any("P0" in r for r in reasons)

    def test_p0_lint_blocks_with_harness_passed(self) -> None:
        """P0 blocks even when harness passed."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=[_p0_finding()],
            harness_passed=True,
        )
        assert can_merge is False
        assert any("P0" in r for r in reasons)

    def test_p0_blocks_from_real_lint(self) -> None:
        """A real lint run on bad data produces a P0 that blocks the gate."""
        # Page with empty ID triggers P0
        bad_page = Frontmatter(
            id="",
            type=PageType.SOURCE,
            title="Bad",
            status=PageStatus.AUTO,
            created_at=__import__("datetime").date(2026, 4, 15),
            updated_at=__import__("datetime").date(2026, 4, 15),
            review_status=ReviewStatus.PENDING,
        )

        linter = WikiLinter()
        findings = linter.lint(pages=[bad_page], claims=[], entities=[])
        p0 = [f for f in findings if f.severity == LintSeverity.P0]
        assert len(p0) > 0

        gate = ReleaseGate()
        can_merge, reasons = gate.check(findings=findings, harness_passed=True)
        assert can_merge is False
        assert any("P0" in r for r in reasons)


class TestGateBlocksOnMissingHarness:
    def test_missing_harness_blocks(self) -> None:
        """Missing harness (None) blocks auto-merge."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(findings=[], harness_passed=None)
        assert can_merge is False
        assert any("Harness has not run" in r for r in reasons)

    def test_failed_harness_blocks(self) -> None:
        """Failed harness blocks auto-merge."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(findings=[], harness_passed=False)
        assert can_merge is False
        assert any("Harness failed" in r for r in reasons)


class TestGateRequiresReviewForFallback:
    def test_fallback_low_confidence_requires_review(self) -> None:
        """Fallback low-confidence result blocks auto-merge."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=[],
            harness_passed=True,
            fallback_low_confidence=True,
        )
        assert can_merge is False
        assert any("Fallback" in r for r in reasons)

    def test_fallback_with_p0_and_low_confidence(self) -> None:
        """Both P0 and fallback issues are reported."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=[_p0_finding()],
            harness_passed=True,
            fallback_low_confidence=True,
        )
        assert can_merge is False
        assert any("P0" in r for r in reasons)
        assert any("Fallback" in r for r in reasons)


class TestGateDecisionReport:
    def test_clean_run_allows_auto_merge(self) -> None:
        """No findings + harness passed = auto-merge allowed."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(findings=[], harness_passed=True)
        assert can_merge is True
        assert len(reasons) == 0

    def test_report_includes_all_reasons(self) -> None:
        """Multiple blocking conditions all appear in reasons."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=[_p0_finding(), _p1_finding()],
            harness_passed=None,
            regression_ok=False,
        )
        assert can_merge is False
        assert len(reasons) >= 3  # P0, P1, missing harness, regression

    def test_gate_report_with_real_lint_and_harness(self) -> None:
        """Full integration: lint + gate produces a meaningful gate decision."""
        pages = _make_pages()
        claims = _make_claims()
        entities = _make_entities()

        linter = WikiLinter()
        findings = linter.lint(pages=pages, claims=claims, entities=entities)

        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=findings,
            harness_passed=True,
        )
        assert can_merge is True
        assert len(reasons) == 0


class TestGateWithConfig:
    def test_config_can_disable_p0_block(self) -> None:
        """Config can set block_on_p0_lint=False to allow P0 through."""
        config = AppConfig(
            release_gates=ReleaseGates(block_on_p0_lint=False),
        )
        gate = ReleaseGate(config=config)
        can_merge, reasons = gate.check(
            findings=[_p0_finding()],
            harness_passed=True,
        )
        # P0 not blocked when config disables it
        assert not any("P0" in r for r in reasons)
        assert can_merge is True

    def test_config_can_disable_missing_harness_block(self) -> None:
        """Config can set block_on_missing_harness=False."""
        config = AppConfig(
            release_gates=ReleaseGates(block_on_missing_harness=False),
        )
        gate = ReleaseGate(config=config)
        can_merge, reasons = gate.check(
            findings=[],
            harness_passed=None,
        )
        # No harness blocking when config disables it
        assert not any("Harness" in r for r in reasons)
        assert can_merge is True
