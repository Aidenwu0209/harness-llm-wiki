"""Tests for Canonical DocIR schema."""

import pytest
from pydantic import ValidationError

from docos.models.docir import (
    Block,
    BlockType,
    BBox,
    Citation,
    DocIR,
    DocIRWarning,
    Page,
    PageWarning,
    Relation,
    RelationType,
    TableCell,
)


# ---------------------------------------------------------------------------
# Block tests
# ---------------------------------------------------------------------------

class TestBlock:
    def test_minimal_block(self) -> None:
        b = Block(
            block_id="b1",
            page_no=1,
            block_type=BlockType.TITLE,
            reading_order=0,
            bbox=(0.0, 0.0, 100.0, 50.0),
            source_parser="test_parser",
            source_node_id="n1",
        )
        assert b.block_id == "b1"
        assert b.confidence == 1.0
        assert b.text_plain == ""

    def test_invalid_bbox(self) -> None:
        with pytest.raises(ValidationError, match="Invalid bbox"):
            Block(
                block_id="b1",
                page_no=1,
                block_type=BlockType.PARAGRAPH,
                reading_order=0,
                bbox=(100.0, 100.0, 50.0, 50.0),  # x1 < x0
                source_parser="p",
                source_node_id="n1",
            )

    def test_confidence_range(self) -> None:
        with pytest.raises(ValidationError):
            Block(
                block_id="b1",
                page_no=1,
                block_type=BlockType.PARAGRAPH,
                reading_order=0,
                bbox=(0, 0, 10, 10),
                confidence=1.5,
                source_parser="p",
                source_node_id="n1",
            )

    def test_table_cells(self) -> None:
        b = Block(
            block_id="t1",
            page_no=1,
            block_type=BlockType.TABLE,
            reading_order=0,
            bbox=(0, 0, 500, 300),
            source_parser="p",
            source_node_id="n1",
            table_cells=[
                TableCell(row=0, col=0, text_plain="Header", is_header=True),
                TableCell(row=1, col=0, text_plain="Data"),
            ],
        )
        assert b.table_cells is not None
        assert len(b.table_cells) == 2
        assert b.table_cells[0].is_header is True

    def test_all_block_types(self) -> None:
        for bt in BlockType:
            b = Block(
                block_id=f"test_{bt.value}",
                page_no=1,
                block_type=bt,
                reading_order=0,
                bbox=(0, 0, 10, 10),
                source_parser="p",
                source_node_id="n1",
            )
            assert b.block_type == bt


# ---------------------------------------------------------------------------
# Page tests
# ---------------------------------------------------------------------------

class TestPage:
    def test_minimal_page(self) -> None:
        p = Page(page_no=1, width=612, height=792)
        assert p.page_no == 1
        assert p.rotation == 0.0
        assert p.blocks == []

    def test_page_with_warnings(self) -> None:
        p = Page(
            page_no=1,
            width=612,
            height=792,
            warnings=[PageWarning(code="OCR_LOW_CONF", message="Low OCR confidence", severity="medium")],
        )
        assert len(p.warnings) == 1


# ---------------------------------------------------------------------------
# Relation tests
# ---------------------------------------------------------------------------

class TestRelation:
    def test_all_relation_types(self) -> None:
        for rt in RelationType:
            r = Relation(
                relation_id=f"r_{rt.value}",
                relation_type=rt,
                source_block_id="b1",
                target_block_id="b2",
            )
            assert r.relation_type == rt


# ---------------------------------------------------------------------------
# DocIR tests
# ---------------------------------------------------------------------------

class TestDocIR:
    def _make_block(self, block_id: str, page_no: int = 1, order: int = 0) -> Block:
        return Block(
            block_id=block_id,
            page_no=page_no,
            block_type=BlockType.PARAGRAPH,
            reading_order=order,
            bbox=(0, 0, 100, 50),
            text_plain=f"Content of {block_id}",
            source_parser="test_parser",
            source_node_id=f"node_{block_id}",
        )

    def test_minimal_docir(self) -> None:
        d = DocIR(
            doc_id="doc_001",
            source_id="src_001",
            parser="fast_text_route",
            page_count=0,
        )
        assert d.schema_version == "1"
        assert d.confidence == 1.0
        assert d.pages == []

    def test_docir_with_pages_and_blocks(self) -> None:
        b1 = self._make_block("p1_b1", page_no=1, order=0)
        b2 = self._make_block("p1_b2", page_no=1, order=1)
        p1 = Page(page_no=1, width=612, height=792, blocks=["p1_b1", "p1_b2"])

        d = DocIR(
            doc_id="doc_002",
            source_id="src_002",
            parser="complex_pdf_route",
            page_count=1,
            pages=[p1],
            blocks=[b1, b2],
        )
        assert len(d.pages) == 1
        assert len(d.blocks) == 2

    def test_duplicate_block_ids_rejected(self) -> None:
        b1 = self._make_block("dup_id")
        b2 = self._make_block("dup_id")  # same ID
        with pytest.raises(ValidationError, match="Duplicate block_id"):
            DocIR(
                doc_id="doc_003",
                source_id="src_003",
                parser="test",
                page_count=1,
                blocks=[b1, b2],
            )

    def test_docir_with_relations_and_warnings(self) -> None:
        b1 = self._make_block("b1")
        b2 = self._make_block("b2")

        rel = Relation(
            relation_id="r1",
            relation_type=RelationType.CAPTION_OF,
            source_block_id="b1",
            target_block_id="b2",
        )

        warn = DocIRWarning(code="CROSS_PAGE_TABLE", message="Table spans pages 2-3", severity="high")

        d = DocIR(
            doc_id="doc_004",
            source_id="src_004",
            parser="complex_pdf_route",
            page_count=5,
            blocks=[b1, b2],
            relations=[rel],
            warnings=[warn],
            confidence=0.85,
        )
        assert len(d.relations) == 1
        assert len(d.warnings) == 1
        assert d.confidence == 0.85

    def test_full_example(self) -> None:
        """Replicate the example from requirements.md section 38.1."""
        title_block = Block(
            block_id="p1_b1",
            page_no=1,
            block_type=BlockType.TITLE,
            reading_order=1,
            bbox=[120, 180, 2140, 340],
            parent_id=None,
            children_ids=[],
            text_plain="READOC: A Benchmark for End-to-End Document Structure Extraction",
            text_md="READOC: A Benchmark for End-to-End Document Structure Extraction",
            confidence=0.99,
            source_parser="parser_a",
            source_node_id="node_001",
        )

        page1 = Page(
            page_no=1,
            width=2480,
            height=3508,
            rotation=0,
            ocr_used=False,
            blocks=["p1_b1"],
        )

        doc = DocIR(
            doc_id="doc.readoc.2025",
            source_id="src_0001",
            parser="complex_pdf_route.primary",
            parser_version="1.2.0",
            schema_version="1",
            page_count=2,
            pages=[page1],
            blocks=[title_block],
            relations=[],
            warnings=[],
        )
        assert doc.doc_id == "doc.readoc.2025"
        assert doc.blocks[0].block_type == BlockType.TITLE
        assert doc.pages[0].blocks == ["p1_b1"]
