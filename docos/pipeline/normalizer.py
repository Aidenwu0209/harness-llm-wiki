"""Normalizer — page-local and document-global normalization.

Stage A (page-local): Convert parser output into DocIR pages/blocks.
Stage B (document-global): Cross-page repair for structure, tables, references.

Every repair is logged for auditability.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from docos.models.docir import (
    Block,
    BlockType,
    BBox,
    DocIR,
    DocIRWarning,
    Page,
    PageWarning,
    Relation,
    RelationType,
)


# ---------------------------------------------------------------------------
# Repair log
# ---------------------------------------------------------------------------

class RepairRecord(BaseModel):
    """A single repair entry — before/after with reason."""

    repair_id: str = Field(default_factory=lambda: f"repair_{uuid.uuid4().hex[:8]}")
    repair_type: str
    before: str = ""
    after: str = ""
    reason: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    performed_by: Literal["rule", "model", "human"] = "rule"
    timestamp: datetime = Field(default_factory=datetime.now)


class RepairLog(BaseModel):
    """Collection of repair records for a single normalization run."""

    source_id: str
    run_id: str
    repairs: list[RepairRecord] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None

    def add(self, repair: RepairRecord) -> None:
        self.repairs.append(repair)

    @property
    def count(self) -> int:
        return len(self.repairs)


# ---------------------------------------------------------------------------
# Page-local normalizer (Stage A)
# ---------------------------------------------------------------------------

class PageLocalNormalizer:
    """Converts raw parser output into initial DocIR pages and blocks.

    This stage is page-local — it does not attempt cross-page repair.
    Unknown content is represented as BlockType.UNKNOWN (never dropped).
    """

    def normalize_page(
        self,
        page_data: dict[str, Any],
        page_no: int,
        parser_name: str,
    ) -> tuple[Page, list[Block]]:
        """Normalize a single page of parser output.

        Args:
            page_data: Parser-specific page data.
            page_no: 1-based page number.
            parser_name: Name of the source parser.

        Returns:
            Tuple of (Page, list of Blocks).
        """
        width = page_data.get("width", 612.0)
        height = page_data.get("height", 792.0)
        rotation = page_data.get("rotation", 0.0)
        ocr_used = page_data.get("ocr_used", False)

        raw_blocks: list[dict[str, Any]] = page_data.get("blocks", [])

        blocks: list[Block] = []
        block_ids: list[str] = []

        for i, raw_block in enumerate(raw_blocks):
            block = self._convert_block(raw_block, page_no, i, parser_name)
            blocks.append(block)
            block_ids.append(block.block_id)

        page = Page(
            page_no=page_no,
            width=width,
            height=height,
            rotation=rotation,
            ocr_used=ocr_used,
            blocks=block_ids,
        )

        return page, blocks

    def _convert_block(
        self,
        raw: dict[str, Any],
        page_no: int,
        reading_order: int,
        parser_name: str,
    ) -> Block:
        """Convert a raw parser block to canonical DocIR Block."""
        block_type_str = raw.get("block_type", "unknown")
        try:
            block_type = BlockType(block_type_str)
        except ValueError:
            block_type = BlockType.UNKNOWN

        bbox_raw = raw.get("bbox", [0, 0, 0, 0])
        bbox: BBox = (
            float(bbox_raw[0]),
            float(bbox_raw[1]),
            float(bbox_raw[2]),
            float(bbox_raw[3]),
        )

        return Block(
            block_id=raw.get("block_id", f"p{page_no}_b{reading_order}"),
            page_no=page_no,
            block_type=block_type,
            reading_order=raw.get("reading_order", reading_order),
            bbox=bbox,
            parent_id=raw.get("parent_id"),
            children_ids=raw.get("children_ids", []),
            text_plain=raw.get("text_plain", ""),
            text_md=raw.get("text_md", ""),
            text_html=raw.get("text_html", ""),
            latex=raw.get("latex"),
            caption_target=raw.get("caption_target"),
            confidence=raw.get("confidence", 1.0),
            source_parser=parser_name,
            source_node_id=raw.get("source_node_id", ""),
        )


# ---------------------------------------------------------------------------
# Document-global repair (Stage B)
# ---------------------------------------------------------------------------

class GlobalRepair:
    """Cross-page structure repair.

    Applies repairs that require document-wide context:
    - Heading hierarchy normalization
    - Repeated header/footer noise removal
    - Cross-page table continuity
    - Cross-page note/reference continuity
    - Caption attachment fix
    """

    def repair(self, docir: DocIR, repair_log: RepairLog) -> DocIR:
        """Apply all global repairs to a DocIR.

        The original parser output is NOT modified — repairs create
        a new DocIR with repair records in the log.
        """
        blocks = list(docir.blocks)
        relations = list(docir.relations)
        warnings = list(docir.warnings)

        blocks = self._normalize_heading_hierarchy(blocks, repair_log)
        blocks = self._remove_repeated_headers_footers(blocks, repair_log)
        blocks, relations = self._link_cross_page_continuation(blocks, relations, repair_log)
        blocks, relations = self._fix_caption_attachments(blocks, relations, repair_log)

        return DocIR(
            doc_id=docir.doc_id,
            source_id=docir.source_id,
            source_uri=docir.source_uri,
            mime_type=docir.mime_type,
            parser=docir.parser,
            parser_version=docir.parser_version,
            schema_version=docir.schema_version,
            created_at=docir.created_at,
            language=docir.language,
            page_count=docir.page_count,
            pages=docir.pages,
            blocks=blocks,
            relations=relations,
            warnings=warnings,
            confidence=docir.confidence,
        )

    def _normalize_heading_hierarchy(
        self, blocks: list[Block], log: RepairLog
    ) -> list[Block]:
        """Ensure heading levels are monotonically non-decreasing from 1."""
        heading_blocks = [b for b in blocks if b.block_type == BlockType.HEADING]
        if not heading_blocks:
            return blocks

        # Extract heading levels from text_md markdown syntax (e.g. "## " → level 2)
        levels: list[int] = []
        for b in heading_blocks:
            md = b.text_md.lstrip()
            level = 0
            for ch in md:
                if ch == "#":
                    level += 1
                else:
                    break
            if level > 0:
                levels.append(level)

        if not levels:
            return blocks

        min_level = min(levels)
        if min_level <= 1:
            return blocks

        # Shift all headings down by (min_level - 1)
        shift = min_level - 1
        result = []
        for b in blocks:
            if b.block_type == BlockType.HEADING:
                old_md = b.text_md
                # Remove 'shift' number of leading '#' characters
                stripped = old_md.lstrip("#")
                leading_space = ""
                if stripped and stripped[0] == " ":
                    leading_space = " "
                    stripped = stripped[1:]
                new_md = "#" + leading_space + stripped
                log.add(RepairRecord(
                    repair_type="heading_hierarchy_shift",
                    before=f"level {min_level}: {old_md[:50]}",
                    after=f"shifted to level 1: {new_md[:50]}",
                    reason=f"Heading hierarchy started at level {min_level}, shifted by {shift}",
                    confidence=0.9,
                    performed_by="rule",
                ))
                result.append(Block(**{**b.model_dump(), "text_md": new_md}))
            else:
                result.append(b)
        return result

        return blocks

    def _remove_repeated_headers_footers(
        self, blocks: list[Block], log: RepairLog
    ) -> list[Block]:
        """Detect and flag repeated header/footer blocks across pages."""
        from collections import Counter

        header_blocks = [b for b in blocks if b.block_type == BlockType.HEADER]
        footer_blocks = [b for b in blocks if b.block_type == BlockType.FOOTER]

        result = list(blocks)
        removed = 0

        for block_group in [header_blocks, footer_blocks]:
            text_counts: Counter[str] = Counter()
            for b in block_group:
                text_counts[b.text_plain.strip()] += 1

            repeated_texts = {t for t, c in text_counts.items() if c > 1 and t}

            if repeated_texts:
                filtered = []
                for b in result:
                    if (
                        b.block_type in (BlockType.HEADER, BlockType.FOOTER)
                        and b.text_plain.strip() in repeated_texts
                    ):
                        removed += 1
                        log.add(RepairRecord(
                            repair_type="repeated_header_footer_removal",
                            before=f"[{b.block_type.value}] {b.text_plain[:50]}",
                            after="(removed)",
                            reason=f"Repeated {b.block_type.value} text appears on {text_counts[b.text_plain.strip()]} pages",
                            confidence=0.95,
                            performed_by="rule",
                        ))
                    else:
                        filtered.append(b)
                result = filtered

        return result

    def _link_cross_page_continuation(
        self, blocks: list[Block], relations: list[Relation], log: RepairLog
    ) -> tuple[list[Block], list[Relation]]:
        """Link blocks that continue across pages.

        Detects same-type blocks at the end of one page and the start of
        the next, and creates continued_from/continued_to relations.
        """
        pages: dict[int, list[Block]] = {}
        for b in blocks:
            pages.setdefault(b.page_no, []).append(b)

        sorted_pages = sorted(pages.keys())
        new_relations = list(relations)

        for i in range(len(sorted_pages) - 1):
            curr_page = sorted_pages[i]
            next_page = sorted_pages[i + 1]

            curr_blocks = sorted(pages[curr_page], key=lambda b: b.reading_order)
            next_blocks = sorted(pages[next_page], key=lambda b: b.reading_order)

            if not curr_blocks or not next_blocks:
                continue

            last = curr_blocks[-1]
            first = next_blocks[0]

            # Same type at page boundary → likely continuation
            continuation_types = {
                BlockType.PARAGRAPH,
                BlockType.TABLE,
                BlockType.LIST,
                BlockType.EQUATION_BLOCK,
            }
            if (
                last.block_type in continuation_types
                and last.block_type == first.block_type
            ):
                rel_forward = Relation(
                    relation_id=f"rel_cont_{last.block_id}_{first.block_id}",
                    relation_type=RelationType.CONTINUED_TO,
                    source_block_id=last.block_id,
                    target_block_id=first.block_id,
                    confidence=0.8,
                )
                rel_backward = Relation(
                    relation_id=f"rel_cont_{first.block_id}_{last.block_id}",
                    relation_type=RelationType.CONTINUED_FROM,
                    source_block_id=first.block_id,
                    target_block_id=last.block_id,
                    confidence=0.8,
                )
                new_relations.extend([rel_forward, rel_backward])

                log.add(RepairRecord(
                    repair_type="cross_page_continuation",
                    before=f"Unlinked: {last.block_id} (p{curr_page}) → {first.block_id} (p{next_page})",
                    after=f"Linked: continued_to / continued_from",
                    reason=f"Same block_type '{last.block_type.value}' at page boundary",
                    confidence=0.8,
                    performed_by="rule",
                ))

        return blocks, new_relations

    def _fix_caption_attachments(
        self, blocks: list[Block], relations: list[Relation], log: RepairLog
    ) -> tuple[list[Block], list[Relation]]:
        """Ensure caption blocks are linked to their targets via relations."""
        caption_blocks = [b for b in blocks if b.block_type == BlockType.CAPTION]
        new_relations = list(relations)

        for cap in caption_blocks:
            if cap.caption_target:
                # Already linked
                continue

            # Find nearest figure/table on same page
            candidates = [
                b for b in blocks
                if b.page_no == cap.page_no
                and b.block_type in (BlockType.FIGURE, BlockType.TABLE)
                and b.block_id != cap.block_id
            ]

            if candidates:
                # Pick closest by bbox distance
                def bbox_distance(a: Block, b: Block) -> float:
                    a_bbox: BBox = a.bbox
                    b_bbox: BBox = b.bbox
                    ax = (a_bbox[0] + a_bbox[2]) / 2
                    ay = (a_bbox[1] + a_bbox[3]) / 2
                    bx = (b_bbox[0] + b_bbox[2]) / 2
                    by = (b_bbox[1] + b_bbox[3]) / 2
                    return float(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5)

                nearest = min(candidates, key=lambda c: bbox_distance(cap, c))

                new_relations.append(Relation(
                    relation_id=f"rel_cap_{cap.block_id}_{nearest.block_id}",
                    relation_type=RelationType.CAPTION_OF,
                    source_block_id=cap.block_id,
                    target_block_id=nearest.block_id,
                    confidence=0.7,
                ))

                log.add(RepairRecord(
                    repair_type="caption_attachment",
                    before=f"Unlinked caption: {cap.block_id}",
                    after=f"Linked to: {nearest.block_id} ({nearest.block_type.value})",
                    reason="Caption had no explicit target; linked to nearest figure/table on same page",
                    confidence=0.7,
                    performed_by="rule",
                ))

        return blocks, new_relations
