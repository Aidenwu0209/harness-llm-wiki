"""US-024: Make harness consume real parse and knowledge artifacts."""

import json
import tempfile
from datetime import date, datetime
from pathlib import Path

from docos.artifact_stores import PatchStore, ReportStore, WikiPageState, WikiStore
from docos.harness.runner import HarnessRunner
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
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
        doc_id="doc_harness_001",
        source_id="src_001",
        parser="stdlib_pdf",
        parser_version="1.0",
        page_count=2,
        pages=[
            Page(page_no=1, width=612, height=792),
            Page(page_no=2, width=612, height=792),
        ],
        blocks=[
            Block(
                block_id="blk_001",
                page_no=1,
                block_type=BlockType.HEADING,
                reading_order=0,
                bbox=(0, 0, 612, 50),
                text_plain="Introduction",
                source_parser="stdlib_pdf",
                source_node_id="n1",
            ),
            Block(
                block_id="blk_002",
                page_no=1,
                block_type=BlockType.PARAGRAPH,
                reading_order=1,
                bbox=(0, 50, 612, 100),
                text_plain="This is the introduction paragraph.",
                source_parser="stdlib_pdf",
                source_node_id="n2",
            ),
            Block(
                block_id="blk_003",
                page_no=2,
                block_type=BlockType.PARAGRAPH,
                reading_order=2,
                bbox=(0, 0, 612, 50),
                text_plain="Second page content.",
                source_parser="stdlib_pdf",
                source_node_id="n3",
            ),
        ],
        confidence=0.85,
    )


def _make_entities() -> list[EntityRecord]:
    return [
        EntityRecord(
            entity_id="ent_001",
            canonical_name="Alpha Model",
            entity_type=EntityType.MODEL,
            source_ids=["src_001"],
        ),
        EntityRecord(
            entity_id="ent_002",
            canonical_name="Beta Dataset",
            entity_type=EntityType.DATASET,
            source_ids=["src_001"],
        ),
    ]


def _make_claims() -> list[ClaimRecord]:
    return [
        ClaimRecord(
            claim_id="clm_001",
            statement="Alpha achieves 95% accuracy on Beta",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[
                EvidenceAnchor(
                    anchor_id="anc_001",
                    source_id="src_001",
                    doc_id="doc_harness_001",
                    page_no=1,
                    block_id="blk_002",
                    quote="95% accuracy",
                ),
            ],
        ),
        ClaimRecord(
            claim_id="clm_002",
            statement="Beta is the largest dataset",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[
                EvidenceAnchor(
                    anchor_id="anc_002",
                    source_id="src_001",
                    doc_id="doc_harness_001",
                    page_no=2,
                    block_id="blk_003",
                ),
            ],
        ),
    ]


def _make_patch() -> Patch:
    return Patch(
        patch_id="pat_harness_001",
        run_id="run_001",
        source_id="src_001",
        changes=[
            Change(type=ChangeType.CREATE_PAGE, target="wiki/sources/test.md"),
        ],
        risk_score=0.15,
    )


