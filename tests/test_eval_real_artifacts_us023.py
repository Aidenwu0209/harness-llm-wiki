"""US-023: Make eval load real artifacts from stores.

Verifies that:
- Eval (harness) reads persisted artifacts (DocIR, knowledge, patches)
- No empty placeholder inputs are used
- Bad fixture can produce a blocking eval result
"""

import json
import tempfile
from pathlib import Path

from docos.artifact_stores import PatchStore, ReportStore
from docos.harness.runner import HarnessReport, HarnessRunner
from docos.ir_store import IRStore
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.models.docir import Block, BlockType, DocIR, DocIRWarning, Page
from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    EvidenceAnchor,
)
from docos.models.patch import BlastRadius, Change, ChangeType, Patch


def _make_docir() -> DocIR:
    return DocIR(
        doc_id="doc_eval_001",
        source_id="src_eval_001",
        parser="stdlib_pdf",
        parser_version="1.0",
        page_count=2,
        pages=[
            Page(page_no=1, width=612, height=792),
            Page(page_no=2, width=612, height=792),
        ],
        blocks=[
            Block(
                block_id="blk_eval_001",
                page_no=1,
                block_type=BlockType.HEADING,
                reading_order=0,
                bbox=(0, 0, 612, 50),
                text_plain="Introduction",
                source_parser="stdlib_pdf",
                source_node_id="n1",
            ),
            Block(
                block_id="blk_eval_002",
                page_no=1,
                block_type=BlockType.PARAGRAPH,
                reading_order=1,
                bbox=(0, 50, 612, 100),
                text_plain="This is a paragraph with important claims.",
                source_parser="stdlib_pdf",
                source_node_id="n2",
            ),
        ],
        confidence=0.88,
    )


def _make_entities() -> list[EntityRecord]:
    return [
        EntityRecord(
            entity_id="ent_eval_001",
            canonical_name="Alpha Model",
            entity_type=EntityType.MODEL,
            source_ids=["src_eval_001"],
        ),
    ]


def _make_claims() -> list[ClaimRecord]:
    return [
        ClaimRecord(
            claim_id="clm_eval_001",
            statement="Alpha achieves 92% accuracy",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[
                EvidenceAnchor(
                    anchor_id="anc_eval_001",
                    source_id="src_eval_001",
                    doc_id="doc_eval_001",
                    page_no=1,
                    block_id="blk_eval_002",
                    quote="92% accuracy",
                ),
            ],
        ),
    ]


def _make_patch() -> Patch:
    return Patch(
        patch_id="pat_eval_001",
        run_id="run_eval_001",
        source_id="src_eval_001",
        changes=[
            Change(type=ChangeType.CREATE_PAGE, target="wiki/sources/alpha.md"),
        ],
        blast_radius=BlastRadius(pages=1, claims=1),
        risk_score=0.15,
    )


