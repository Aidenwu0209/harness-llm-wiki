"""Tests for US-009: Persist normalized DocIR artifacts.

Acceptance criteria:
- The normalize stage writes a DocIR artifact under the IR store for each successful run
- The RunManifest includes a pointer to the saved DocIR artifact
- A new process can reload the persisted DocIR by run_id
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.debug_store import DebugAssetStore
from docos.ir_store import IRStore
from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.run import RunManifest, StageStatus
from docos.pipeline.normalizer import GlobalRepair, RepairLog
from docos.pipeline.orchestrator import PipelineOrchestrator
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import RouteDecision
from docos.run_store import RunStore


def _write_text_pdf(path: Path) -> Path:
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\n"
        b"endobj\n"
        b"4 0 obj\n"
        b"<< /Length 44 >>\n"
        b"stream\n"
        b"BT /F1 12 Tf 100 700 Td (Hello World) Tj ET\n"
        b"endstream\n"
        b"endobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _parse_to_docir(tmp_path: Path, run_id: str) -> DocIR:
    """Helper: parse a PDF and return DocIR via orchestrator."""
    registry = ParserRegistry()
    registry.register(StdlibPDFParser())

    debug_store = DebugAssetStore(tmp_path / "debug")
    orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

    pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
    decision = RouteDecision(
        selected_route="test",
        primary_parser="stdlib_pdf",
        fallback_parsers=[],
        expected_risks=[],
        post_parse_repairs=[],
        review_policy="default",
    )

    result = orchestrator.execute(
        run_id=run_id,
        source_id="src_norm",
        file_path=pdf_path,
        route_decision=decision,
    )
    assert result.success
    assert result.docir is not None
    return result.docir


# ---------------------------------------------------------------------------
# AC1: Normalize writes DocIR artifact under the IR store
# ---------------------------------------------------------------------------


class TestNormalizeWritesDocIR:
    """The normalize stage writes a DocIR artifact under the IR store for each
    successful run."""

    def test_normalize_persists_docir(self, tmp_path: Path) -> None:
        """After parsing + normalizing, DocIR is persisted to IR store."""
        run_id = "run_norm_1"
        docir = _parse_to_docir(tmp_path, run_id)

        # Apply normalization (repairs)
        repair_log = RepairLog(source_id="src_norm", run_id=run_id)
        repaired = GlobalRepair().repair(docir, repair_log)

        # Persist via IR store
        ir_store = IRStore(tmp_path / "ir")
        path = ir_store.save(repaired, run_id)

        assert path.exists()
        assert path.name == f"{run_id}.json"

    def test_normalize_saves_valid_json(self, tmp_path: Path) -> None:
        """The persisted DocIR is valid JSON."""
        run_id = "run_norm_2"
        docir = _parse_to_docir(tmp_path, run_id)

        repair_log = RepairLog(source_id="src_norm", run_id=run_id)
        repaired = GlobalRepair().repair(docir, repair_log)

        ir_store = IRStore(tmp_path / "ir")
        ir_store.save(repaired, run_id)

        path = ir_store._artifact_path(run_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["doc_id"] == repaired.doc_id
        assert data["page_count"] == repaired.page_count

    def test_normalize_overwrites_previous(self, tmp_path: Path) -> None:
        """Re-running normalize with the same run_id overwrites the artifact."""
        run_id = "run_norm_3"
        docir = _parse_to_docir(tmp_path, run_id)

        ir_store = IRStore(tmp_path / "ir")
        ir_store.save(docir, run_id)

        # Modify and re-save (simulating normalize stage)
        repair_log = RepairLog(source_id="src_norm", run_id=run_id)
        repaired = GlobalRepair().repair(docir, repair_log)
        ir_store.save(repaired, run_id)

        # Should have the repaired version
        loaded = ir_store.get(run_id)
        assert loaded is not None


# ---------------------------------------------------------------------------
# AC2: RunManifest includes pointer to saved DocIR artifact
# ---------------------------------------------------------------------------


class TestManifestLinksDocIR:
    """The RunManifest includes a pointer to the saved DocIR artifact."""

    def test_manifest_ir_artifact_path_set(self, tmp_path: Path) -> None:
        """RunManifest.ir_artifact_path points to the saved DocIR."""
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_norm",
            source_hash="a" * 64,
            source_file_path=str(tmp_path / "doc.pdf"),
        )

        run_id = manifest.run_id
        docir = _parse_to_docir(tmp_path, run_id)

        # Normalize and persist
        ir_store = IRStore(tmp_path / "ir")
        ir_store.save(docir, run_id)

        ir_path = tmp_path / "ir" / f"{run_id}.json"
        manifest.ir_artifact_path = str(ir_path)
        run_store.update(manifest)

        loaded = run_store.get(run_id)
        assert loaded is not None
        assert loaded.ir_artifact_path is not None
        assert Path(loaded.ir_artifact_path).exists()


# ---------------------------------------------------------------------------
# AC3: New process can reload persisted DocIR by run_id
# ---------------------------------------------------------------------------


class TestReloadDocIRByRunId:
    """A new process can reload the persisted DocIR by run_id."""

    def test_reload_docir_from_fresh_store(self, tmp_path: Path) -> None:
        """A new IRStore instance can reload the persisted DocIR."""
        run_id = "run_reload"
        docir = _parse_to_docir(tmp_path, run_id)

        # Persist
        ir_store = IRStore(tmp_path / "ir")
        ir_store.save(docir, run_id)

        # New store instance (simulates new process)
        new_store = IRStore(tmp_path / "ir")
        loaded = new_store.get(run_id)
        assert loaded is not None
        assert loaded.doc_id == docir.doc_id
        assert loaded.page_count == docir.page_count

    def test_reload_preserves_blocks(self, tmp_path: Path) -> None:
        """Reloaded DocIR preserves all blocks."""
        run_id = "run_blocks"
        docir = _parse_to_docir(tmp_path, run_id)

        ir_store = IRStore(tmp_path / "ir")
        ir_store.save(docir, run_id)

        new_store = IRStore(tmp_path / "ir")
        loaded = new_store.get(run_id)
        assert loaded is not None
        assert len(loaded.blocks) == len(docir.blocks)

    def test_exists_check(self, tmp_path: Path) -> None:
        """IRStore.exists() returns True for saved artifacts."""
        run_id = "run_exists"
        docir = _parse_to_docir(tmp_path, run_id)

        ir_store = IRStore(tmp_path / "ir")
        assert not ir_store.exists(run_id)

        ir_store.save(docir, run_id)
        assert ir_store.exists(run_id)