class TestHarnessRealArtifacts:
    def test_harness_from_real_docir_and_knowledge(self) -> None:
        """Harness produces a report from real DocIR, claims, and entities."""
        runner = HarnessRunner()
        docir = _make_docir()
        claims = _make_claims()
        entities = _make_entities()
        patch = _make_patch()

        report = runner.run(
            run_id="run_001",
            source_id="src_001",
            docir=docir,
            claims=claims,
            entities=entities,
            patch=patch,
        )

        assert report.run_id == "run_001"
        assert report.parse_quality.metrics["page_count"] == 2
        assert report.parse_quality.metrics["block_count"] == 3
        assert report.parse_quality.metrics["confidence"] == 0.85
        assert report.knowledge_quality.metrics["total_claims"] == 2
        assert report.knowledge_quality.metrics["citation_coverage_pct"] == 100.0
        assert report.maintenance_quality.metrics["entity_count"] == 2
        assert report.maintenance_quality.metrics["risk_score"] == 0.15
        assert report.overall_passed is True

    def test_harness_reads_persisted_artifacts(self) -> None:
        """Harness report is generated from artifacts loaded from disk."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            # Persist DocIR as JSON (simulating IR store)
            docir = _make_docir()
            ir_dir = base / "ir"
            ir_dir.mkdir()
            ir_path = ir_dir / "run_001.json"
            ir_path.write_text(docir.model_dump_json(indent=2), encoding="utf-8")

            # Persist knowledge
            ks = KnowledgeStore(base / "knowledge")
            ks.save(KnowledgeArtifact(
                run_id="run_001",
                source_id="src_001",
                entities=_make_entities(),
                claims=_make_claims(),
            ))

            # Persist patch
            patch_store = PatchStore(base / "patches")
            patch = _make_patch()
            patch_store.save(patch)

            # Load from disk
            loaded_docir = DocIR.model_validate_json(ir_path.read_text(encoding="utf-8"))
            loaded_ka = ks.get("run_001")
            assert loaded_ka is not None
            loaded_patch = patch_store.get("pat_harness_001")
            assert loaded_patch is not None

            # Run harness on loaded artifacts
            runner = HarnessRunner()
            report = runner.run(
                run_id="run_001",
                source_id="src_001",
                docir=loaded_docir,
                claims=loaded_ka.claims,
                entities=loaded_ka.entities,
                patch=loaded_patch,
            )

            assert report.overall_passed is True
            assert report.knowledge_quality.metrics["citation_coverage_pct"] == 100.0

    def test_harness_report_persisted_to_disk(self) -> None:
        """Harness report can be persisted and reloaded."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            runner = HarnessRunner()
            report = runner.run(
                run_id="run_002",
                source_id="src_002",
                docir=_make_docir(),
                claims=_make_claims(),
                entities=_make_entities(),
                patch=_make_patch(),
            )

            # Persist report
            report_store = ReportStore(base / "reports")
            report_path = report_store.save(report)
            assert report_path.exists()

            # Reload
            loaded = report_store.get("run_002")
            assert loaded is not None
            assert loaded.run_id == "run_002"
            assert loaded.source_id == "src_002"
            assert loaded.overall_passed is True
            assert loaded.parse_quality.metrics["page_count"] == 2

    def test_harness_report_includes_overall_decision(self) -> None:
        """Report includes release decision after compute_overall()."""
        runner = HarnessRunner()
        report = runner.run(
            run_id="run_003",
            source_id="src_003",
            docir=_make_docir(),
            claims=_make_claims(),
            entities=_make_entities(),
            patch=_make_patch(),
        )

        # With good data, release_decision should be auto_merge
        assert report.release_decision == "auto_merge"
        assert report.overall_passed is True

    def test_harness_detects_quality_issues(self) -> None:
        """Harness flags quality issues when data is problematic."""
        # Create DocIR with low confidence and high-severity warnings
        from docos.models.docir import DocIRWarning

        docir = _make_docir()
        docir.confidence = 0.3
        docir.warnings.append(DocIRWarning(
            code="LOW_CONFIDENCE",
            message="Parse confidence below threshold",
            severity="high",
        ))

        runner = HarnessRunner()
        report = runner.run(
            run_id="run_004",
            source_id="src_004",
            docir=docir,
            claims=_make_claims(),
            entities=_make_entities(),
        )

        assert report.parse_quality.passed is False
        assert report.release_decision != "auto_merge"

    def test_harness_linked_from_manifest(self) -> None:
        """Verify RunManifest links to the persisted harness report artifact."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            run_id = "run_manifest_link_test"

            # Create and persist a RunManifest
            run_store = RunStore(base)
            manifest = RunManifest.create(
                run_id=run_id,
                source_id="src_005",
                source_file_path="/tmp/test.pdf",
                artifact_root=str(base / "artifacts" / run_id),
            )
            run_store.update(manifest)

            # Run harness
            runner = HarnessRunner()
            report = runner.run(
                run_id=run_id,
                source_id="src_005",
                docir=_make_docir(),
                claims=_make_claims(),
                entities=_make_entities(),
                patch=_make_patch(),
            )

            # Persist report
            report_store = ReportStore(base / "reports")
            report_path = report_store.save(report)

            # Link the report path in the manifest (as pipeline runner does)
            manifest.report_artifact_path = str(report_path)
            run_store.update(manifest)

            # Reload manifest and verify the link
            loaded_manifest = run_store.get(run_id)
            assert loaded_manifest is not None
            assert loaded_manifest.report_artifact_path is not None
            assert Path(loaded_manifest.report_artifact_path).exists()

            # Verify the linked report content
            report_artifact_path = Path(loaded_manifest.report_artifact_path)
            report_data = json.loads(report_artifact_path.read_text(encoding="utf-8"))
            assert report_data["run_id"] == run_id
            assert report_data["overall_passed"] is True
            assert report_data["release_decision"] == "auto_merge"