class TestEvalLoadsRealArtifactsFromStores:
    """Test that eval reads persisted artifacts from disk stores."""

    def test_eval_reads_persisted_docir(self) -> None:
        """Eval reads persisted DocIR from IRStore and produces quality metrics."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ir_store = IRStore(base / "ir")
            docir = _make_docir()
            ir_store.save(docir, run_id="run_eval_001")

            # Load from disk
            loaded_docir = ir_store.get("run_eval_001")
            assert loaded_docir is not None
            assert loaded_docir.doc_id == "doc_eval_001"
            assert loaded_docir.confidence == 0.88

            runner = HarnessRunner()
            report = runner.run(
                run_id="run_eval_001",
                source_id="src_eval_001",
                docir=loaded_docir,
                claims=_make_claims(),
                entities=_make_entities(),
                patch=_make_patch(),
            )
            assert report.parse_quality.metrics["page_count"] == 2
            assert report.parse_quality.metrics["block_count"] == 2
            assert report.parse_quality.metrics["confidence"] == 0.88
            assert report.parse_quality.passed is True

    def test_eval_reads_persisted_knowledge(self) -> None:
        """Eval reads persisted entities and claims from KnowledgeStore."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ks = KnowledgeStore(base / "knowledge")
            ks.save(KnowledgeArtifact(
                run_id="run_eval_001",
                source_id="src_eval_001",
                entities=_make_entities(),
                claims=_make_claims(),
            ))

            loaded_ka = ks.get("run_eval_001")
            assert loaded_ka is not None
            assert len(loaded_ka.entities) == 1
            assert loaded_ka.entities[0].canonical_name == "Alpha Model"
            assert len(loaded_ka.claims) == 1

            runner = HarnessRunner()
            report = runner.run(
                run_id="run_eval_001",
                source_id="src_eval_001",
                docir=_make_docir(),
                claims=loaded_ka.claims,
                entities=loaded_ka.entities,
                patch=_make_patch(),
            )
            assert report.knowledge_quality.metrics["total_claims"] == 1
            assert report.knowledge_quality.metrics["citation_coverage_pct"] == 100.0
            assert report.maintenance_quality.metrics["entity_count"] == 1

    def test_eval_reads_persisted_patch(self) -> None:
        """Eval reads persisted patch from PatchStore for blast radius."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            patch_store = PatchStore(base / "patches")
            patch = _make_patch()
            patch_store.save(patch)

            loaded_patch = patch_store.get("pat_eval_001")
            assert loaded_patch is not None
            assert loaded_patch.risk_score == 0.15

            runner = HarnessRunner()
            report = runner.run(
                run_id="run_eval_001",
                source_id="src_eval_001",
                docir=_make_docir(),
                claims=_make_claims(),
                entities=_make_entities(),
                patch=loaded_patch,
            )
            assert report.maintenance_quality.metrics["risk_score"] == 0.15
            assert report.maintenance_quality.metrics["blast_pages"] == 1
            assert report.maintenance_quality.metrics["blast_claims"] == 1

    def test_eval_reads_previous_report(self) -> None:
        """Eval reads a previous report from ReportStore for regression check."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report_store = ReportStore(base / "reports")

            # Create and persist a previous report
            runner = HarnessRunner()
            prev_report = runner.run(
                run_id="run_prev_001",
                source_id="src_eval_001",
                docir=_make_docir(),
                claims=_make_claims(),
                entities=_make_entities(),
                patch=_make_patch(),
            )
            report_store.save(prev_report)

            # Load previous report
            loaded_prev = report_store.get("run_prev_001")
            assert loaded_prev is not None

            # Run new eval with previous report loaded from disk
            new_report = runner.run(
                run_id="run_eval_002",
                source_id="src_eval_001",
                docir=_make_docir(),
                claims=_make_claims(),
                entities=_make_entities(),
                patch=_make_patch(),
                previous_report=loaded_prev,
            )
            # Same data should not trigger regression
            assert new_report.overall_passed is True


class TestEvalNoEmptyPlaceholders:
    """Verify eval does not rely on empty placeholder inputs."""

    def test_missing_docir_produces_blocking_result(self) -> None:
        """If DocIR is missing, eval fails clearly instead of false pass."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_no_docir",
            source_id="src_eval_001",
            docir=None,
            claims=_make_claims(),
            entities=_make_entities(),
        )
        assert report.parse_quality.passed is False
        assert "No DocIR provided" in report.parse_quality.notes
        assert report.overall_passed is False
        assert report.release_decision == "review_required"

    def test_missing_all_artifacts_produces_blocking_result(self) -> None:
        """When all artifacts are missing, eval produces a blocking result."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_empty",
            source_id="src_eval_001",
            docir=None,
            claims=None,
            entities=None,
            patch=None,
        )
        assert report.parse_quality.passed is False
        assert report.knowledge_quality.passed is True  # No claims -> trivially passes
        assert report.overall_passed is False
        assert report.release_decision == "review_required"

    def test_no_placeholder_empty_lists_used(self) -> None:
        """Verify that when artifacts are provided, they are real non-empty data."""
        runner = HarnessRunner()
        docir = _make_docir()
        claims = _make_claims()
        entities = _make_entities()
        patch = _make_patch()

        report = runner.run(
            run_id="run_full",
            source_id="src_eval_001",
            docir=docir,
            claims=claims,
            entities=entities,
            patch=patch,
        )

        # All metrics should reflect real data, not empty placeholders
        assert report.parse_quality.metrics["page_count"] == 2
        assert report.parse_quality.metrics["block_count"] == 2
        assert report.knowledge_quality.metrics["total_claims"] == 1
        assert report.knowledge_quality.metrics["supported_claims"] == 1
        assert report.maintenance_quality.metrics["entity_count"] == 1
        assert report.maintenance_quality.metrics["risk_score"] == 0.15
        assert report.overall_passed is True


