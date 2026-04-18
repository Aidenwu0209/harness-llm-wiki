"""Tests for US-018: Readability gates for entity extraction candidates.

Verifies that entity extraction filters out unreadable candidates
*before* they are persisted or compiled into wiki pages.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is importable.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docos.knowledge.extractor import RuleBasedEntityExtractor
from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.knowledge import EntityType
from docos.slugify import is_readable_title


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_block(
    block_id: str,
    block_type: str = "paragraph",
    page_no: int = 1,
    order: int = 0,
    text_plain: str = "",
) -> Block:
    return Block(
        block_id=block_id,
        page_no=page_no,
        block_type=BlockType(block_type),
        reading_order=order,
        bbox=(0.0, 0.0, 100.0, 50.0),
        text_plain=text_plain,
        source_parser="test",
        source_node_id=f"node_{block_id}",
    )


def _make_docir(blocks: list[Block]) -> DocIR:
    page_nos = sorted(set(b.page_no for b in blocks)) or [1]
    return DocIR(
        doc_id="doc_test",
        source_id="src_test",
        parser="test",
        page_count=len(page_nos),
        pages=[Page(page_no=p, width=612.0, height=792.0) for p in page_nos],
        blocks=blocks,
    )


# ---------------------------------------------------------------------------
# Tests — readability gate at extraction
# ---------------------------------------------------------------------------

class TestEntityReadabilityGate:
    """Verify unreadable entity candidates are filtered during extraction."""

    def test_readable_document_entity_is_created(self) -> None:
        """A readable document title should produce a document entity."""
        blocks = [
            _make_block("b1", "title", text_plain="Attention Is All You Need"),
            _make_block("h1", "heading", text_plain="Introduction"),
        ]
        docir = _make_docir(blocks)
        extractor = RuleBasedEntityExtractor()
        entities = extractor.extract_entities(docir)

        doc_ents = [e for e in entities if e.entity_type == EntityType.DOCUMENT]
        assert len(doc_ents) == 1
        assert doc_ents[0].canonical_name == "Attention Is All You Need"

    def test_garbage_title_blocked_at_extraction(self) -> None:
        """A binary-garbage document title should NOT produce an entity."""
        garbage = "\x00\x01\x02\x03\x04\x05"
        assert not is_readable_title(garbage)

        blocks = [
            _make_block("b1", "title", text_plain=garbage),
            _make_block("h1", "heading", text_plain="Normal Heading"),
        ]
        docir = _make_docir(blocks)
        extractor = RuleBasedEntityExtractor()
        entities = extractor.extract_entities(docir)

        # No document entity should exist because the title is unreadable
        doc_ents = [e for e in entities if e.entity_type == EntityType.DOCUMENT]
        assert len(doc_ents) == 0

    def test_garbage_heading_blocked_at_extraction(self) -> None:
        """A binary-garbage heading should NOT produce a concept entity."""
        garbage = "\x00\x01\x02\x03\x04\x05\x06\x07\x08"
        assert not is_readable_title(garbage)

        blocks = [
            _make_block("b1", "title", text_plain="Readable Document Title"),
            _make_block("h1", "heading", text_plain=garbage),
            _make_block("h2", "heading", text_plain="Good Section"),
        ]
        docir = _make_docir(blocks)
        extractor = RuleBasedEntityExtractor()
        entities = extractor.extract_entities(docir)

        concept_names = [
            e.canonical_name
            for e in entities
            if e.entity_type == EntityType.CONCEPT
        ]
        assert garbage not in concept_names
        assert "Good Section" in concept_names

    def test_readable_cjk_entity_passes(self) -> None:
        """CJK entity names should pass the readability gate."""
        blocks = [
            _make_block("b1", "title", text_plain="深度学习综述"),
            _make_block("h1", "heading", text_plain="Transformer 架构"),
        ]
        docir = _make_docir(blocks)
        extractor = RuleBasedEntityExtractor()
        entities = extractor.extract_entities(docir)

        assert len(entities) == 2
        names = {e.canonical_name for e in entities}
        assert "深度学习综述" in names
        assert "Transformer 架构" in names

    def test_control_chars_heading_blocked(self) -> None:
        """Headings consisting mostly of control characters are blocked."""
        noisy = "\x00\x01\x02\x03\x04\x05\x06\x07ab"  # 2/10 readable → 20%, below 30%
        assert not is_readable_title(noisy)

        blocks = [
            _make_block("b1", "title", text_plain="Normal Title"),
            _make_block("h1", "heading", text_plain=noisy),
        ]
        docir = _make_docir(blocks)
        entities = RuleBasedEntityExtractor().extract_entities(docir)

        concept_names = [
            e.canonical_name for e in entities if e.entity_type == EntityType.CONCEPT
        ]
        assert noisy not in concept_names

    def test_mixed_readable_and_garbage_entities(self) -> None:
        """Only readable entities survive extraction when mixed with garbage."""
        blocks = [
            _make_block("b1", "title", text_plain="Good Paper Title"),
            _make_block("h1", "heading", text_plain="Introduction"),
            _make_block("h2", "heading", text_plain="\x00\x01\x02\x03\x04"),
            _make_block("h3", "heading", text_plain="Conclusion"),
            _make_block("h4", "heading", text_plain="\x00\x00\x00\x00\x00\x00"),
        ]
        docir = _make_docir(blocks)
        entities = RuleBasedEntityExtractor().extract_entities(docir)

        names = {e.canonical_name for e in entities}
        assert "Good Paper Title" in names
        assert "Introduction" in names
        assert "Conclusion" in names
        assert "\x00\x01\x02\x03\x04" not in names
        assert "\x00\x00\x00\x00\x00\x00" not in names

    def test_replacement_char_heading_blocked(self) -> None:
        """Headings full of Unicode replacement characters are blocked."""
        noisy = "\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd"
        assert not is_readable_title(noisy)

        blocks = [
            _make_block("b1", "title", text_plain="Normal Title"),
            _make_block("h1", "heading", text_plain=noisy),
        ]
        docir = _make_docir(blocks)
        entities = RuleBasedEntityExtractor().extract_entities(docir)

        concept_names = [
            e.canonical_name for e in entities if e.entity_type == EntityType.CONCEPT
        ]
        assert noisy not in concept_names

    def test_empty_title_no_document_entity(self) -> None:
        """A title that is whitespace-only produces no document entity."""
        blocks = [
            _make_block("b1", "title", text_plain="   "),
        ]
        docir = _make_docir(blocks)
        entities = RuleBasedEntityExtractor().extract_entities(docir)

        doc_ents = [e for e in entities if e.entity_type == EntityType.DOCUMENT]
        assert len(doc_ents) == 0

    def test_deterministic_filtering(self) -> None:
        """Same unreadable input always produces the same (empty) entity list."""
        garbage = "\x00\x01\x02\x03\x04\x05"
        blocks = [
            _make_block("b1", "title", text_plain=garbage),
            _make_block("h1", "heading", text_plain=garbage),
        ]
        docir = _make_docir(blocks)
        extractor = RuleBasedEntityExtractor()

        results = [extractor.extract_entities(docir) for _ in range(10)]
        for entities in results:
            assert len(entities) == 0

    def test_extraction_gate_prevents_persistence_payload(self) -> None:
        """Filtered entities are never part of the extraction output,
        simulating that they would never reach the knowledge store."""
        blocks = [
            _make_block("b1", "title", text_plain="\x00\x01\x02\x03\x04\x05"),
            _make_block("h1", "heading", text_plain="Valid Heading"),
            _make_block("h2", "heading", text_plain="\ufffd\ufffd\ufffd\ufffd"),
        ]
        docir = _make_docir(blocks)
        entities = RuleBasedEntityExtractor().extract_entities(docir)

        # Only the valid heading entity should exist (no document, no garbage)
        assert all(is_readable_title(e.canonical_name) for e in entities)
        assert len(entities) == 1
        assert entities[0].canonical_name == "Valid Heading"
