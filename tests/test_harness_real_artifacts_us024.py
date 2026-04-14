"""US-024: Make harness consume real parse and knowledge artifacts."""

import tempfile
from pathlib import Path

from docos.artifact_stores import PatchStore, ReportStore
from docos.harness.runner import HarnessRunner
from docos.models.docir import DocIR
from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord, EntityType, EvidenceAnchor
from docos.models.patch import Change, ChangeType, Patch


def _make_docir() -> DocIR:
    return DocIR(
        doc_id="doc_001",
        source_id="src_001",
        parser="stdlib_pdf",
        parser_version="1.0",
        schema_version="1",
        page_count=5,
        confidence=0.85,
    )


def _make_claims() -> list[ClaimRecord]:
    return [
        ClaimRecord(
            claim_id="claim_001",
            statement="Test claim with evidence",
            status=ClaimStatus.SUPPORTED,
            source_ids=["src_001"],
            evidence_anchors=[EvidenceAnchor(
                anchor_id="anc_001", source_id="src_001", doc_id="doc_001",
                page_no=1, block_id="blk_001",
            )],
        ),
        ClaimRecord(
            claim_id="claim_002",
            statement="Another claim",
            status=ClaimStatus.INFERRED,
            source_ids=["src_001"],
            inference_note="Derived from context",
            evidence_anchors=[EvidenceAnchor(
                anchor_id="anc_002", source_id="src_001", doc_id="doc_001",
                page_no=2, block_id="blk_002",
            )],
        ),
    ]


def _make_entities() -> list[EntityRecord]:
    return [
        EntityRecord(
            entity_id="ent_001",
            canonical_name="TestEntity",
            entity_type=EntityType.CONCEPT,
            source_ids=["src_001"],
        ),
    ]


def _make_patch() -> Patch:
    return Patch(
        patch_id="pat_harness_test",
        run_id="run_001",
        source_id="src_001",
        changes=[
            Change(type=ChangeType.CREATE_PAGE, target="wiki/sources/test.md"),
        ],
        risk_score=0.2,
    )


class TestHarnessRealArtifacts:
    def test_harness_reads_real_docir(self) -> None:
        """Harness reads real DocIR parse artifacts and produces quality metrics."""
        runner = HarnessRunner()
        docir = _make_docir()
        report = runner.run(
            run_id="run_001",
            source_id="src_001",
            docir=docir,
            claims=_make_claims(),
            entities=_make_entities(),
            patch=_make_patch(),
        )
        assert report.parse_quality.metrics["page_count"] == 5
        assert report.parse_quality.metrics["block_count"] == 0  # No blocks in this DocIR
        assert report.parse_quality.metrics["confidence"] == 0.85
        assert report.parse_quality.passed is True

    def test_harness_reads_real_claims(self) -> None:
        """Harness reads real knowledge claims and produces quality metrics."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_001",
            source_id="src_001",
            docir=_make_docir(),
            claims=_make_claims(),
            entities=_make_entities(),
            patch=_make_patch(),
        )
        assert report.knowledge_quality.metrics["total_claims"] == 2

    def test_harness_reads_real_entities(self) -> None:
        """Harness reads real entities and computes duplicate rate."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_001",
            source_id="src_001",
            docir=_make_docir(),
            claims=_make_claims(),
            entities=_make_entities(),
            patch=_make_patch(),
        )
        assert report.maintenance_quality.metrics["entity_count"] == 1
        assert report.maintenance_quality.metrics["duplicate_entity_rate_pct"] == 0.0

    def test_harness_reads_real_patch(self) -> None:
        """Harness reads real patch data for blast radius metrics."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_001",
            source_id="src_001",
            docir=_make_docir(),
            claims=_make_claims(),
            entities=_make_entities(),
            patch=_make_patch(),
        )
        assert "risk_score" in report.maintenance_quality.metrics
        assert report.maintenance_quality.metrics["risk_score"] == 0.2


class TestHarnessPersistedReport:
    def test_harness_report_persisted_to_disk(self) -> None:
        """Harness report is written to disk as a structured artifact."""
        with tempfile.TemporaryDirectory() as tmp:
            report_store = ReportStore(Path(tmp) / "reports")

            runner = HarnessRunner()
            report = runner.run(
                run_id="run_persist_test",
                source_id="src_001",
                docir=_make_docir(),
                claims=_make_claims(),
                entities=_make_entities(),
                patch=_make_patch(),
            )

            # Persist report
            path = report_store.save(report)
            assert path.exists()

            # Load back
            loaded = report_store.get("run_persist_test")
            assert loaded is not None
            assert loaded.run_id == "run_persist_test"
            assert loaded.overall_passed is True

    def test_harness_report_includes_overall_decision(self) -> None:
        """Report includes the overall release decision."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_decision_test",
            source_id="src_001",
            docir=_make_docir(),
            claims=_make_claims(),
            entities=_make_entities(),
            patch=_make_patch(),
        )
        assert report.release_decision in ("auto_merge", "review_required", "pending")
        report.compute_overall()
        assert report.release_decision in ("auto_merge", "review_required")


class TestHarnessFromPersistedArtifacts:
    def test_harness_from_persisted_patch(self) -> None:
        """Harness can load a patch from PatchStore and use it."""
        with tempfile.TemporaryDirectory() as tmp:
            patch_store = PatchStore(Path(tmp) / "patches")
            patch = _make_patch()
            patch_store.save(patch)

            # Simulate loading from store
            loaded_patch = patch_store.get("pat_harness_test")
            assert loaded_patch is not None

            runner = HarnessRunner()
            report = runner.run(
                run_id="run_from_store",
                source_id="src_001",
                docir=_make_docir(),
                claims=_make_claims(),
                entities=_make_entities(),
                patch=loaded_patch,
            )
            assert report.maintenance_quality.metrics["risk_score"] == 0.2
