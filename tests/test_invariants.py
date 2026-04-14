"""Tests for US-013: DocIR page, block, and relation invariant validation."""

from __future__ import annotations

import pytest

from docos.models.docir import (
    Block,
    BlockType,
    DocIR,
    Page,
    Relation,
    RelationType,
)
from docos.pipeline.invariants import InvariantReport, validate_docir


def _make_valid_docir(page_count: int = 1) -> DocIR:
    """Create a valid DocIR fixture."""
    blocks: list[Block] = []
    pages: list[Page] = []
    for p in range(1, page_count + 1):
        bid = f"blk_p{p}_0"
        blocks.append(
            Block(
                block_id=bid, page_no=p, block_type=BlockType.PARAGRAPH,
                reading_order=0, bbox=(0.0, 0.0, 100.0, 20.0),
                text_plain=f"Page {p}", source_parser="test", source_node_id=f"n{p}",
            )
        )
        pages.append(Page(page_no=p, width=612.0, height=792.0, blocks=[bid]))
    return DocIR(
        doc_id="doc_valid", source_id="src_test", parser="test",
        page_count=page_count, pages=pages, blocks=blocks,
    )


class TestDocIRInvariants:
    def test_valid_docir_passes(self) -> None:
        docir = _make_valid_docir(page_count=2)
        report = validate_docir(docir)
        assert report.passed, [e.message for e in report.errors]

    def test_rejects_duplicate_block_ids(self) -> None:
        blocks = [
            Block(block_id="blk_dup", page_no=1, block_type=BlockType.PARAGRAPH,
                  reading_order=0, bbox=(0, 0, 100, 20), text_plain="A",
                  source_parser="test", source_node_id="n1"),
            Block(block_id="blk_dup", page_no=1, block_type=BlockType.HEADING,
                  reading_order=1, bbox=(0, 0, 100, 20), text_plain="B",
                  source_parser="test", source_node_id="n2"),
        ]
        # Use model_construct to bypass Pydantic's own unique validator
        docir = DocIR.model_construct(
            doc_id="doc_dup", source_id="src", parser="test",
            page_count=1,
            pages=[Page(page_no=1, width=612.0, height=792.0, blocks=["blk_dup"])],
            blocks=blocks,
            relations=[],
            warnings=[],
        )
        report = validate_docir(docir)
        assert not report.passed
        codes = [e.code for e in report.errors]
        assert "duplicate_block_id" in codes

    def test_rejects_invalid_page_block_refs(self) -> None:
        """Page references non-existent block_id."""
        docir = DocIR(
            doc_id="doc_inv", source_id="src", parser="test",
            page_count=1,
            pages=[Page(page_no=1, width=612.0, height=792.0, blocks=["blk_missing"])],
            blocks=[
                Block(block_id="blk_real", page_no=1, block_type=BlockType.PARAGRAPH,
                      reading_order=0, bbox=(0, 0, 100, 20), text_plain="Real",
                      source_parser="test", source_node_id="n1"),
            ],
        )
        report = validate_docir(docir)
        assert not report.passed
        codes = [e.code for e in report.errors]
        assert "invalid_page_block_ref" in codes
        # Error should include block_id
        ref_err = [e for e in report.errors if e.code == "invalid_page_block_ref"][0]
        assert ref_err.block_id == "blk_missing"
        assert ref_err.page_no == 1

    def test_rejects_duplicate_reading_order(self) -> None:
        """Two blocks on the same page with same reading_order."""
        docir = DocIR(
            doc_id="doc_ord", source_id="src", parser="test",
            page_count=1,
            pages=[Page(page_no=1, width=612.0, height=792.0, blocks=["blk_a", "blk_b"])],
            blocks=[
                Block(block_id="blk_a", page_no=1, block_type=BlockType.PARAGRAPH,
                      reading_order=0, bbox=(0, 0, 100, 20), text_plain="A",
                      source_parser="test", source_node_id="n1"),
                Block(block_id="blk_b", page_no=1, block_type=BlockType.PARAGRAPH,
                      reading_order=0, bbox=(0, 30, 100, 50), text_plain="B",
                      source_parser="test", source_node_id="n2"),
            ],
        )
        report = validate_docir(docir)
        assert not report.passed
        codes = [e.code for e in report.errors]
        assert "duplicate_reading_order" in codes

    def test_rejects_invalid_relation_refs(self) -> None:
        """Relation references non-existent blocks."""
        docir = DocIR(
            doc_id="doc_rel", source_id="src", parser="test",
            page_count=1,
            pages=[Page(page_no=1, width=612.0, height=792.0, blocks=["blk_1"])],
            blocks=[
                Block(block_id="blk_1", page_no=1, block_type=BlockType.PARAGRAPH,
                      reading_order=0, bbox=(0, 0, 100, 20), text_plain="X",
                      source_parser="test", source_node_id="n1"),
            ],
            relations=[
                Relation(
                    relation_id="rel_bad", relation_type=RelationType.CAPTION_OF,
                    source_block_id="blk_1", target_block_id="blk_nonexistent",
                ),
            ],
        )
        report = validate_docir(docir)
        assert not report.passed
        codes = [e.code for e in report.errors]
        assert "invalid_relation_target" in codes

    def test_rejects_page_count_mismatch(self) -> None:
        """page_count doesn't match actual number of pages."""
        docir = DocIR(
            doc_id="doc_cnt", source_id="src", parser="test",
            page_count=3,  # Wrong
            pages=[Page(page_no=1, width=612.0, height=792.0, blocks=[])],
            blocks=[],
        )
        report = validate_docir(docir)
        assert not report.passed
        codes = [e.code for e in report.errors]
        assert "page_count_mismatch" in codes

    def test_errors_include_page_or_block_info(self) -> None:
        """Validation errors include page_no or block_id in the message."""
        docir = DocIR(
            doc_id="doc_info", source_id="src", parser="test",
            page_count=1,
            pages=[Page(page_no=1, width=612.0, height=792.0, blocks=["blk_ghost"])],
            blocks=[],
        )
        report = validate_docir(docir)
        assert not report.passed
        for err in report.errors:
            if err.code == "invalid_page_block_ref":
                assert err.page_no == 1
                assert err.block_id == "blk_ghost"
                assert "1" in err.message or "blk_ghost" in err.message
