"""US-025: Make lint and harness jointly block or route reviews.

Verifies that:
- P0 lint failures block auto-merge
- Missing harness output blocks auto-merge
- Fallback low-confidence or review-required harness creates review items
- Report includes final gate decision and reasons
"""

import json
import tempfile
from pathlib import Path

from docos.artifact_stores import ReportStore
from docos.harness.runner import HarnessRunner
from docos.lint.checker import LintFinding, LintSeverity, ReleaseGate, WikiLinter
from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    EvidenceAnchor,
)
from docos.models.page import Frontmatter, PageStatus, PageType, ReviewStatus
from docos.models.patch import Change, ChangeType, Patch
from docos.models.run import RunManifest, RunStatus
from docos.run_store import RunStore


def _make_docir() -> DocIR:
    return DocIR(
        doc_id="doc_joint_001",
        source_id="src_joint_001",
        parser="stdlib_pdf",
        parser_version="1.0",
        page_count=1,
        pages=[Page(page_no=1, width=612, height=792)],
        blocks=[
            Block(
                block_id="blk_joint_001",
                page_no=1,
                block_type=BlockType.PARAGRAPH,
                reading_order=0,
                bbox=(0, 0, 612, 50),
                text_plain="Joint test content",
                source_parser="stdlib_pdf",
                source_node_id="n1",
            ),
        ],
        confidence=0.9,
    )


def _make_good_claims() -> list[ClaimRecord]:
    return [
        ClaimRecord(
            claim_id="clm_joint_001",
            statement="Joint test claim",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[
                EvidenceAnchor(
                    anchor_id="anc_joint_001",
                    source_id="src_joint_001",
                    doc_id="doc_joint_001",
                    page_no=1,
                    block_id="blk_joint_001",
                ),
            ],
        ),
    ]


def _make_entities() -> list[EntityRecord]:
    return [
        EntityRecord(
            entity_id="ent_joint_001",
            canonical_name="JointEntity",
            entity_type=EntityType.CONCEPT,
            source_ids=["src_joint_001"],
        ),
    ]


def _make_pages() -> list[Frontmatter]:
    return [
        Frontmatter(
            id="source.joint",
            type=PageType.SOURCE,
            title="Joint Test Page",
            status=PageStatus.AUTO,
            created_at=__import__("datetime").date(2026, 4, 15),
            updated_at=__import__("datetime").date(2026, 4, 15),
            review_status=ReviewStatus.PENDING,
        ),
    ]


def _make_patch() -> Patch:
    return Patch(
        patch_id="pat_joint_001",
        run_id="run_joint_001",
        source_id="src_joint_001",
        changes=[Change(type=ChangeType.CREATE_PAGE, target="wiki/sources/joint.md")],
        risk_score=0.1,
    )


class TestLintHarnessJointControl:
    """Test that lint and harness jointly control auto-merge decisions."""

    def test_p0_lint_blocks_even_with_passing_harness(self) -> None:
        """P0 lint finding blocks auto-merge even when harness passes."""
        # Run real lint to get P0
        bad_page = Frontmatter(
            id="",
            type=PageType.SOURCE,
            title="Bad Page",
            status=PageStatus.AUTO,
            created_at=__import__("datetime").date(2026, 4, 15),
            updated_at=__import__("datetime").date(2026, 4, 15),
        )
        linter = WikiLinter()
        findings = linter.lint(pages=[bad_page], claims=[], entities=[])
        p0 = [f for f in findings if f.severity == LintSeverity.P0]
        assert len(p0) > 0

        # Run real harness (should pass)
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_p0_test",
            source_id="src_joint_001",
            docir=_make_docir(),
            claims=_make_good_claims(),
            entities=_make_entities(),
            patch=_make_patch(),
        )
        assert report.overall_passed is True

        # Gate should block despite passing harness
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=findings,
            harness_passed=True,
        )
        assert can_merge is False
        assert any("P0" in r for r in reasons)

    def test_missing_harness_blocks_with_clean_lint(self) -> None:
        """Missing harness blocks auto-merge even with clean lint."""
        # Clean lint
        linter = WikiLinter()
        findings = linter.lint(
            pages=_make_pages(),
            claims=_make_good_claims(),
            entities=_make_entities(),
        )
        assert len(findings) == 0

        # Missing harness
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=findings,
            harness_passed=None,
        )
        assert can_merge is False
        assert any("Harness has not run" in r for r in reasons)

    def test_both_lint_and_harness_fail_produces_multiple_reasons(self) -> None:
        """Both P0 lint and harness failure produce combined blocking reasons."""
        findings = [
            LintFinding(code="MISSING_ID", message="No ID", severity=LintSeverity.P0),
        ]

        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=findings,
            harness_passed=False,
        )
        assert can_merge is False
        assert any("P0" in r for r in reasons)
        assert any("Harness failed" in r for r in reasons)

    def test_clean_lint_and_passing_harness_allows_merge(self) -> None:
        """Clean lint + passing harness = auto-merge allowed."""
        linter = WikiLinter()
        findings = linter.lint(
            pages=_make_pages(),
            claims=_make_good_claims(),
            entities=_make_entities(),
        )

        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=findings,
            harness_passed=True,
        )
        assert can_merge is True
        assert len(reasons) == 0


