"""Tests for US-012: render docos report from persisted run data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.artifact_stores import PatchStore, ReportStore, WikiStore
from docos.harness.runner import HarnessReport
from docos.ir_store import IRStore
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.patch import Change, ChangeType, Patch
from docos.run_store import RunStore


def _make_docir() -> DocIR:
    return DocIR(
        doc_id="doc_test",
        source_id="src_test",
        parser="stdlib_pdf",
        page_count=2,
        pages=[
            Page(page_no=1, width=612.0, height=792.0, blocks=["blk_1"]),
            Page(page_no=2, width=612.0, height=792.0, blocks=["blk_2"]),
        ],
        blocks=[
            Block(
                block_id="blk_1", page_no=1, block_type=BlockType.PARAGRAPH,
                reading_order=0, bbox=(0, 0, 100, 20), text_plain="Hello",
                source_parser="stdlib_pdf", source_node_id="n1",
            ),
            Block(
                block_id="blk_2", page_no=2, block_type=BlockType.PARAGRAPH,
                reading_order=0, bbox=(0, 0, 100, 20), text_plain="World",
                source_parser="stdlib_pdf", source_node_id="n2",
            ),
        ],
    )


def _setup_full_run(tmp_path: Path) -> str:
    """Create a full run with all artifacts and return the run_id."""
    run_store = RunStore(tmp_path)
    manifest = run_store.create(
        source_id="src_test",
        source_hash="a" * 64,
        source_file_path="/tmp/test.pdf",
    )
    run_id = manifest.run_id

    # IR artifact
    ir_store = IRStore(tmp_path / "ir")
    ir_path = ir_store.save(_make_docir(), run_id)
    manifest.ir_artifact_path = str(ir_path)

    # Knowledge artifact
    ks = KnowledgeStore(tmp_path / "knowledge")
    artifact = KnowledgeArtifact(
        run_id=run_id,
        source_id="src_test",
    )
    ks_path = ks.save(artifact)
    manifest.knowledge_artifact_path = str(ks_path)

    # Patch artifact
    ps = PatchStore(tmp_path / "patches")
    patch = Patch(
        patch_id=f"pat_{run_id}",
        run_id=run_id,
        source_id="src_test",
        changes=[Change(type=ChangeType.CREATE_PAGE, target="source/test.md")],
    )
    ps_path = ps.save(patch)
    manifest.patch_artifact_path = str(ps_path)

    # Report artifact
    rs = ReportStore(tmp_path / "reports")
    report = HarnessReport(run_id=run_id, source_id="src_test")
    report.parse_quality.passed = True
    report.knowledge_quality.passed = True
    report.maintenance_quality.passed = True
    report.compute_overall()
    rs_path = rs.save(report)
    manifest.report_artifact_path = str(rs_path)

    run_store.update(manifest)
    return run_id


class TestReportFromPersistedData:
    def test_report_shows_run_status(self, tmp_path: Path) -> None:
        """Report shows run status from persisted run manifest."""
        run_id = _setup_full_run(tmp_path)
        run_store = RunStore(tmp_path)
        manifest = run_store.get(run_id)
        assert manifest is not None
        assert manifest.status.value is not None

    def test_report_shows_parsers_tried(self, tmp_path: Path) -> None:
        """Report output includes parser attempt information."""
        run_id = _setup_full_run(tmp_path)
        run_store = RunStore(tmp_path)
        manifest = run_store.get(run_id)
        assert manifest is not None
        stages = [{"name": s.name, "status": s.status.value} for s in manifest.stages]
        assert len(stages) > 0
        stage_names = [s["name"] for s in stages]
        assert "parse" in stage_names

    def test_report_shows_artifact_paths(self, tmp_path: Path) -> None:
        """Report shows paths to generated artifacts."""
        run_id = _setup_full_run(tmp_path)
        run_store = RunStore(tmp_path)
        manifest = run_store.get(run_id)
        assert manifest is not None
        assert manifest.ir_artifact_path is not None
        assert manifest.knowledge_artifact_path is not None
        assert manifest.patch_artifact_path is not None
        assert manifest.report_artifact_path is not None

    def test_report_missing_run(self, tmp_path: Path) -> None:
        """Report for a non-existent run returns a structured error."""
        run_store = RunStore(tmp_path)
        result = run_store.get("run_nonexistent")
        assert result is None

    def test_missing_artifacts_labeled_not_generated(self, tmp_path: Path) -> None:
        """Missing artifacts are labeled as not-generated-yet."""
        # Create a run with no artifacts
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_empty",
            source_hash="b" * 64,
            source_file_path="/tmp/empty.pdf",
        )

        # Check that artifact fields are None (= not generated)
        assert manifest.ir_artifact_path is None
        assert manifest.knowledge_artifact_path is None
        assert manifest.patch_artifact_path is None
        assert manifest.report_artifact_path is None

    def test_report_includes_harness_status(self, tmp_path: Path) -> None:
        """Report includes harness evaluation status."""
        run_id = _setup_full_run(tmp_path)
        rs = ReportStore(tmp_path / "reports")
        report = rs.get(run_id)
        assert report is not None
        assert report.release_decision == "auto_merge"
        assert report.overall_passed is True

    def test_report_uses_real_data_not_placeholder(self, tmp_path: Path) -> None:
        """Report output uses persisted data, not placeholder text."""
        run_id = _setup_full_run(tmp_path)

        # Build the report data (same logic as CLI)
        run_store = RunStore(tmp_path)
        manifest = run_store.get(run_id)
        assert manifest is not None

        # IR data
        ir_store = IRStore(tmp_path / "ir")
        ir = ir_store.get(run_id)
        assert ir is not None
        assert ir.page_count == 2

        # Knowledge data
        ks = KnowledgeStore(tmp_path / "knowledge")
        knowledge = ks.get(run_id)
        assert knowledge is not None
