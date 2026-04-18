"""Tests for US-019: Readability gates for concept extraction candidates.

Verifies that concept extraction filters out unreadable candidates
*before* they are persisted or compiled into wiki pages.

Concept entities are extracted from HEADING blocks by
``RuleBasedEntityExtractor.extract_entities()``.  The readability gate
(``is_readable_title``) is applied to each heading candidate before it
is appended to the returned entity list, ensuring unreadable concept
names never reach the knowledge store.
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
# Tests — concept readability gate at extraction
# ---------------------------------------------------------------------------

class TestConceptReadabilityGate:
    """Verify unreadable concept candidates are filtered during extraction."""

    def test_readable_concept_entity_is_created(self) -> None:
        """A readable heading should produce a concept entity."""
        blocks = [
            _make_block("b1", "title", text_plain="Good Paper"),
            _make_block("h1", "heading", text_plain="Attention Mechanism"),
        ]
        docir = _make_docir(blocks)
        extractor = RuleBasedEntityExtractor()
        entities = extractor.extract_entities(docir)

        concept_ents = [e for e in entities if e.entity_type == EntityType.CONCEPT]
        assert len(concept_ents) == 1
        assert concept_ents[0].canonical_name == "Attention Mechanism"

    def test_garbage_concept_blocked_at_extraction(self) -> None:
        """A binary-garbage heading should NOT produce a concept entity."""
        garbage = "\x00\x01\x02\x03\x04\x05\x06\x07\x08"
        assert not is_readable_title(garbage)

        blocks = [
            _make_block("b1", "title", text_plain="Readable Title"),
            _make_block("h1", "heading", text_plain=garbage),
            _make_block("h2", "heading", text_plain="Valid Section"),
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
        assert "Valid Section" in concept_names

    def test_control_chars_concept_blocked(self) -> None:
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

    def test_readable_cjk_concept_passes(self) -> None:
        """CJK concept names should pass the readability gate."""
        blocks = [
            _make_block("b1", "title", text_plain="深度学习综述"),
            _make_block("h1", "heading", text_plain="Transformer 架构"),
            _make_block("h2", "heading", text_plain="自注意力机制"),
        ]
        docir = _make_docir(blocks)
        extractor = RuleBasedEntityExtractor()
        entities = extractor.extract_entities(docir)

        concept_names = {
            e.canonical_name for e in entities if e.entity_type == EntityType.CONCEPT
        }
        assert "Transformer 架构" in concept_names
        assert "自注意力机制" in concept_names

    def test_mixed_readable_and_garbage_concepts(self) -> None:
        """Only readable concepts survive extraction when mixed with garbage."""
        blocks = [
            _make_block("b1", "title", text_plain="Good Paper"),
            _make_block("h1", "heading", text_plain="Introduction"),
            _make_block("h2", "heading", text_plain="\x00\x01\x02\x03\x04"),
            _make_block("h3", "heading", text_plain="Conclusion"),
            _make_block("h4", "heading", text_plain="\x00\x00\x00\x00\x00\x00"),
        ]
        docir = _make_docir(blocks)
        entities = RuleBasedEntityExtractor().extract_entities(docir)

        concept_names = {
            e.canonical_name for e in entities if e.entity_type == EntityType.CONCEPT
        }
        assert "Introduction" in concept_names
        assert "Conclusion" in concept_names
        assert "\x00\x01\x02\x03\x04" not in concept_names
        assert "\x00\x00\x00\x00\x00\x00" not in concept_names

    def test_replacement_char_concept_blocked(self) -> None:
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

    def test_concept_gate_prevents_persistence_payload(self) -> None:
        """Filtered concept candidates are never part of the extraction output,
        so they would never reach the knowledge store."""
        blocks = [
            _make_block("b1", "title", text_plain="Paper Title"),
            _make_block("h1", "heading", text_plain="Valid Concept"),
            _make_block("h2", "heading", text_plain="\ufffd\ufffd\ufffd\ufffd"),
        ]
        docir = _make_docir(blocks)
        entities = RuleBasedEntityExtractor().extract_entities(docir)

        # Only the valid concept should exist
        concept_ents = [e for e in entities if e.entity_type == EntityType.CONCEPT]
        assert len(concept_ents) == 1
        assert all(is_readable_title(e.canonical_name) for e in concept_ents)
        assert concept_ents[0].canonical_name == "Valid Concept"

    def test_deterministic_concept_filtering(self) -> None:
        """Same unreadable concept input always produces the same filtered result."""
        garbage = "\x00\x01\x02\x03\x04\x05"
        blocks = [
            _make_block("b1", "title", text_plain="Title"),
            _make_block("h1", "heading", text_plain=garbage),
            _make_block("h2", "heading", text_plain="Good Concept"),
        ]
        docir = _make_docir(blocks)
        extractor = RuleBasedEntityExtractor()

        results = [extractor.extract_entities(docir) for _ in range(10)]
        for entities in results:
            concept_names = [
                e.canonical_name for e in entities if e.entity_type == EntityType.CONCEPT
            ]
            assert garbage not in concept_names
            assert "Good Concept" in concept_names

    def test_concept_blocked_does_not_affect_document_entity(self) -> None:
        """A garbage concept heading should not block the document entity."""
        garbage = "\x00\x01\x02\x03\x04\x05\x06\x07\x08"
        blocks = [
            _make_block("b1", "title", text_plain="Valid Document Title"),
            _make_block("h1", "heading", text_plain=garbage),
        ]
        docir = _make_docir(blocks)
        entities = RuleBasedEntityExtractor().extract_entities(docir)

        doc_ents = [e for e in entities if e.entity_type == EntityType.DOCUMENT]
        concept_ents = [e for e in entities if e.entity_type == EntityType.CONCEPT]
        assert len(doc_ents) == 1
        assert len(concept_ents) == 0
