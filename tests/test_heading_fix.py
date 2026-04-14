"""Tests for US-016: fix heading hierarchy shift logic."""

from __future__ import annotations

from docos.models.docir import Block, BlockType, DocIR, Page
from docos.pipeline.normalizer import GlobalRepair, RepairLog


def _make_heading_docir(heading_levels: list[int]) -> DocIR:
    """Create a DocIR with headings at the given levels."""
    blocks: list[Block] = []
    block_ids: list[str] = []
    for i, level in enumerate(heading_levels):
        bid = f"blk_h{i}"
        hashes = "#" * level
        blocks.append(
            Block(
                block_id=bid, page_no=1, block_type=BlockType.HEADING,
                reading_order=i, bbox=(0, 0, 500, 30),
                text_md=f"{hashes} Heading {i}",
                text_plain=f"Heading {i}",
                source_parser="test", source_node_id=f"n{i}",
            )
        )
        block_ids.append(bid)
    return DocIR(
        doc_id="doc_h", source_id="src", parser="test",
        page_count=1,
        pages=[Page(page_no=1, width=612.0, height=792.0, blocks=block_ids)],
        blocks=blocks,
    )


def _heading_level(md: str) -> int:
    """Extract heading level from markdown text."""
    count = 0
    for ch in md.lstrip():
        if ch == "#":
            count += 1
        else:
            break
    return count


class TestHeadingHierarchyShift:
    def test_preserves_relative_spacing(self) -> None:
        """Heading normalization preserves relative levels."""
        # Headings at levels 3, 4, 5 → should become 1, 2, 3
        docir = _make_heading_docir([3, 4, 5])
        repair_log = RepairLog(source_id="src", run_id="run_1")
        repaired = GlobalRepair().repair(docir, repair_log)

        headings = [b for b in repaired.blocks if b.block_type == BlockType.HEADING]
        levels = [_heading_level(b.text_md) for b in headings]
        assert levels == [1, 2, 3]

    def test_shifts_correctly_for_level_2_start(self) -> None:
        """Headings starting at level 2 shift to start at 1."""
        docir = _make_heading_docir([2, 2, 3])
        repair_log = RepairLog(source_id="src", run_id="run_2")
        repaired = GlobalRepair().repair(docir, repair_log)

        headings = [b for b in repaired.blocks if b.block_type == BlockType.HEADING]
        levels = [_heading_level(b.text_md) for b in headings]
        assert levels == [1, 1, 2]

    def test_no_shift_when_starts_at_level_1(self) -> None:
        """Headings already starting at level 1 are unchanged."""
        docir = _make_heading_docir([1, 2, 3])
        repair_log = RepairLog(source_id="src", run_id="run_3")
        repaired = GlobalRepair().repair(docir, repair_log)

        headings = [b for b in repaired.blocks if b.block_type == BlockType.HEADING]
        levels = [_heading_level(b.text_md) for b in headings]
        assert levels == [1, 2, 3]

    def test_no_unreachable_return(self) -> None:
        """The unreachable return path in heading normalization is removed."""
        import inspect
        source = inspect.getsource(GlobalRepair._normalize_heading_hierarchy)
        # Should not have a dangling "return blocks" after the main return
        lines = source.strip().split("\n")
        # Check that the last meaningful line isn't a duplicate return
        assert not any(
            "return blocks" in line and i > 0
            for i, line in enumerate(lines)
            if i == len(lines) - 1
        )

    def test_shift_heading_level_method(self) -> None:
        """Test the _shift_heading_level helper directly."""
        assert GlobalRepair._shift_heading_level("### Title", 2) == "# Title"
        assert GlobalRepair._shift_heading_level("#### Deep", 3) == "# Deep"
        assert GlobalRepair._shift_heading_level("## Mid", 1) == "# Mid"
        assert GlobalRepair._shift_heading_level("# Already One", 0) == "# Already One"

    def test_heading_text_preserved(self) -> None:
        """Heading text content is preserved after shift."""
        docir = _make_heading_docir([3, 5])
        repair_log = RepairLog(source_id="src", run_id="run_text")
        repaired = GlobalRepair().repair(docir, repair_log)

        headings = [b for b in repaired.blocks if b.block_type == BlockType.HEADING]
        assert "Heading 0" in headings[0].text_md
        assert "Heading 1" in headings[1].text_md