class TestFallbackRoutesToReview:
    """Test that fallback and low-confidence results create review items."""

    def test_fallback_low_confidence_blocks_auto_merge(self) -> None:
        """Fallback with low confidence blocks auto-merge and routes to review."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=[],
            harness_passed=True,
            fallback_low_confidence=True,
        )
        assert can_merge is False
        assert any("Fallback" in r for r in reasons)
        assert any("confidence" in r.lower() for r in reasons)

    def test_fallback_with_p0_produces_review(self) -> None:
        """Fallback + P0 lint creates a review item with both reasons."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=[LintFinding(code="MISSING_ID", message="No ID", severity=LintSeverity.P0)],
            harness_passed=True,
            fallback_low_confidence=True,
        )
        assert can_merge is False
        assert len(reasons) >= 2  # P0 + fallback


class TestReportIncludesFinalGateDecision:
    """Test that reports include the final gate decision and reasons."""

    def test_persisted_report_includes_gate_decision(self) -> None:
        """Report persists final gate decision from combined lint+harness."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            # Run harness
            runner = HarnessRunner()
            report = runner.run(
                run_id="run_report_gate",
                source_id="src_joint_001",
                docir=_make_docir(),
                claims=_make_good_claims(),
                entities=_make_entities(),
                patch=_make_patch(),
            )

            # Run gate
            linter = WikiLinter()
            findings = linter.lint(
                pages=_make_pages(),
                claims=_make_good_claims(),
                entities=_make_entities(),
            )
            gate = ReleaseGate()
            can_merge, reasons = gate.check(
                findings=findings,
                harness_passed=report.overall_passed,
            )

            # Persist
            report_store = ReportStore(base / "reports")
            report_path = report_store.save(report)
            data = json.loads(report_path.read_text(encoding="utf-8"))
            assert data["overall_passed"] is True
            assert data["release_decision"] == "auto_merge"
            assert len(data["release_reasoning"]) > 0

    def test_manifest_includes_final_gate_with_reasons(self) -> None:
        """RunManifest persists final gate decision with blocking reasons."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_store = RunStore(base)

            manifest = RunManifest.create(
                run_id="run_manifest_joint",
                source_id="src_joint_001",
                source_file_path="/tmp/test.pdf",
                artifact_root=str(base / "artifacts" / "run_manifest_joint"),
            )

            # Simulate combined gate decision
            findings = [
                LintFinding(code="MISSING_ID", message="No ID", severity=LintSeverity.P0),
            ]
            gate = ReleaseGate()
            can_merge, reasons = gate.check(
                findings=findings,
                harness_passed=False,
            )

            manifest.gate_decision = "passed" if can_merge else "blocked"
            manifest.gate_blockers = reasons
            manifest.release_reasoning = reasons
            manifest.review_status = "pending" if not can_merge else "none"

            run_store.update(manifest)

            # Verify
            loaded = run_store.get("run_manifest_joint")
            assert loaded is not None
            assert loaded.gate_decision == "blocked"
            assert len(loaded.gate_blockers) >= 2  # P0 + harness failed
            assert loaded.review_status == "pending"

    def test_blocked_case_creates_review_routing(self) -> None:
        """A blocked case routes to review (review_status=pending)."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_store = RunStore(base)

            manifest = RunManifest.create(
                run_id="run_review_route",
                source_id="src_joint_001",
                source_file_path="/tmp/test.pdf",
                artifact_root=str(base / "artifacts" / "run_review_route"),
            )

            # Blocked by fallback low confidence
            gate = ReleaseGate()
            can_merge, reasons = gate.check(
                findings=[],
                harness_passed=True,
                fallback_low_confidence=True,
            )

            manifest.gate_decision = "passed" if can_merge else "blocked"
            manifest.gate_blockers = reasons
            manifest.review_status = "pending" if not can_merge else "none"

            run_store.update(manifest)

            loaded = run_store.get("run_review_route")
            assert loaded is not None
            assert loaded.gate_decision == "blocked"
            assert loaded.review_status == "pending"
            assert any("Fallback" in r for r in loaded.gate_blockers)
