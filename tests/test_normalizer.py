"""Tests for Page-local normalizer, Global repair, and Repair logs."""

import pytest

from docos.models.docir import BlockType, DocIR, RelationType
from docos.pipeline.normalizer import (
    GlobalRepair,
    PageLocalNormalizer,
    RepairLog,
    RepairRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_block(
    block_id: str,
    page_no: int = 1,
    block_type: str = "paragraph",
    order: int = 0,
    text_plain: str = "",
    text_md: str = "",
    bbox: tuple[float, float, float, float] = (0, 0, 100, 50),
    **kwargs,
) -> dict:
    return {
        "block_id": block_id,
        "block_type": block_type,
        "reading_order": order,
        "bbox": bbox,
        "text_plain": text_plain,
        "text_md": text_md,
        "source_node_id": f"node_{block_id}",
        **kwargs,
    }


# ---------------------------------------------------------------------------
# Page-local normalizer tests
# ---------------------------------------------------------------------------

class TestPageLocalNormalizer:
    def test_basic_page_normalize(self) -> None:
        norm = PageLocalNormalizer()
        page_data = {
            "width": 612,
            "height": 792,
            "blocks": [
                make_block("b1", block_type="title", text_plain="Title", order=0),
                make_block("b2", block_type="paragraph", text_plain="Text", order=1),
            ],
        }
        page, blocks = norm.normalize_page(page_data, 1, "test_parser")
        assert page.page_no == 1
        assert len(blocks) == 2
        assert blocks[0].block_type == BlockType.TITLE
        assert blocks[0].text_plain == "Title"

    def test_unknown_block_preserved(self) -> None:
        norm = PageLocalNormalizer()
        page_data = {
            "blocks": [
                make_block("b1", block_type="weird_unknown_type"),
            ],
        }
        _, blocks = norm.normalize_page(page_data, 1, "test_parser")
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.UNKNOWN

    def test_empty_page(self) -> None:
        norm = PageLocalNormalizer()
        page, blocks = norm.normalize_page({}, 1, "test_parser")
        assert page.page_no == 1
        assert len(blocks) == 0

    def test_bbox_preserved(self) -> None:
        norm = PageLocalNormalizer()
        page_data = {
            "blocks": [make_block("b1", bbox=(10, 20, 300, 400))],
        }
        _, blocks = norm.normalize_page(page_data, 1, "test_parser")
        assert blocks[0].bbox == (10.0, 20.0, 300.0, 400.0)

    def test_reading_order_preserved(self) -> None:
        norm = PageLocalNormalizer()
        page_data = {
            "blocks": [
                make_block("b1", order=5),
                make_block("b2", order=3),
            ],
        }
        _, blocks = norm.normalize_page(page_data, 1, "test_parser")
        assert blocks[0].reading_order == 5
        assert blocks[1].reading_order == 3


# ---------------------------------------------------------------------------
# Global repair tests
# ---------------------------------------------------------------------------

class TestGlobalRepair:
    def _make_docir(self, blocks, pages=None, relations=None):
        from docos.models.docir import Block, Page as DocPage

        docir_blocks = []
        for b in blocks:
            if isinstance(b, Block):
                docir_blocks.append(b)
            else:
                docir_blocks.append(Block(
                    block_id=b.get("block_id", "b"),
                    page_no=b.get("page_no", 1),
                    block_type=BlockType(b.get("block_type", "paragraph")),
                    reading_order=b.get("order", 0),
                    bbox=b.get("bbox", (0, 0, 100, 50)),
                    text_plain=b.get("text_plain", ""),
                    text_md=b.get("text_md", ""),
                    source_parser=b.get("source_parser", "test"),
                    source_node_id=b.get("source_node_id", "n"),
                ))

        if pages is None:
            page_nos = sorted(set(b.page_no for b in docir_blocks))
            pages = [DocPage(page_no=p, width=612, height=792) for p in page_nos]

        return DocIR(
            doc_id="doc_test",
            source_id="src_test",
            parser="test",
            page_count=len(pages),
            pages=pages,
            blocks=docir_blocks,
            relations=relations or [],
        )

    def test_cross_page_continuation(self) -> None:
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = self._make_docir([
            {"block_id": "p1_last", "page_no": 1, "block_type": "paragraph", "order": 0, "text_plain": "End of page 1..."},
            {"block_id": "p2_first", "page_no": 2, "block_type": "paragraph", "order": 0, "text_plain": "...continuation on page 2"},
        ])

        result = repair.repair(docir, log)
        rel_types = {r.relation_type for r in result.relations}
        assert RelationType.CONTINUED_TO in rel_types
        assert RelationType.CONTINUED_FROM in rel_types

    def test_cross_page_table_continuation(self) -> None:
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = self._make_docir([
            {"block_id": "t1", "page_no": 1, "block_type": "table", "order": 0},
            {"block_id": "t2", "page_no": 2, "block_type": "table", "order": 0},
        ])

        result = repair.repair(docir, log)
        assert any(r.relation_type == RelationType.CONTINUED_TO for r in result.relations)

    def test_heading_hierarchy_shift(self) -> None:
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = self._make_docir([
            {"block_id": "h1", "block_type": "heading", "order": 0, "text_md": "### Section"},
            {"block_id": "p1", "block_type": "paragraph", "order": 1, "text_md": "Text"},
        ])

        result = repair.repair(docir, log)
        # Should have shifted heading from ### to #
        heading = [b for b in result.blocks if b.block_type == BlockType.HEADING][0]
        assert heading.text_md == "# Section"
        assert log.count >= 1

    def test_repeated_footer_removal(self) -> None:
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = self._make_docir([
            {"block_id": "f1", "page_no": 1, "block_type": "footer", "order": 99, "text_plain": "Confidential"},
            {"block_id": "p1", "page_no": 1, "block_type": "paragraph", "order": 0, "text_plain": "Content"},
            {"block_id": "f2", "page_no": 2, "block_type": "footer", "order": 99, "text_plain": "Confidential"},
            {"block_id": "p2", "page_no": 2, "block_type": "paragraph", "order": 0, "text_plain": "More content"},
        ])

        result = repair.repair(docir, log)
        footers = [b for b in result.blocks if b.block_type == BlockType.FOOTER]
        assert len(footers) == 0
        assert any(r.repair_type == "repeated_header_footer_removal" for r in log.repairs)

    def test_caption_attachment(self) -> None:
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = self._make_docir([
            {"block_id": "fig1", "page_no": 1, "block_type": "figure", "order": 0, "bbox": (0, 0, 200, 200)},
            {"block_id": "cap1", "page_no": 1, "block_type": "caption", "order": 1, "bbox": (0, 210, 200, 230), "text_plain": "Figure 1: Test"},
        ])

        result = repair.repair(docir, log)
        caption_rels = [r for r in result.relations if r.relation_type == RelationType.CAPTION_OF]
        assert len(caption_rels) >= 1

    def test_no_modification_when_clean(self) -> None:
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = self._make_docir([
            {"block_id": "b1", "block_type": "paragraph", "order": 0, "text_plain": "Clean text"},
        ])

        result = repair.repair(docir, log)
        assert len(result.blocks) == 1
        assert result.blocks[0].text_plain == "Clean text"


# ---------------------------------------------------------------------------
# Repair log tests
# ---------------------------------------------------------------------------

class TestRepairLog:
    def test_empty_log(self) -> None:
        log = RepairLog(source_id="src_test", run_id="run_test")
        assert log.count == 0

    def test_add_repair(self) -> None:
        log = RepairLog(source_id="src_test", run_id="run_test")
        log.add(RepairRecord(
            repair_type="heading_fix",
            before="### Title",
            after="# Title",
            reason="Hierarchy shift",
            confidence=0.9,
            performed_by="rule",
        ))
        assert log.count == 1
        assert log.repairs[0].repair_type == "heading_fix"

    def test_repair_record_defaults(self) -> None:
        r = RepairRecord(repair_type="test")
        assert r.confidence == 1.0
        assert r.performed_by == "rule"
        assert r.repair_id.startswith("repair_")

    def test_multiple_repairs(self) -> None:
        log = RepairLog(source_id="src_test", run_id="run_test")
        for i in range(5):
            log.add(RepairRecord(repair_type=f"repair_{i}"))
        assert log.count == 5

    def test_serialization(self) -> None:
        log = RepairLog(source_id="src_test", run_id="run_test")
        log.add(RepairRecord(repair_type="test", before="a", after="b"))
        json_str = log.model_dump_json()
        assert "repair_" in json_str
