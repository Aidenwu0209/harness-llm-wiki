"""Tests for US-017+018: deterministic entity/claim/relation/anchor IDs."""

from __future__ import annotations

from docos.models.docir import Block, BlockType, DocIR, Page
from docos.knowledge.extractor import KnowledgeExtractionPipeline


def _make_docir() -> DocIR:
    return DocIR(
        doc_id="doc_det", source_id="src_det", parser="test",
        page_count=1,
        pages=[Page(page_no=1, width=612.0, height=792.0, blocks=["blk_t", "blk_h", "blk_p"])],
        blocks=[
            Block(block_id="blk_t", page_no=1, block_type=BlockType.TITLE,
                  reading_order=0, bbox=(0, 0, 500, 30), text_plain="Test Document",
                  source_parser="test", source_node_id="n0"),
            Block(block_id="blk_h", page_no=1, block_type=BlockType.HEADING,
                  reading_order=1, bbox=(0, 40, 500, 60), text_plain="Introduction",
                  source_parser="test", source_node_id="n1"),
            Block(block_id="blk_p", page_no=1, block_type=BlockType.PARAGRAPH,
                  reading_order=2, bbox=(0, 70, 500, 120), text_plain="This is the introduction content.",
                  source_parser="test", source_node_id="n2"),
        ],
    )


class TestDeterministicIDs:
    def test_entity_ids_deterministic(self) -> None:
        """Entity IDs derived from stable inputs, not random UUIDs."""
        docir = _make_docir()
        pipeline = KnowledgeExtractionPipeline()
        e1, _, _ = pipeline.extract(docir)
        e2, _, _ = pipeline.extract(docir)
        ids1 = {e.entity_id for e in e1}
        ids2 = {e.entity_id for e in e2}
        assert ids1 == ids2

    def test_claim_ids_deterministic(self) -> None:
        """Claim IDs derived from stable inputs."""
        docir = _make_docir()
        pipeline = KnowledgeExtractionPipeline()
        _, c1, _ = pipeline.extract(docir)
        _, c2, _ = pipeline.extract(docir)
        ids1 = {c.claim_id for c in c1}
        ids2 = {c.claim_id for c in c2}
        assert ids1 == ids2

    def test_relation_ids_deterministic(self) -> None:
        """Relation IDs derived from stable source/object/semantic-type inputs."""
        docir = _make_docir()
        pipeline = KnowledgeExtractionPipeline()
        _, _, r1 = pipeline.extract(docir)
        _, _, r2 = pipeline.extract(docir)
        ids1 = {r.relation_id for r in r1}
        ids2 = {r.relation_id for r in r2}
        assert ids1 == ids2

    def test_anchor_ids_deterministic(self) -> None:
        """Evidence anchor IDs derived from stable source/block evidence."""
        docir = _make_docir()
        pipeline = KnowledgeExtractionPipeline()
        _, c1, _ = pipeline.extract(docir)
        _, c2, _ = pipeline.extract(docir)
        anchors1 = {a.anchor_id for c in c1 for a in c.evidence_anchors}
        anchors2 = {a.anchor_id for c in c2 for a in c.evidence_anchors}
        assert anchors1 == anchors2

    def test_extraction_twice_identical_all_ids(self) -> None:
        """Running extraction twice on the same unchanged source produces identical IDs."""
        docir = _make_docir()
        pipeline = KnowledgeExtractionPipeline()
        e1, c1, r1 = pipeline.extract(docir)
        e2, c2, r2 = pipeline.extract(docir)
        assert [e.entity_id for e in e1] == [e.entity_id for e in e2]
        assert [c.claim_id for c in c1] == [c.claim_id for c in c2]
        assert [r.relation_id for r in r1] == [r.relation_id for r in r2]
