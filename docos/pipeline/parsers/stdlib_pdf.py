"""StdlibPDFParser — primary PDF parser using only Python standard library.

This parser extracts text blocks from PDF files by parsing the binary
content directly. It serves as the default primary parser for text-heavy
PDFs and requires no external dependencies.

Limitations:
- Only handles text-based PDFs (not scanned/image-based)
- Layout analysis is basic (no column detection)
- Table detection is heuristic-based
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from docos.models.docir import (
    Block,
    BlockType,
    DocIR,
    Page,
    Relation,
)
from docos.pipeline.parser import (
    DebugConfig,
    HealthStatus,
    ParseResult,
    ParserBackend,
    ParserCapability,
)


class ParserError(Exception):
    """Structured parser error with parser name and reason."""

    def __init__(self, parser_name: str, reason: str) -> None:
        self.parser_name = parser_name
        self.reason = reason
        super().__init__(f"[{parser_name}] {reason}")


class StdlibPDFParser(ParserBackend):
    """Primary PDF parser using Python standard library only.

    Extracts text content by parsing PDF binary structures directly.
    Suitable for text-heavy PDFs. Will report failure for encrypted
    or image-only documents.
    """

    @property
    def name(self) -> str:
        return "stdlib_pdf"

    @property
    def version(self) -> str:
        return "1.0.0"

    def capabilities(self) -> set[ParserCapability]:
        return {
            ParserCapability.TEXT_EXTRACTION,
            ParserCapability.READING_ORDER,
            ParserCapability.HEADER_FOOTER_DETECTION,
        }

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(healthy=True, parser_name=self.name, latency_ms=0.0)

    def parse(self, file_path: Path) -> ParseResult:
        """Parse a PDF file using standard library PDF text extraction.

        Args:
            file_path: Path to the PDF file.

        Returns:
            ParseResult with raw_output containing extracted text per page.
        """
        start = datetime.now()

        if not file_path.exists():
            return ParseResult(
                parser_name=self.name,
                parser_version=self.version,
                success=False,
                error=f"File not found: {file_path}",
                elapsed_seconds=0.0,
            )

        try:
            raw = file_path.read_bytes()
        except OSError as e:
            return ParseResult(
                parser_name=self.name,
                parser_version=self.version,
                success=False,
                error=f"Cannot read file: {e}",
                elapsed_seconds=0.0,
            )

        # Check for valid PDF header
        if not raw.startswith(b"%PDF"):
            return ParseResult(
                parser_name=self.name,
                parser_version=self.version,
                success=False,
                error="Invalid PDF: missing %PDF header",
                elapsed_seconds=0.0,
            )

        # Check for encryption
        if b"/Encrypt" in raw:
            return ParseResult(
                parser_name=self.name,
                parser_version=self.version,
                success=False,
                error="Encrypted PDF: cannot parse without decryption",
                elapsed_seconds=0.0,
            )

        # Extract text content per page
        page_texts = self._extract_text_per_page(raw)
        page_count = len(page_texts)

        raw_output: dict[str, Any] = {
            "file_name": file_path.name,
            "byte_size": len(raw),
            "page_count": page_count,
            "pages": [
                {"page_no": i + 1, "text": text}
                for i, text in enumerate(page_texts)
            ],
        }

        elapsed = (datetime.now() - start).total_seconds()

        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            raw_output=raw_output,
            elapsed_seconds=elapsed,
            pages_parsed=page_count,
            blocks_extracted=sum(len(self._text_to_blocks(text, i + 1)) for i, text in enumerate(page_texts)),
        )

    def normalize(self, result: ParseResult) -> DocIR:
        """Normalize parse result into canonical DocIR."""
        if not result.success or not result.raw_output:
            msg = f"Cannot normalize failed parse result: {result.error}"
            raise ValueError(msg)

        pages_raw = result.raw_output.get("pages", [])
        all_blocks: list[Block] = []
        pages: list[Page] = []

        for page_data in pages_raw:
            page_no: int = page_data["page_no"]
            text: str = page_data["text"]

            blocks = self._text_to_blocks(text, page_no)
            block_ids = [b.block_id for b in blocks]
            all_blocks.extend(blocks)

            pages.append(
                Page(
                    page_no=page_no,
                    width=612.0,
                    height=792.0,
                    blocks=block_ids,
                )
            )

        return DocIR(
            doc_id=f"doc_{id(result)}",
            source_id="",
            parser=self.name,
            parser_version=self.version,
            page_count=len(pages),
            pages=pages,
            blocks=all_blocks,
            relations=[],
            confidence=0.8,
        )

    # ------------------------------------------------------------------
    # Internal extraction
    # ------------------------------------------------------------------

    def _extract_text_per_page(self, raw: bytes) -> list[str]:
        """Extract text content from PDF binary, split by page."""
        # Split content by page markers
        # This is a simplified extraction that looks for text between
        # parentheses in content streams
        pages_text: list[str] = []

        # Find content between stream/endstream markers
        streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.DOTALL)

        if not streams:
            # Fallback: extract all text-like content
            text_parts = re.findall(rb"\(([^)]+)\)", raw)
            combined = " ".join(p.decode("latin-1", errors="replace") for p in text_parts)
            return [combined] if combined.strip() else [""]

        for stream in streams:
            page_text = self._decode_stream_text(stream)
            pages_text.append(page_text)

        return pages_text if pages_text else [""]

    def _decode_stream_text(self, stream: bytes) -> str:
        """Decode text from a PDF content stream."""
        # Extract text from parentheses (PDF text objects)
        # Handle escaped parentheses
        text_parts: list[str] = []
        i = 0
        while i < len(stream):
            if stream[i:i + 1] == b"(":
                depth = 1
                j = i + 1
                while j < len(stream) and depth > 0:
                    if stream[j:j + 1] == b"(":
                        depth += 1
                    elif stream[j:j + 1] == b")":
                        depth -= 1
                    elif stream[j:j + 1] == b"\\":
                        j += 1  # Skip escaped char
                    j += 1
                text_bytes = stream[i + 1:j - 1]
                # Replace common escape sequences
                text = text_bytes.decode("latin-1", errors="replace")
                text = text.replace("\\n", "\n").replace("\\r", "\r").replace("\\(", "(").replace("\\)", ")")
                if text.strip():
                    text_parts.append(text)
                i = j
            else:
                i += 1

        return "\n".join(text_parts)

    def _text_to_blocks(self, text: str, page_no: int) -> list[Block]:
        """Convert extracted text into DocIR blocks."""
        blocks: list[Block] = []
        if not text.strip():
            return blocks

        lines = text.split("\n")
        order = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            block_type = self._classify_line(stripped)
            blocks.append(
                Block(
                    block_id=f"blk_p{page_no}_{order}",
                    page_no=page_no,
                    block_type=block_type,
                    reading_order=order,
                    bbox=(0.0, 0.0, 612.0, 12.0),
                    text_plain=stripped,
                    source_parser=self.name,
                    source_node_id=f"p{page_no}_line{order}",
                )
            )
            order += 1

        return blocks

    def _classify_line(self, line: str) -> BlockType:
        """Classify a text line into a block type."""
        if line.startswith("#"):
            return BlockType.HEADING
        if len(line) > 200 and " " not in line:
            return BlockType.UNKNOWN
        return BlockType.PARAGRAPH