class TestBadFixtureProducesBlockingEval:
    """A bad fixture should produce a blocking eval result."""

    def test_low_confidence_docir_blocks(self) -> None:
        """DocIR with low confidence blocks auto-merge."""
        docir = _make_docir()
        docir.confidence = 0.2

        runner = HarnessRunner()
        report = runner.run(
            run_id="run_low_conf",
            source_id="src_eval_001",
            docir=docir,
            claims=_make_claims(),
            entities=_make_entities(),
        )
        assert report.parse_quality.passed is False
        assert report.overall_passed is False
        assert report.release_decision == "review_required"

    def test_high_severity_warnings_block(self) -> None:
        """DocIR with high-severity warnings blocks auto-merge."""
        docir = _make_docir()
        docir.warnings.append(DocIRWarning(
            code="CRITICAL_PARSE_FAILURE",
            message="Failed to extract text from page 3",
            severity="high",
        ))

        runner = HarnessRunner()
        report = runner.run(
            run_id="run_warnings",
            source_id="src_eval_001",
            docir=docir,
            claims=_make_claims(),
            entities=_make_entities(),
        )
        assert report.parse_quality.passed is False
        assert "high-severity warnings" in report.parse_quality.notes[0]

    def test_bad_claims_without_evidence_block(self) -> None:
        """Claims without evidence anchors produce knowledge quality failure."""
        bad_claims = [
            ClaimRecord.model_construct(
                claim_id="clm_bad",
                statement="Unverified claim",
                status=ClaimStatus.SUPPORTED,
                evidence_anchors=[],
            ),
        ]

        runner = HarnessRunner()
        report = runner.run(
            run_id="run_bad_claims",
            source_id="src_eval_001",
            docir=_make_docir(),
            claims=bad_claims,
            entities=_make_entities(),
        )
        # knowledge_quality checks unsupported rate
        assert report.knowledge_quality.metrics["unsupported_claim_rate_pct"] == 100.0
        assert report.knowledge_quality.passed is False

    def test_full_bad_fixture_from_stores_produces_blocking(self) -> None:
        """A full pipeline with persisted bad data produces a blocking eval result."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            # Persist bad DocIR (low confidence)
            ir_store = IRStore(base / "ir")
            bad_docir = _make_docir()
            bad_docir.confidence = 0.1
            bad_docir.warnings.append(DocIRWarning(
                code="LOW_CONFIDENCE",
                message="Parse confidence below threshold",
                severity="high",
            ))
            ir_store.save(bad_docir, run_id="run_bad_full")

            # Load bad artifacts from disk
            loaded_docir = ir_store.get("run_bad_full")
            assert loaded_docir is not None

            runner = HarnessRunner()
            report = runner.run(
                run_id="run_bad_full",
                source_id="src_eval_001",
                docir=loaded_docir,
                claims=_make_claims(),
                entities=_make_entities(),
            )

            assert report.parse_quality.passed is False
            assert report.overall_passed is False
            assert report.release_decision == "review_required"

            # Persist the bad report
            report_store = ReportStore(base / "reports")
            report_path = report_store.save(report)
            assert report_path.exists()

            # Reload and verify blocking state
            loaded_report = report_store.get("run_bad_full")
            assert loaded_report is not None
            assert loaded_report.overall_passed is False
            assert loaded_report.release_decision == "review_required"
