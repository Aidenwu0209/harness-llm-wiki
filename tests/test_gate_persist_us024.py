"""US-024: Persist release decisions and gate blockers.

Verifies that:
- Gate output persists release_decision, release_reasoning, and gate_blockers
- RunManifest stores whether the run entered review and whether fallback was used
- Report output displays the persisted release decision and reasons
"""

import json
import tempfile
from pathlib import Path

from docos.artifact_stores import ReportStore
from docos.harness.runner import HarnessReport, HarnessRunner
from docos.ir_store import IRStore
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.lint.checker import LintFinding, LintSeverity, ReleaseGate
from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    EvidenceAnchor,
)
from docos.models.patch import Change, ChangeType, Patch
from docos.models.run import RunManifest, RunStatus
from docos.run_store import RunStore


def _make_docir() -> DocIR:
    return DocIR(
        doc_id="doc_gate_001",
        source_id="src_gate_001",
        parser="stdlib_pdf",
        parser_version="1.0",
        page_count=2,
        pages=[
            Page(page_no=1, width=612, height=792),
            Page(page_no=2, width=612, height=792),
        ],
        blocks=[
            Block(
                block_id="blk_gate_001",
                page_no=1,
                block_type=BlockType.PARAGRAPH,
                reading_order=0,
                bbox=(0, 0, 612, 50),
                text_plain="Gate test content",
                source_parser="stdlib_pdf",
                source_node_id="n1",
            ),
        ],
        confidence=0.9,
    )


def _make_claims() -> list[ClaimRecord]:
    return [
        ClaimRecord(
            claim_id="clm_gate_001",
            statement="Gate test claim",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[
                EvidenceAnchor(
                    anchor_id="anc_gate_001",
                    source_id="src_gate_001",
                    doc_id="doc_gate_001",
                    page_no=1,
                    block_id="blk_gate_001",
                ),
            ],
        ),
    ]


def _make_entities() -> list[EntityRecord]:
    return [
        EntityRecord(
            entity_id="ent_gate_001",
            canonical_name="GateEntity",
            entity_type=EntityType.CONCEPT,
            source_ids=["src_gate_001"],
        ),
    ]


def _make_patch() -> Patch:
    return Patch(
        patch_id="pat_gate_001",
        run_id="run_gate_001",
        source_id="src_gate_001",
        changes=[Change(type=ChangeType.CREATE_PAGE, target="wiki/sources/gate.md")],
        risk_score=0.1,
    )


