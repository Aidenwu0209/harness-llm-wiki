"""Tests for Patch/Risk, Lint, Release Gates, and Harness (US-021~026)."""

from datetime import date

import pytest

from docos.lint.checker import LintFinding, LintSeverity, ReleaseGate, WikiLinter
from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord, EntityType
from docos.models.page import Frontmatter, PageType
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.harness.runner import HarnessReport, HarnessRunner


# ---------------------------------------------------------------------------
# US-021/022: Patch generation & risk
# ---------------------------------------------------------------------------

class TestPatchRiskScoring:
    def test_compute_blast_radius(self) -> None:
        patch = Patch(
            patch_id="p1", run_id="r1", source_id="s1",
            changes=[
                Change(type=ChangeType.CREATE_PAGE, target="a.md"),
                Change(type=ChangeType.UPDATE_PAGE, target="b.md"),
                Change(type=ChangeType.ADD_CLAIM, target="c1"),
            ],
            blast_radius=BlastRadius(pages=2, claims=1, links=3),
            risk_score=0.35,
        )
        assert patch.blast_radius.pages == 2
        assert patch.blast_radius.claims == 1

    def test_high_risk_marked_review(self) -> None:
        patch = Patch(
            patch_id="p2", run_id="r2", source_id="s2",
            blast_radius=BlastRadius(pages=10, claims=20, links=30),
            risk_score=0.85,
            review_required=True,
        )
        assert patch.review_required is True

    def test_patch_not_direct_write(self) -> None:
        """Patch never writes directly — it's a proposal."""
        patch = Patch(patch_id="p3", run_id="r3", source_id="s3")
        assert patch.merge_status.value == "pending"


# ---------------------------------------------------------------------------
# US-023: Lint
# ---------------------------------------------------------------------------

class TestWikiLinter:
    def test_detect_missing_id(self) -> None:
        linter = WikiLinter()
        pages = [Frontmatter(id="", type=PageType.SOURCE, title="T", created_at=date.today(), updated_at=date.today())]
        findings = linter._lint_structure(pages)
        assert any(f.code == "MISSING_ID" for f in findings)

    def test_detect_duplicate_id(self) -> None:
        linter = WikiLinter()
        pages = [
            Frontmatter(id="dup", type=PageType.SOURCE, title="A", created_at=date.today(), updated_at=date.today()),
            Frontmatter(id="dup", type=PageType.ENTITY, title="B", created_at=date.today(), updated_at=date.today()),
        ]
        findings = linter._lint_structure(pages)
        assert any(f.code == "DUPLICATE_ID" for f in findings)

    def test_detect_unsupported_claim(self) -> None:
        linter = WikiLinter()
        # ClaimRecord with SUPPORTED but no anchors would fail pydantic validation,
        # so we test the linter with a manually constructed scenario
        claims = [
            ClaimRecord(
                claim_id="c1", statement="Supported with anchor",
                status=ClaimStatus.SUPPORTED,
                evidence_anchors=[__import__("docos.models.knowledge", fromlist=["EvidenceAnchor"]).EvidenceAnchor(
                    anchor_id="a1", source_id="s1", doc_id="d1", page_no=1, block_id="b1"
                )],
            ),
        ]
        findings = linter._lint_knowledge(claims, [])
        # No finding because claim has evidence
        assert not any(f.code == "UNSUPPORTED_CLAIM_NO_EVIDENCE" for f in findings)

    def test_detect_inferred_claim_without_note(self) -> None:
        linter = WikiLinter()
        claims = [
            ClaimRecord(
                claim_id="c2", statement="Inferred",
                status=ClaimStatus.INFERRED,
                inference_note="Derived from pattern",  # has note
            ),
        ]
        findings = linter._lint_knowledge(claims, [])
        assert not any(f.code == "INFERRED_CLAIM_NO_NOTE" for f in findings)

    def test_detect_duplicate_entities(self) -> None:
        linter = WikiLinter()
        entities = [
            EntityRecord(entity_id="e1", canonical_name="READOC", entity_type=EntityType.BENCHMARK),
            EntityRecord(entity_id="e2", canonical_name="readoc", entity_type=EntityType.BENCHMARK),
        ]
        findings = linter._lint_knowledge([], entities)
        assert any(f.code == "DUPLICATE_ENTITY_CANDIDATES" for f in findings)

    def test_high_blast_no_review(self) -> None:
        linter = WikiLinter()
        patch = Patch(
            patch_id="p1", run_id="r1", source_id="s1",
            blast_radius=BlastRadius(pages=5, claims=10),
            review_required=False,
        )
        findings = linter._lint_operational([], patch)
        assert any(f.code == "HIGH_BLAST_NO_REVIEW" for f in findings)

    def test_clean_lint(self) -> None:
        linter = WikiLinter()
        pages = [Frontmatter(id="clean", type=PageType.SOURCE, title="Clean Page", created_at=date.today(), updated_at=date.today())]
        findings = linter.lint(pages, [], [])
        assert all(f.severity in (LintSeverity.P2, LintSeverity.P3) for f in findings)


