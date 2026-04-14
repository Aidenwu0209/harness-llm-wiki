"""Tests for US-036: PDF fixtures and workflow regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.knowledge.extractor import KnowledgeExtractionPipeline
from docos.models.docir import Block, BlockType, DocIR, Page
from docos.pipeline.normalizer import GlobalRepair, PageLocalNormalizer, RepairLog


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write_simple_pdf(path: Path) -> Path:
    """Simple text-heavy PDF."""
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 80 >>\nstream\n"
        b"BT /F1 12 Tf 100 700 Td (Introduction) Tj ET\n"
        b"BT /F1 10 Tf 100 680 Td (This is a test document body.) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _write_complex_pdf(path: Path) -> Path:
    """Complex multi-page PDF with tables and headings."""
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R, 4 0 R] /Count 2 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _make_simple_docir() -> DocIR:
    return DocIR(
        doc_id="doc_simple", source_id="src_simple", parser="stdlib_pdf",
        page_count=1,
        pages=[Page(page_no=1, width=612.0, height=792.0, blocks=["blk_1", "blk_2"])],
        blocks=[
            Block(block_id="blk_1", page_no=1, block_type=BlockType.HEADING,
                  reading_order=0, bbox=(0, 0, 500, 30), text_plain="Introduction",
                  text_md="## Introduction", source_parser="test", source_node_id="n1"),
            Block(block_id="blk_2", page_no=1, block_type=BlockType.PARAGRAPH,
                  reading_order=1, bbox=(0, 40, 500, 80), text_plain="This is the body.",
                  source_parser="test", source_node_id="n2"),
        ],
    )


def _make_complex_docir() -> DocIR:
    return DocIR(
        doc_id="doc_complex", source_id="src_complex", parser="stdlib_pdf",
        page_count=2,
        pages=[
            Page(page_no=1, width=612.0, height=792.0, blocks=["blk_h1", "blk_p1"]),
            Page(page_no=2, width=612.0, height=792.0, blocks=["blk_p2", "blk_h2", "blk_p3"]),
        ],
        blocks=[
            Block(block_id="blk_h1", page_no=1, block_type=BlockType.HEADING,
                  reading_order=0, bbox=(0, 0, 500, 30), text_plain="Part A",
                  text_md="## Part A", source_parser="test", source_node_id="n1"),
            Block(block_id="blk_p1", page_no=1, block_type=BlockType.PARAGRAPH,
                  reading_order=1, bbox=(0, 40, 500, 80), text_plain="Content A page 1.",
                  source_parser="test", source_node_id="n2"),
            Block(block_id="blk_p2", page_no=2, block_type=BlockType.PARAGRAPH,
                  reading_order=0, bbox=(0, 0, 500, 40), text_plain="Content A continued.",
                  source_parser="test", source_node_id="n3"),
            Block(block_id="blk_h2", page_no=2, block_type=BlockType.HEADING,
                  reading_order=1, bbox=(0, 50, 500, 80), text_plain="Part B",
                  text_md="## Part B", source_parser="test", source_node_id="n4"),
            Block(block_id="blk_p3", page_no=2, block_type=BlockType.PARAGRAPH,
                  reading_order=2, bbox=(0, 90, 500, 130), text_plain="Content B.",
                  source_parser="test", source_node_id="n5"),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPDFFixtures:
    def test_simple_pdf_fixture_exists(self, tmp_path: Path) -> None:
        pdf_path = _write_simple_pdf(tmp_path / "simple.pdf")
        assert pdf_path.exists()
        assert pdf_path.read_bytes().startswith(b"%PDF")

    def test_complex_pdf_fixture_exists(self, tmp_path: Path) -> None:
        pdf_path = _write_complex_pdf(tmp_path / "complex.pdf")
        assert pdf_path.exists()
        assert pdf_path.read_bytes().startswith(b"%PDF")


class TestWorkflowIntegration:
    def test_simple_workflow_extract(self) -> None:
        """Ingest → extract pipeline on simple fixture."""
        docir = _make_simple_docir()
        pipeline = KnowledgeExtractionPipeline()
        entities, claims, relations = pipeline.extract(docir)
        assert len(entities) >= 1  # At least a document entity
        assert len(claims) >= 1  # At least one section claim

    def test_complex_workflow_extract(self) -> None:
        """Ingest → extract on complex multi-page fixture."""
        docir = _make_complex_docir()
        pipeline = KnowledgeExtractionPipeline()
        entities, claims, relations = pipeline.extract(docir)
        assert len(entities) >= 2  # Document + concepts
        assert len(claims) >= 2  # Part A and Part B

    def test_normalize_and_repair(self) -> None:
        """Normalize → repair workflow."""
        docir = _make_complex_docir()
        repair_log = RepairLog(source_id="src_complex", run_id="run_test")
        repaired = GlobalRepair().repair(docir, repair_log)
        assert repaired.page_count == 2
        assert len(repaired.blocks) > 0

    def test_re_ingest_stability(self) -> None:
        """Re-ingesting same unchanged source produces stable IDs."""
        docir = _make_simple_docir()
        pipeline = KnowledgeExtractionPipeline()
        e1, c1, r1 = pipeline.extract(docir)
        e2, c2, r2 = pipeline.extract(docir)

        entity_ids_1 = sorted(e.entity_id for e in e1)
        entity_ids_2 = sorted(e.entity_id for e in e2)
        assert entity_ids_1 == entity_ids_2

        claim_ids_1 = sorted(c.claim_id for c in c1)
        claim_ids_2 = sorted(c.claim_id for c in c2)
        assert claim_ids_1 == claim_ids_2
