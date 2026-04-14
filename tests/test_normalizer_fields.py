"""Tests for US-014: preserve structured block fields during page-local normalization."""

from __future__ import annotations

from typing import Any

import pytest

from docos.models.docir import Block, BlockType, TableCell
from docos.pipeline.normalizer import NormalizationError, PageLocalNormalizer


def _raw_block(**overrides: Any) -> dict[str, Any]:
    """Create a minimal raw parser block dict."""
    base = {
        "block_id": "blk_1",
        "block_type": "paragraph",
        "bbox": [10.0, 20.0, 100.0, 40.0],
        "text_plain": "Hello world",
        "reading_order": 0,
    }
    base.update(overrides)
    return base


class TestPreserveStructuredFields:
    def test_table_cells_preserved(self) -> None:
        """Normalization maps table_cells into canonical blocks."""
        cells = [
            {"row": 0, "col": 0, "text_plain": "A", "is_header": True},
            {"row": 0, "col": 1, "text_plain": "B", "is_header": True},
            {"row": 1, "col": 0, "text_plain": "1"},
            {"row": 1, "col": 1, "text_plain": "2"},
        ]
        raw = _raw_block(block_type="table", table_cells=cells)
        normalizer = PageLocalNormalizer()
        page, blocks = normalizer.normalize_page(
            {"blocks": [raw], "width": 612.0, "height": 792.0},
            page_no=1,
            parser_name="test_parser",
        )
        assert len(blocks) == 1
        assert blocks[0].table_cells is not None
        assert len(blocks[0].table_cells) == 4
        assert blocks[0].table_cells[0].is_header is True
        assert blocks[0].table_cells[2].text_plain == "1"

    def test_footnote_refs_preserved(self) -> None:
        """Normalization maps footnote_refs into canonical blocks."""
        raw = _raw_block(footnote_refs=["fn_1", "fn_2"])
        normalizer = PageLocalNormalizer()
        page, blocks = normalizer.normalize_page(
            {"blocks": [raw], "width": 612.0, "height": 792.0},
            page_no=1,
            parser_name="test_parser",
        )
        assert blocks[0].footnote_refs == ["fn_1", "fn_2"]

    def test_citations_preserved(self) -> None:
        """Normalization maps citations into canonical blocks."""
        citations = [
            {"ref_id": "ref_1", "ref_text": "[1]", "ref_type": "internal"},
            {"ref_id": "ref_2", "ref_text": "Smith 2024", "ref_type": "external"},
        ]
        raw = _raw_block(citations=citations)
        normalizer = PageLocalNormalizer()
        page, blocks = normalizer.normalize_page(
            {"blocks": [raw], "width": 612.0, "height": 792.0},
            page_no=1,
            parser_name="test_parser",
        )
        assert len(blocks[0].citations) == 2
        assert blocks[0].citations[0].ref_id == "ref_1"
        assert blocks[0].citations[1].ref_type == "external"

    def test_unknown_parser_fields_ignored_gracefully(self) -> None:
        """Parser-specific fields not in DocIR schema are ignored without error."""
        raw = _raw_block(custom_layout_hints={"dual_column": True}, parser_version="2.0")
        normalizer = PageLocalNormalizer()
        page, blocks = normalizer.normalize_page(
            {"blocks": [raw], "width": 612.0, "height": 792.0},
            page_no=1,
            parser_name="test_parser",
        )
        assert len(blocks) == 1
        # The block is valid even with unknown fields
        assert blocks[0].block_id == "blk_1"

    def test_rejects_invalid_bbox_length(self) -> None:
        """Normalization rejects bbox with wrong length."""
        raw = _raw_block(bbox=[10.0, 20.0, 100.0])  # Only 3 values
        normalizer = PageLocalNormalizer()
        with pytest.raises(NormalizationError, match="bbox length"):
            normalizer.normalize_page(
                {"blocks": [raw], "width": 612.0, "height": 792.0},
                page_no=1,
                parser_name="test_parser",
            )

    def test_rejects_invalid_bbox_type(self) -> None:
        """Normalization rejects bbox with wrong type."""
        raw = _raw_block(bbox="not_a_bbox")
        normalizer = PageLocalNormalizer()
        with pytest.raises(NormalizationError, match="bbox type"):
            normalizer.normalize_page(
                {"blocks": [raw], "width": 612.0, "height": 792.0},
                page_no=1,
                parser_name="test_parser",
            )

    def test_rejects_non_numeric_bbox_values(self) -> None:
        """Normalization rejects bbox with non-numeric values."""
        raw = _raw_block(bbox=[10.0, "bad", 100.0, 40.0])
        normalizer = PageLocalNormalizer()
        with pytest.raises(NormalizationError, match="bbox values"):
            normalizer.normalize_page(
                {"blocks": [raw], "width": 612.0, "height": 792.0},
                page_no=1,
                parser_name="test_parser",
            )

    def test_all_structured_fields_combined(self) -> None:
        """All structured fields preserved in a single block."""
        raw = _raw_block(
            block_type="paragraph",
            table_cells=[{"row": 0, "col": 0, "text_plain": "X"}],
            footnote_refs=["fn_1"],
            citations=[{"ref_id": "r1"}],
        )
        normalizer = PageLocalNormalizer()
        page, blocks = normalizer.normalize_page(
            {"blocks": [raw], "width": 612.0, "height": 792.0},
            page_no=1,
            parser_name="test_parser",
        )
        b = blocks[0]
        assert b.table_cells is not None and len(b.table_cells) == 1
        assert b.footnote_refs == ["fn_1"]
        assert len(b.citations) == 1