class TestGateOutputPersisted:
    """Test that gate decisions are persisted to manifest and reports."""

    def test_harness_report_persists_release_decision(self) -> None:
        """HarnessReport includes release_decision, release_reasoning, and gate_blockers."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_gate_001",
            source_id="src_gate_001",
            docir=_make_docir(),
            claims=_make_claims(),
            entities=_make_entities(),
            patch=_make_patch(),
        )
        assert report.release_decision == "auto_merge"
        assert len(report.release_reasoning) > 0
        assert "All quality sections passed" in report.release_reasoning

    def test_harness_report_persists_blocking_reasons(self) -> None:
        """HarnessReport includes release_reasoning when blocked."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_blocked",
            source_id="src_gate_001",
            docir=None,  # Missing DocIR -> blocked
        )
        assert report.release_decision == "review_required"
        assert len(report.release_reasoning) > 0
        assert any("Parse quality failed" in r for r in report.release_reasoning)

    def test_gate_decision_persisted_to_disk(self) -> None:
        """Gate decision is persisted as a structured JSON artifact."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            # Run harness
            runner = HarnessRunner()
            report = runner.run(
                run_id="run_gate_persist",
                source_id="src_gate_001",
                docir=_make_docir(),
                claims=_make_claims(),
                entities=_make_entities(),
                patch=_make_patch(),
            )

            # Persist report
            report_store = ReportStore(base / "reports")
            report_path = report_store.save(report)
            assert report_path.exists()

            # Load and verify
            loaded = report_store.get("run_gate_persist")
            assert loaded is not None
            assert loaded.release_decision == "auto_merge"
            assert loaded.release_reasoning == ["All quality sections passed"]
            assert loaded.gate_blockers == []

    def test_gate_blockers_persisted_when_blocked(self) -> None:
        """Gate blockers are persisted when auto-merge is blocked."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            # Create a failing scenario
            runner = HarnessRunner()
            report = runner.run(
                run_id="run_blocked_persist",
                source_id="src_gate_001",
                docir=None,
            )

            # Persist report
            report_store = ReportStore(base / "reports")
            report_store.save(report)

            # Load and verify blocking state
            loaded = report_store.get("run_blocked_persist")
            assert loaded is not None
            assert loaded.release_decision == "review_required"
            assert len(loaded.release_reasoning) > 0

    def test_release_gate_check_persists_blockers(self) -> None:
        """ReleaseGate.check() returns blockers that can be persisted."""
        gate = ReleaseGate()

        # Create P0 finding
        findings = [
            LintFinding(
                code="MISSING_ID",
                message="Page has no ID",
                severity=LintSeverity.P0,
            ),
        ]

        can_merge, reasons = gate.check(
            findings=findings,
            harness_passed=True,
        )
        assert can_merge is False
        assert len(reasons) > 0
        assert any("P0" in r for r in reasons)

        # These reasons become gate_blockers
        gate_blockers = reasons
        assert "P0 lint exists (1 findings)" in gate_blockers

    def test_release_gate_with_missing_harness(self) -> None:
        """Missing harness output blocks auto-merge."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=[],
            harness_passed=None,
        )
        assert can_merge is False
        assert any("Harness has not run" in r for r in reasons)


class TestManifestStoresGateResults:
    """Test that RunManifest stores gate decisions and review state."""

    def test_manifest_stores_gate_blockers(self) -> None:
        """RunManifest stores gate_blockers when gate blocks."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_store = RunStore(base)

            manifest = RunManifest.create(
                run_id="run_manifest_gate",
                source_id="src_gate_001",
                source_file_path="/tmp/test.pdf",
                artifact_root=str(base / "artifacts" / "run_manifest_gate"),
            )

            # Simulate gate decision
            gate = ReleaseGate()
            findings = [
                LintFinding(
                    code="MISSING_ID",
                    message="Page has no ID",
                    severity=LintSeverity.P0,
                ),
            ]
            can_merge, reasons = gate.check(findings=findings, harness_passed=False)

            manifest.gate_decision = "passed" if can_merge else "blocked"
            manifest.gate_blockers = reasons
            manifest.release_reasoning = reasons
            manifest.review_status = "pending"
            manifest.fallback_used = False

            run_store.update(manifest)

            # Reload and verify
            loaded = run_store.get("run_manifest_gate")
            assert loaded is not None
            assert loaded.gate_decision == "blocked"
            assert len(loaded.gate_blockers) > 0
            assert loaded.review_status == "pending"
            assert loaded.fallback_used is False

    def test_manifest_stores_passed_gate(self) -> None:
        """RunManifest stores passed gate with no blockers."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_store = RunStore(base)

            manifest = RunManifest.create(
                run_id="run_manifest_pass",
                source_id="src_gate_001",
                source_file_path="/tmp/test.pdf",
                artifact_root=str(base / "artifacts" / "run_manifest_pass"),
            )

            manifest.gate_decision = "passed"
            manifest.gate_blockers = []
            manifest.release_reasoning = ["All gates passed"]
            manifest.review_status = "none"
            manifest.fallback_used = False

            run_store.update(manifest)

            loaded = run_store.get("run_manifest_pass")
            assert loaded is not None
            assert loaded.gate_decision == "passed"
            assert loaded.gate_blockers == []
            assert loaded.release_reasoning == ["All gates passed"]
            assert loaded.review_status == "none"

    def test_manifest_stores_fallback_used(self) -> None:
        """RunManifest stores whether fallback parser was used."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_store = RunStore(base)

            manifest = RunManifest.create(
                run_id="run_manifest_fallback",
                source_id="src_gate_001",
                source_file_path="/tmp/test.pdf",
                artifact_root=str(base / "artifacts" / "run_manifest_fallback"),
            )

            manifest.fallback_used = True
            manifest.gate_decision = "passed"
            manifest.review_status = "none"

            run_store.update(manifest)

            loaded = run_store.get("run_manifest_fallback")
            assert loaded is not None
            assert loaded.fallback_used is True


class TestReportDisplaysGateDecision:
    """Test that report output displays persisted release decision and reasons."""

    def test_report_json_includes_gate_fields(self) -> None:
        """Persisted report JSON includes release_decision, release_reasoning, gate_blockers."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_report_display",
            source_id="src_gate_001",
            docir=_make_docir(),
            claims=_make_claims(),
            entities=_make_entities(),
            patch=_make_patch(),
        )

        with tempfile.TemporaryDirectory() as tmp:
            report_store = ReportStore(Path(tmp))
            path = report_store.save(report)

            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["release_decision"] == "auto_merge"
            assert "release_reasoning" in data
            assert "gate_blockers" in data
            assert data["release_reasoning"] == ["All quality sections passed"]
            assert data["gate_blockers"] == []

    def test_blocked_report_json_shows_blockers(self) -> None:
        """Blocked report JSON shows gate blockers and reasoning."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_blocked_report",
            source_id="src_gate_001",
            docir=None,
        )

        with tempfile.TemporaryDirectory() as tmp:
            report_store = ReportStore(Path(tmp))
            path = report_store.save(report)

            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["release_decision"] == "review_required"
            assert len(data["release_reasoning"]) > 0
            assert data["overall_passed"] is False
