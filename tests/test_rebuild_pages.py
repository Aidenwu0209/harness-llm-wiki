"""Tests for US-015: rebuild page state after global repair."""

from __future__ import annotations

from docos.models.docir import (
    Block,
    BlockType,
    DocIR,
    Page,
)
from docos.pipeline.invariants import validate_docir
from docos.pipeline.normalizer import GlobalRepair, RepairLog


def _make_two_page_docir(with_repeated_footer: bool = False) -> DocIR:
    """Create a 2-page DocIR fixture."""
    blocks = [
        Block(
            block_id="blk_h1", page_no=1, block_type=BlockType.HEADING,
            reading_order=0, bbox=(0, 0, 500, 30), text_md="## Section One",
            text_plain="Section One", source_parser="test", source_node_id="n1",
        ),
        Block(
            block_id="blk_p1", page_no=1, block_type=BlockType.PARAGRAPH,
            reading_order=1, bbox=(0, 40, 500, 80), text_plain="Paragraph 1",
            source_parser="test", source_node_id="n2",
        ),
        Block(
            block_id="blk_p2", page_no=2, block_type=BlockType.PARAGRAPH,
            reading_order=0, bbox=(0, 0, 500, 40), text_plain="Paragraph 2",
            source_parser="test", source_node_id="n3",
        ),
    ]
    pages = [
        Page(page_no=1, width=612.0, height=792.0, blocks=["blk_h1", "blk_p1"]),
        Page(page_no=2, width=612.0, height=792.0, blocks=["blk_p2"]),
    ]
    if with_repeated_footer:
        blocks.append(
            Block(
                block_id="blk_f1", page_no=1, block_type=BlockType.FOOTER,
                reading_order=2, bbox=(0, 750, 500, 780), text_plain="Page footer",
                source_parser="test", source_node_id="nf1",
            )
        )
        blocks.append(
            Block(
                block_id="blk_f2", page_no=2, block_type=BlockType.FOOTER,
                reading_order=1, bbox=(0, 750, 500, 780), text_plain="Page footer",
                source_parser="test", source_node_id="nf2",
            )
        )
        pages[0] = Page(page_no=1, width=612.0, height=792.0, blocks=["blk_h1", "blk_p1", "blk_f1"])
        pages[1] = Page(page_no=2, width=612.0, height=792.0, blocks=["blk_p2", "blk_f2"])

    return DocIR(
        doc_id="doc_test", source_id="src_test", parser="test",
        page_count=2, pages=pages, blocks=blocks,
    )


class TestRebuildPageState:
    def test_removed_blocks_not_in_pages(self) -> None:
        """Removed blocks do not remain in any Page.blocks after repair."""
        docir = _make_two_page_docir(with_repeated_footer=True)
        repair_log = RepairLog(source_id="src_test", run_id="run_1")
        repaired = GlobalRepair().repair(docir, repair_log)

        # The repeated footer blocks should have been removed
        all_block_ids = {b.block_id for b in repaired.blocks}
        for page in repaired.pages:
            for bid in page.blocks:
                assert bid in all_block_ids, f"Stale block {bid} in page {page.page_no}"

    def test_pages_blocks_rebuilt_from_repaired_set(self) -> None:
        """Page.blocks references match exactly the blocks in the repaired set."""
        docir = _make_two_page_docir()
        repair_log = RepairLog(source_id="src_test", run_id="run_1")
        repaired = GlobalRepair().repair(docir, repair_log)

        # All blocks in pages should exist in the block list
        blocks_by_page = {}
        for b in repaired.blocks:
            blocks_by_page.setdefault(b.page_no, []).append(b.block_id)

        for page in repaired.pages:
            expected = blocks_by_page.get(page.page_no, [])
            assert page.blocks == expected

    def test_page_warnings_preserved(self) -> None:
        """Page-level warnings are preserved during rebuild."""
        from docos.models.docir import PageWarning
        docir = DocIR(
            doc_id="doc_w", source_id="src", parser="test",
            page_count=1,
            pages=[Page(
                page_no=1, width=612.0, height=792.0,
                blocks=["blk_1"],
                warnings=[PageWarning(code="low_confidence", message="Test warning")],
            )],
            blocks=[
                Block(block_id="blk_1", page_no=1, block_type=BlockType.PARAGRAPH,
                      reading_order=0, bbox=(0, 0, 100, 20), text_plain="X",
                      source_parser="test", source_node_id="n1"),
            ],
        )
        repair_log = RepairLog(source_id="src", run_id="run_w")
        repaired = GlobalRepair().repair(docir, repair_log)
        assert len(repaired.pages[0].warnings) == 1
        assert repaired.pages[0].warnings[0].code == "low_confidence"

    def test_reading_order_version_preserved(self) -> None:
        """reading_order_version is preserved during rebuild."""
        docir = DocIR(
            doc_id="doc_ro", source_id="src", parser="test",
            page_count=1,
            pages=[Page(page_no=1, width=612.0, height=792.0, blocks=["blk_1"])],
            blocks=[
                Block(block_id="blk_1", page_no=1, block_type=BlockType.PARAGRAPH,
                      reading_order=0, bbox=(0, 0, 100, 20), text_plain="X",
                      source_parser="test", source_node_id="n1"),
            ],
        )
        repair_log = RepairLog(source_id="src", run_id="run_ro")
        repaired = GlobalRepair().repair(docir, repair_log)
        assert repaired.pages[0].reading_order_version == "1"

    def test_repaired_docir_passes_invariants(self) -> None:
        """A repaired DocIR passes the full invariant validator."""
        docir = _make_two_page_docir(with_repeated_footer=True)
        repair_log = RepairLog(source_id="src_test", run_id="run_inv")
        repaired = GlobalRepair().repair(docir, repair_log)
        report = validate_docir(repaired)
        assert report.passed, [e.message for e in report.errors]
