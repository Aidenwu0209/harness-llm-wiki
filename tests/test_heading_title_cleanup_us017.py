"""Tests for US-017: Clean heading and title candidates after parse or normalize.

Verifies that heading and title block text is sanitized during normalization
(stage 4) so that downstream extraction (stage 5) consumes cleaned candidates.
"""

import pytest

from docos.models.docir import Block, BlockType, DocIR, Page
from docos.knowledge.extractor import RuleBasedEntityExtractor, RuleBasedClaimExtractor
from docos.pipeline.normalizer import GlobalRepair, RepairLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_block(
    block_id: str,
    block_type: str = "paragraph",
    page_no: int = 1,
    order: int = 0,
    text_plain: str = "",
    text_md: str = "",
) -> Block:
    return Block(
        block_id=block_id,
        page_no=page_no,
        block_type=BlockType(block_type),
        reading_order=order,
        bbox=(0.0, 0.0, 100.0, 50.0),
        text_plain=text_plain,
        text_md=text_md,
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
# AC1: Heading/title candidates pass through text-cleaning step
# ---------------------------------------------------------------------------

class TestTextCleaningStepApplied:
    """AC1: Heading or title candidates emitted after parse or normalize
    pass through a text-cleaning step before downstream use."""

    def test_heading_text_cleaned_after_normalize(self) -> None:
        """Heading blocks have sanitize_title applied during repair."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = _make_docir([
            _make_block("h1", block_type="heading", text_plain="Hello\x00World", text_md="Hello\x00World"),
        ])
        result = repair.repair(docir, log)
        heading = result.blocks[0]
        assert heading.text_plain == "HelloWorld"
        assert heading.text_md == "HelloWorld"

    def test_title_text_cleaned_after_normalize(self) -> None:
        """Title blocks have sanitize_title applied during repair."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = _make_docir([
            _make_block("t1", block_type="title", text_plain="Paper\x01Title", text_md="Paper\x01Title"),
        ])
        result = repair.repair(docir, log)
        title = result.blocks[0]
        assert title.text_plain == "PaperTitle"
        assert title.text_md == "PaperTitle"

    def test_paragraph_blocks_not_affected(self) -> None:
        """Non-heading/title blocks are left untouched by the cleaning step."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = _make_docir([
            _make_block("p1", block_type="paragraph", text_plain="Keep\x00as-is"),
        ])
        result = repair.repair(docir, log)
        assert result.blocks[0].text_plain == "Keep\x00as-is"

    def test_clean_heading_not_modified(self) -> None:
        """Already-clean heading text is not modified (sanitization-wise)."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = _make_docir([
            _make_block("h1", block_type="heading", text_plain="Clean Heading", text_md="# Clean Heading"),
        ])
        result = repair.repair(docir, log)
        assert result.blocks[0].text_plain == "Clean Heading"
        assert result.blocks[0].text_md == "# Clean Heading"
        # No sanitization repair record for clean text
        assert not any(r.repair_type == "heading_title_text_sanitized" for r in log.repairs)


# ---------------------------------------------------------------------------
# AC2: Control characters and binary garbage removed
# ---------------------------------------------------------------------------

class TestControlCharsRemoved:
    """AC2: Control characters and obvious binary garbage are removed
    or rejected during that step."""

    def test_control_chars_removed_from_heading(self) -> None:
        """Control characters (\\x00-\\x08, \\x0e-\\x1f) stripped."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        dirty = "Sec\x02tion\x05\x1fName"
        docir = _make_docir([
            _make_block("h1", block_type="heading", text_plain=dirty, text_md=dirty),
        ])
        result = repair.repair(docir, log)
        assert result.blocks[0].text_plain == "SectionName"

    def test_binary_garbage_removed(self) -> None:
        """Private-use codepoints and replacement char stripped."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        dirty = "My\ue000Title\ufffd"
        docir = _make_docir([
            _make_block("h1", block_type="heading", text_plain=dirty, text_md=dirty),
        ])
        result = repair.repair(docir, log)
        assert "\ue000" not in result.blocks[0].text_plain
        assert "\ufffd" not in result.blocks[0].text_plain

    def test_whitespace_collapsed(self) -> None:
        """Consecutive whitespace collapsed to single space."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = _make_docir([
            _make_block("h1", block_type="heading", text_plain="Too   much    space", text_md="Too   much    space"),
        ])
        result = repair.repair(docir, log)
        assert result.blocks[0].text_plain == "Too much space"

    def test_repair_log_records_sanitization(self) -> None:
        """Each sanitized block is recorded in the repair log."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = _make_docir([
            _make_block("h1", block_type="heading", text_plain="Bad\x00Heading", text_md="Bad\x00Heading"),
        ])
        repair.repair(docir, log)
        sanitized_repairs = [r for r in log.repairs if r.repair_type == "heading_title_text_sanitized"]
        assert len(sanitized_repairs) == 1
        assert sanitized_repairs[0].confidence == 1.0


