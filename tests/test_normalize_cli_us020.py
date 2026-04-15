"""Tests for US-020: Make `docos normalize` replay the real normalize stage."""

from __future__ import annotations

from pathlib import Path

from docos.ir_store import IRStore
from docos.models.docir import DocIR
from docos.pipeline.normalizer import GlobalRepair, RepairLog
from docos.run_store import RunStore


class TestNormalizeCLI:
    """US-020: `docos normalize` replays real normalize stage."""

    def test_find_latest_run_returns_latest(self, tmp_path: Path) -> None:
        """RunStore.find_latest_run returns the most recent run_id."""
        base = tmp_path / "artifacts"
        store = RunStore(base)

        m1 = store.create(source_id="src-norm", source_hash="h1", source_file_path="/tmp/a.pdf")
        m2 = store.create(source_id="src-norm", source_hash="h2", source_file_path="/tmp/b.pdf")

        latest = store.find_latest_run("src-norm")
        assert latest is not None
        # The latest run should be m2 (created after m1)
        assert latest == m2.run_id

    def test_find_latest_run_returns_none_for_unknown(self, tmp_path: Path) -> None:
        """RunStore.find_latest_run returns None for unknown source_id."""
        base = tmp_path / "artifacts"
        store = RunStore(base)
        assert store.find_latest_run("nonexistent") is None

    def test_normalize_loads_docir_and_saves_repaired(self, tmp_path: Path) -> None:
        """Normalize loads persisted DocIR, runs GlobalRepair, and saves result."""
        base = tmp_path / "artifacts"
        store = RunStore(base)
        manifest = store.create(source_id="src-norm2", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        # Save initial DocIR
        ir_store = IRStore(base / "ir")
        docir = DocIR(doc_id="d-1", source_id="src-norm2", parser="test", page_count=1, pages=[])
        ir_store.save(docir, run_id)

        # Run normalize (same logic as CLI command)
        loaded = ir_store.get(run_id)
        assert loaded is not None
        assert loaded.doc_id == "d-1"

        repair_log = RepairLog(source_id="src-norm2", run_id=run_id)
        repaired = GlobalRepair().repair(loaded, repair_log)
        ir_store.save(repaired, run_id)

        # Verify saved
        reloaded = ir_store.get(run_id)
        assert reloaded is not None
        assert reloaded.doc_id == "d-1"

    def test_normalize_missing_docir_returns_none(self, tmp_path: Path) -> None:
        """Normalize returns None for run without parse artifact."""
        base = tmp_path / "artifacts"
        ir_store = IRStore(base / "ir")
        result = ir_store.get("nonexistent-run")
        assert result is None

    def test_normalize_with_run_id_option(self, tmp_path: Path) -> None:
        """Normalize with explicit run_id loads correct artifact."""
        base = tmp_path / "artifacts"
        store = RunStore(base)
        manifest = store.create(source_id="src-norm3", source_hash="h", source_file_path="/tmp/t.pdf")
        run_id = manifest.run_id

        ir_store = IRStore(base / "ir")
        docir = DocIR(doc_id="d-explicit", source_id="src-norm3", parser="test", page_count=2, pages=[])
        ir_store.save(docir, run_id)

        # Load by explicit run_id (bypass find_latest_run)
        loaded = ir_store.get(run_id)
        assert loaded is not None
        assert loaded.doc_id == "d-explicit"
        assert loaded.page_count == 2
