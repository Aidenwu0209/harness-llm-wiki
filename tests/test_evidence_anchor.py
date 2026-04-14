"""Tests for US-019: expand evidence anchors for source drilldown."""

from __future__ import annotations

from docos.models.knowledge import ClaimRecord, ClaimStatus, EvidenceAnchor


class TestEvidenceAnchorDrilldown:
    def test_anchor_with_bbox_and_char_offsets(self) -> None:
        """Anchor includes bbox, char offsets, and render_uri."""
        anchor = EvidenceAnchor(
            anchor_id="anc_test", source_id="src_1", doc_id="doc_1",
            page_no=3, block_id="blk_42",
            bbox=(10.0, 20.0, 500.0, 40.0),
            char_start=15, char_end=89,
            quote="Evidence text here",
            render_uri="file:///raw/src_1/run_001/stdlib_pdf/page_0003.png",
        )
        assert anchor.bbox == (10.0, 20.0, 500.0, 40.0)
        assert anchor.char_start == 15
        assert anchor.char_end == 89
        assert anchor.render_uri is not None

    def test_claim_recover_source_page_and_block(self) -> None:
        """A claim can reference its anchor and recover source page and block."""
        anchor = EvidenceAnchor(
            anchor_id="anc_1", source_id="src_1", doc_id="doc_1",
            page_no=5, block_id="blk_100",
        )
        claim = ClaimRecord(
            claim_id="clm_1", statement="Test claim",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[anchor],
            supporting_sources=["src_1"],
        )
        # Recover source page and block from anchor
        a = claim.evidence_anchors[0]
        assert a.page_no == 5
        assert a.block_id == "blk_100"
        assert a.source_id == "src_1"
        assert a.doc_id == "doc_1"

    def test_multilingual_text_anchor(self) -> None:
        """Anchor with multilingual quote serializes correctly."""
        anchor = EvidenceAnchor(
            anchor_id="anc_zh", source_id="src_zh", doc_id="doc_zh",
            page_no=1, block_id="blk_中文",
            quote="这是一段中文引用文本，用于测试多语言支持。",
        )
        data = anchor.model_dump_json()
        restored = EvidenceAnchor.model_validate_json(data)
        assert restored.quote == "这是一段中文引用文本，用于测试多语言支持。"
        assert restored.block_id == "blk_中文"

    def test_anchor_missing_optional_fields(self) -> None:
        """Anchor with only required fields serializes without breaking."""
        anchor = EvidenceAnchor(
            anchor_id="anc_min", source_id="src_1", doc_id="doc_1",
            page_no=1, block_id="blk_1",
        )
        assert anchor.bbox is None
        assert anchor.char_start is None
        assert anchor.char_end is None
        assert anchor.render_uri is None
        assert anchor.quote == ""
        # Round-trip
        data = anchor.model_dump_json()
        restored = EvidenceAnchor.model_validate_json(data)
        assert restored.bbox is None
        assert restored.source_id == "src_1"