# ---------------------------------------------------------------------------
# AC3: Downstream extraction consumes cleaned candidates
# ---------------------------------------------------------------------------

class TestDownstreamExtractionUsesCleaned:
    """AC3: Downstream extraction consumes the cleaned title candidates
    instead of the raw unfiltered values."""

    def test_entity_extraction_uses_cleaned_heading_name(self) -> None:
        """Entity extractor sees sanitized heading text, not raw."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        dirty_name = "Neural\x00Networks"
        docir = _make_docir([
            _make_block("h1", block_type="heading", order=0, text_plain=dirty_name, text_md=dirty_name),
            _make_block("p1", block_type="paragraph", order=1, text_plain="Some body text here."),
        ])
        repaired = repair.repair(docir, log)

        extractor = RuleBasedEntityExtractor()
        entities = extractor.extract_entities(repaired)

        concept_entities = [e for e in entities if e.entity_type.value == "concept"]
        assert len(concept_entities) >= 1
        # canonical_name should be cleaned, not containing control chars
        assert concept_entities[0].canonical_name == "NeuralNetworks"
        assert "\x00" not in concept_entities[0].canonical_name

    def test_entity_extraction_uses_cleaned_title_name(self) -> None:
        """Document entity from TITLE block gets cleaned name."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        dirty_title = "My\x02Paper\x05Title"
        docir = _make_docir([
            _make_block("t1", block_type="title", order=0, text_plain=dirty_title, text_md=dirty_title),
        ])
        repaired = repair.repair(docir, log)

        extractor = RuleBasedEntityExtractor()
        entities = extractor.extract_entities(repaired)

        doc_entities = [e for e in entities if e.entity_type.value == "document"]
        assert len(doc_entities) >= 1
        assert "\x02" not in doc_entities[0].canonical_name
        assert "\x05" not in doc_entities[0].canonical_name

    def test_claim_extraction_uses_cleaned_heading(self) -> None:
        """Claim statement embeds cleaned heading text, not raw."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        dirty_heading = "Intro\x1fduction"
        docir = _make_docir([
            _make_block("h1", block_type="heading", order=0, text_plain=dirty_heading, text_md=dirty_heading),
            _make_block("p1", block_type="paragraph", order=1, text_plain="Body text for the section."),
        ])
        repaired = repair.repair(docir, log)

        entities = RuleBasedEntityExtractor().extract_entities(repaired)
        claims = RuleBasedClaimExtractor().extract_claims(repaired, entities)

        # Claims should reference cleaned heading in statement
        assert len(claims) >= 1
        assert "\x1f" not in claims[0].statement
        assert "Introduction" in claims[0].statement

    def test_end_to_end_dirty_heading_flow(self) -> None:
        """Full flow: dirty heading → normalize (sanitize) → extract → clean entities."""
        repair = GlobalRepair()
        log = RepairLog(source_id="src_test", run_id="run_test")

        docir = _make_docir([
            _make_block("h1", block_type="heading", order=0,
                        text_plain="Deep\x00Learning\x02", text_md="## Deep\x00Learning\x02"),
            _make_block("p1", block_type="paragraph", order=1, text_plain="Content about deep learning."),
            _make_block("h2", block_type="heading", order=2,
                        text_plain="\x1fCNN Architectures", text_md="### \x1fCNN Architectures"),
            _make_block("p2", block_type="paragraph", order=3, text_plain="Convolutional networks."),
        ])
        repaired = repair.repair(docir, log)

        extractor = RuleBasedEntityExtractor()
        entities = extractor.extract_entities(repaired)

        # Both headings should produce entities with clean names
        for ent in entities:
            assert "\x00" not in ent.canonical_name
            assert "\x02" not in ent.canonical_name
            assert "\x1f" not in ent.canonical_name
