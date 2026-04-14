"""Tests for IR Store — DocIR artifact persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.ir_store import IRStore
from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.run import RunManifest, StageStatus
from docos.run_store import RunStore


def _make_docir(source_id: str = "src_test", page_count: int = 1) -> DocIR:
    """Create a minimal valid DocIR fixture."""
    blocks: list[Block] = []
    pages: list[Page] = []
    for i in range(1, page_count + 1):
        blocks.append(
            Block(
                block_id=f"blk_p{i}_1",
                page_no=i,
                block_type=BlockType.PARAGRAPH,
                reading_order=0,
                bbox=(0.0, 0.0, 100.0, 20.0),
                text_plain=f"Page {i} content",
                source_parser="test_parser",
                source_node_id=f"node_{i}",
            )
        )
        pages.append(
            Page(
                page_no=i,
                width=612.0,
                height=792.0,
                blocks=[f"blk_p{i}_1"],
            )
        )
    return DocIR(
        doc_id="doc_test",
        source_id=source_id,
        parser="test_parser",
        page_count=page_count,
        pages=pages,
        blocks=blocks,
    )


class TestIRStore:
    def test_save_and_retrieve(self, tmp_path: Path) -> None:
        store = IRStore(tmp_path / "ir")
        docir = _make_docir()
        path = store.save(docir, run_id="run_abc123")

        assert path.exists()
        loaded = store.get("run_abc123")
        assert loaded is not None
        assert loaded.doc_id == "doc_test"
        assert loaded.source_id == "src_test"
        assert loaded.page_count == 1

    def test_save_includes_run_id_metadata(self, tmp_path: Path) -> None:
        import json

        store = IRStore(tmp_path / "ir")
        docir = _make_docir()
        path = store.save(docir, run_id="run_meta_check")

        data = json.loads(path.read_text())
        assert data["_run_id"] == "run_meta_check"

    def test_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        store = IRStore(tmp_path / "ir")
        assert store.get("run_nonexistent") is None

    def test_exists(self, tmp_path: Path) -> None:
        store = IRStore(tmp_path / "ir")
        assert not store.exists("run_check")
        docir = _make_docir()
        store.save(docir, run_id="run_check")
        assert store.exists("run_check")

    def test_round_trip_preserves_blocks(self, tmp_path: Path) -> None:
        store = IRStore(tmp_path / "ir")
        docir = _make_docir(page_count=2)
        store.save(docir, run_id="run_round")

        loaded = store.get("run_round")
        assert loaded is not None
        assert len(loaded.blocks) == 2
        assert len(loaded.pages) == 2
        assert loaded.blocks[0].text_plain == "Page 1 content"

    def test_manifest_links_ir_artifact(self, tmp_path: Path) -> None:
        """Verify run manifest can store the IR artifact path."""
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_test",
            source_hash="a" * 64,
            source_file_path="/tmp/test.pdf",
        )

        ir_store = IRStore(tmp_path / "ir")
        docir = _make_docir(source_id="src_test")
        ir_path = ir_store.save(docir, run_id=manifest.run_id)

        # Link the artifact in the manifest
        manifest.ir_artifact_path = str(ir_path)
        run_store.update(manifest)

        # Reload and verify
        loaded = run_store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.ir_artifact_path == str(ir_path)

    def test_reload_after_new_process(self, tmp_path: Path) -> None:
        """Simulate process restart with a fresh IRStore."""
        store1 = IRStore(tmp_path / "ir")
        docir = _make_docir()
        store1.save(docir, run_id="run_restart")

        store2 = IRStore(tmp_path / "ir")
        loaded = store2.get("run_restart")
        assert loaded is not None
        assert loaded.doc_id == "doc_test"
