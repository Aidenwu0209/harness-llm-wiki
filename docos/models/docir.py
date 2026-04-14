"""Canonical DocIR — versioned document intermediate representation.

This module defines the single source of truth for parsed document structure.
Every parser output normalizes into this schema before downstream processing.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BlockType(str, Enum):
    """Supported block types (v1)."""

    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    TABLE = "table"
    TABLE_CELL = "table_cell"
    FIGURE = "figure"
    CAPTION = "caption"
    EQUATION = "equation"
    EQUATION_BLOCK = "equation_block"
    FOOTNOTE = "footnote"
    REFERENCE_ITEM = "reference_item"
    CODE_BLOCK = "code_block"
    QUOTE = "quote"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    UNKNOWN = "unknown"


class RelationType(str, Enum):
    """Supported relation types between blocks."""

    CAPTION_OF = "caption_of"
    FOOTNOTE_OF = "footnote_of"
    CONTINUED_FROM = "continued_from"
    CONTINUED_TO = "continued_to"
    REFERENCES = "references"
    MENTIONED_IN = "mentioned_in"
    SAME_TABLE_AS = "same_table_as"
    SAME_SECTION_AS = "same_section_as"
    DUPLICATE_OF = "duplicate_of"
    DERIVED_FROM = "derived_from"


# ---------------------------------------------------------------------------
# BBox
# ---------------------------------------------------------------------------

BBox = tuple[float, float, float, float]  # (x0, y0, x1, y1)


# ---------------------------------------------------------------------------
# Block
# ---------------------------------------------------------------------------

class TableCell(BaseModel):
    """A single cell in a table block."""

    row: int = Field(ge=0, description="Row index (0-based)")
    col: int = Field(ge=0, description="Column index (0-based)")
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    text_plain: str = ""
    is_header: bool = False


class Citation(BaseModel):
    """A citation reference within a block."""

    ref_id: str = Field(description="ID of the referenced block or external ref")
    ref_text: str = ""
    ref_type: Literal["internal", "external"] = "internal"


class Block(BaseModel):
    """A single structural block within a page.

    Blocks are the smallest addressable units in DocIR. Each block carries
    enough metadata to trace back to the original parser output and to
    locate the content in the source document.
    """

    block_id: str = Field(description="Unique block identifier")
    page_no: int = Field(ge=1, description="1-based page number")
    block_type: BlockType
    reading_order: int = Field(ge=0, description="Reading order within the page")

    # Geometry
    bbox: BBox = Field(description="Bounding box (x0, y0, x1, y1)")

    # Hierarchy
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)

    # Text content (at least one should be populated)
    text_plain: str = ""
    text_md: str = ""
    text_html: str = ""

    # Special content
    latex: str | None = None
    table_cells: list[TableCell] | None = None
    caption_target: str | None = Field(
        default=None,
        description="block_id of the figure/table this caption describes",
    )
    footnote_refs: list[str] = Field(
        default_factory=list,
        description="IDs of footnote blocks referenced by this block",
    )
    citations: list[Citation] = Field(default_factory=list)

    # Provenance
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_parser: str = Field(description="Name of the parser that produced this block")
    source_node_id: str = Field(
        description="Original node ID in parser-specific output",
    )

    @field_validator("bbox")
    @classmethod
    def _bbox_must_be_valid(cls, v: BBox) -> BBox:
        x0, y0, x1, y1 = v
        if x1 < x0 or y1 < y0:
            msg = f"Invalid bbox: ({x0}, {y0}, {x1}, {y1})"
            raise ValueError(msg)
        return v


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

class PageWarning(BaseModel):
    """A warning associated with a page."""

    code: str
    message: str
    severity: Literal["low", "medium", "high"] = "low"


class Page(BaseModel):
    """A single page in the document.

    Each page contains references to its blocks and carries layout metadata.
    """

    page_no: int = Field(ge=1, description="1-based page number")
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: float = 0.0
    image_uri: str | None = Field(default=None, description="URI of rendered page image")
    ocr_used: bool = False
    reading_order_version: str = "1"
    blocks: list[str] = Field(
        default_factory=list,
        description="Ordered list of block IDs on this page",
    )
    warnings: list[PageWarning] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Relation
# ---------------------------------------------------------------------------

class Relation(BaseModel):
    """A typed relation between two blocks."""

    relation_id: str
    relation_type: RelationType
    source_block_id: str
    target_block_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, object] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# DocIR Warning
# ---------------------------------------------------------------------------

class DocIRWarning(BaseModel):
    """A top-level warning for the document."""

    code: str
    message: str
    severity: Literal["low", "medium", "high"] = "medium"
    page_no: int | None = None
    block_id: str | None = None


# ---------------------------------------------------------------------------
# Canonical DocIR
# ---------------------------------------------------------------------------

class DocIR(BaseModel):
    """Canonical Document Intermediate Representation.

    This is the single machine-truth layer for parsed documents.
    All parser outputs normalize into this structure before any downstream
    knowledge extraction or wiki compilation occurs.

    Invariants:
    - All block_ids must be unique across the document.
    - reading_order must not repeat within the same page.
    - bbox values must be valid rectangles.
    - Unknown blocks must NOT be silently dropped.
    """

    # Identity
    doc_id: str = Field(description="Unique document IR identifier")
    source_id: str = Field(description="Link back to source registry record")
    source_uri: str = ""
    mime_type: str = "application/pdf"

    # Parser provenance
    parser: str = Field(description="Parser route name")
    parser_version: str = ""
    schema_version: str = Field(default="1", description="DocIR schema version")

    # Temporal
    created_at: datetime = Field(default_factory=datetime.now)

    # Document metadata
    language: list[str] = Field(default_factory=list)
    page_count: int = Field(ge=0)

    # Core structure
    pages: list[Page] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)

    # Quality signals
    warnings: list[DocIRWarning] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("blocks")
    @classmethod
    def _block_ids_unique(cls, v: list[Block]) -> list[Block]:
        seen: set[str] = set()
        for b in v:
            if b.block_id in seen:
                msg = f"Duplicate block_id: {b.block_id}"
                raise ValueError(msg)
            seen.add(b.block_id)
        return v