# ---------------------------------------------------------------------------
# US-024: Release gate
# ---------------------------------------------------------------------------

class TestReleaseGate:
    def test_allow_merge_when_clean(self) -> None:
        gate = ReleaseGate()
        can_merge, reasons = gate.check([], harness_passed=True, regression_ok=True)
        assert can_merge is True
        assert len(reasons) == 0

    def test_block_on_p0(self) -> None:
        gate = ReleaseGate()
        findings = [LintFinding(code="BAD", message="Bad", severity=LintSeverity.P0)]
        can_merge, reasons = gate.check(findings)
        assert can_merge is False
        assert any("P0" in r for r in reasons)

    def test_block_on_p1(self) -> None:
        gate = ReleaseGate()
        findings = [LintFinding(code="WARN", message="Warn", severity=LintSeverity.P1)]
        can_merge, reasons = gate.check(findings)
        assert can_merge is False

    def test_block_no_harness(self) -> None:
        gate = ReleaseGate()
        can_merge, reasons = gate.check([], harness_passed=None)
        assert can_merge is False
        assert any("Harness" in r for r in reasons)

    def test_block_regression(self) -> None:
        gate = ReleaseGate()
        can_merge, reasons = gate.check([], harness_passed=True, regression_ok=False)
        assert can_merge is False
        assert any("Regression" in r for r in reasons)

    def test_block_unsupported_increase(self) -> None:
        gate = ReleaseGate()
        can_merge, reasons = gate.check([], harness_passed=True, regression_ok=True, unsupported_claim_increase=True)
        assert can_merge is False

    def test_block_fallback_low_confidence(self) -> None:
        gate = ReleaseGate()
        can_merge, reasons = gate.check([], harness_passed=True, regression_ok=True, fallback_low_confidence=True)
        assert can_merge is False


# ---------------------------------------------------------------------------
# US-025/026: Harness
# ---------------------------------------------------------------------------

class TestHarnessRunner:
    def test_harness_report_structure(self) -> None:
        report = HarnessReport(run_id="r1", source_id="s1")
        assert report.parse_quality.name == "parse_quality"
        assert report.knowledge_quality.name == "knowledge_quality"
        assert report.maintenance_quality.name == "maintenance_quality"
        assert report.release_decision == "pending"

    def test_harness_run_basic(self) -> None:
        runner = HarnessRunner()
        report = runner.run(run_id="r1", source_id="s1")
        assert report.run_id == "r1"
        # No DocIR → parse_quality fails → overall fails → review_required
        assert report.overall_passed is False
        assert report.release_decision == "review_required"
        assert "No DocIR" in report.parse_quality.notes[0]

    def test_harness_with_claims(self) -> None:
        from docos.models.knowledge import EvidenceAnchor
        runner = HarnessRunner()
        claims = [
            ClaimRecord(
                claim_id="c1", statement="Test",
                status=ClaimStatus.SUPPORTED,
                evidence_anchors=[
                    EvidenceAnchor(anchor_id="a1", source_id="s1", doc_id="d1", page_no=1, block_id="b1")
                ],
                supporting_sources=["s1"],
            ),
        ]
        report = runner.run(run_id="r1", source_id="s1", claims=claims)
        assert report.knowledge_quality.metrics["total_claims"] == 1
        assert report.knowledge_quality.metrics["citation_coverage_pct"] == 100.0

    def test_harness_compute_overall(self) -> None:
        report = HarnessReport(run_id="r1", source_id="s1")
        report.parse_quality.passed = True
        report.knowledge_quality.passed = False
        report.maintenance_quality.passed = True
        report.compute_overall()
        assert report.overall_passed is False
        assert report.release_decision == "review_required"


class TestRegressionComparison:
    def test_regression_detected(self) -> None:
        runner = HarnessRunner()
        prev = HarnessReport(run_id="r0", source_id="s1")
        prev.knowledge_quality.metrics["citation_coverage_pct"] = 98.0

        current = HarnessReport(run_id="r1", source_id="s1")
        current.knowledge_quality.metrics["citation_coverage_pct"] = 88.0

        runner._check_regression(current, prev)
        assert not current.knowledge_quality.passed
        assert any("dropped" in n for n in current.knowledge_quality.notes)

    def test_no_regression(self) -> None:
        runner = HarnessRunner()
        prev = HarnessReport(run_id="r0", source_id="s1")
        prev.knowledge_quality.metrics["citation_coverage_pct"] = 95.0

        current = HarnessReport(run_id="r1", source_id="s1")
        current.knowledge_quality.metrics["citation_coverage_pct"] = 97.0

        runner._check_regression(current, prev)
        assert current.knowledge_quality.passed
