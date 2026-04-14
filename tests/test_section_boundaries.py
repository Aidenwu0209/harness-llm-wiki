"""Tests for US-020: section boundaries and cross-page extraction."""

from __future__ import annotations

from docos.models.docir import Block, BlockType, DocIR, Page
from docos.knowledge.extractor import KnowledgeExtractionPipeline


def _make_cross_page_docir() -> DocIR:
    """Heading on page 1, section continues to page 2 with a new heading."""
    return DocIR(
        doc_id="doc_cp", source_id="src_cp", parser="test",
        page_count=2,
        pages=[
            Page(page_no=1, width=612.0, height=792.0, blocks=["blk_h1", "blk_p1"]),
            Page(page_no=2, width=612.0, height=792.0, blocks=["blk_p2", "blk_h2", "blk_p3"]),
        ],
        blocks=[
            Block(block_id="blk_h1", page_no=1, block_type=BlockType.HEADING,
                  reading_order=0, bbox=(0, 0, 500, 30), text_plain="Section A",
                  source_parser="test", source_node_id="n1"),
            Block(block_id="blk_p1", page_no=1, block_type=BlockType.PARAGRAPH,
                  reading_order=1, bbox=(0, 40, 500, 80), text_plain="Content A page 1",
                  source_parser="test", source_node_id="n2"),
            Block(block_id="blk_p2", page_no=2, block_type=BlockType.PARAGRAPH,
                  reading_order=0, bbox=(0, 0, 500, 40), text_plain="Content A page 2",
                  source_parser="test", source_node_id="n3"),
            Block(block_id="blk_h2", page_no=2, block_type=BlockType.HEADING,
                  reading_order=1, bbox=(0, 50, 500, 80), text_plain="Section B",
                  source_parser="test", source_node_id="n4"),
            Block(block_id="blk_p3", page_no=2, block_type=BlockType.PARAGRAPH,
                  reading_order=2, bbox=(0, 90, 500, 130), text_plain="Content B",
                  source_parser="test", source_node_id="n5"),
        ],
    )


class TestSectionBoundaries:
    def test_claim_stops_at_next_heading(self) -> None:
        """Section A claim does not include Section B content."""
        docir = _make_cross_page_docir()
        _, claims, _ = KnowledgeExtractionPipeline().extract(docir)

        section_a_claims = [c for c in claims if "Section A" in c.statement]
        assert len(section_a_claims) == 1
        claim = section_a_claims[0]
        # Should NOT contain "Content B" from Section B
        assert "Content B" not in claim.statement

    def test_cross_page_section_produces_claims(self) -> None:
        """A cross-page section produces claims from the continued body."""
        docir = _make_cross_page_docir()
        _, claims, _ = KnowledgeExtractionPipeline().extract(docir)

        section_a_claims = [c for c in claims if "Section A" in c.statement]
        assert len(section_a_claims) >= 1
        # The claim should reference both pages
        claim = section_a_claims[0]
        assert 1 in claim.page_refs
        assert 2 in claim.page_refs

    def test_cross_page_evidence_attached(self) -> None:
        """Cross-page evidence can be attached to extracted claims."""
        docir = _make_cross_page_docir()
        _, claims, _ = KnowledgeExtractionPipeline().extract(docir)

        section_a_claims = [c for c in claims if "Section A" in c.statement]
        assert section_a_claims
        claim = section_a_claims[0]
        # Should have anchors from both pages
        anchor_pages = {a.page_no for a in claim.evidence_anchors}
        assert 1 in anchor_pages
        assert 2 in anchor_pages

    def test_separate_sections_produce_separate_claims(self) -> None:
        """Each section heading produces its own distinct claim."""
        docir = _make_cross_page_docir()
        _, claims, _ = KnowledgeExtractionPipeline().extract(docir)

        section_a = [c for c in claims if "Section A" in c.statement]
        section_b = [c for c in claims if "Section B" in c.statement]
        assert len(section_a) >= 1
        assert len(section_b) >= 1
        assert section_a[0].claim_id != section_b[0].claim_id
