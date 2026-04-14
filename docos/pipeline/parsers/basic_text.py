"""BasicTextFallbackParser — fallback PDF parser for basic text extraction.

A simpler, more robust parser that serves as a fallback when the primary
parser fails. Uses minimal PDF structure parsing with aggressive error recovery.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from docos.models.docir import Block, BlockType, DocIR, Page
from docos.pipeline.parser import (
    HealthStatus,
    ParseResult,
    ParserBackend,
    ParserCapability,
)


class BasicTextFallbackParser(ParserBackend):
    """Fallback PDF parser — robust basic text extraction.

    This parser is intentionally simpler than StdlibPDFParser.
    It focuses on extracting any readable text from a PDF, even if
    the structure is damaged or unusual.
    """

    @property
    def name(self) -> str:
        return "basic_text_fallback"

    @property
    def version(self) -> str:
        return "1.0.0"

    def capabilities(self) -> set[ParserCapability]:
        return {ParserCapability.TEXT_EXTRACTION}

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(healthy=True, parser_name=self.name, latency_ms=0.0)

    def parse(self, file_path: Path) -> ParseResult:
        """Parse PDF with aggressive text recovery."""
        start = datetime.now()

        if not file_path.exists():
            return ParseResult(
                parser_name=self.name,
                parser_version=self.version,
                success=False,
                error=f"File not found: {file_path}",
            )

        try:
            raw = file_path.read_bytes()
        except OSError as e:
            return ParseResult(
                parser_name=self.name,
                parser_version=self.version,
                success=False,
                error=f"Cannot read file: {e}",
            )

        # Aggressive text extraction — grab anything that looks like text
        text_parts = re.findall(rb"\(([^)]{1,500})\)", raw)
        all_text = "\n".join(p.decode("latin-1", errors="replace") for p in text_parts if p.strip())

        # Even if no text in parens, try to extract printable ASCII
        if not all_text.strip():
            printable = re.findall(rb"[\x20-\x7e]{4,}", raw)
            all_text = "\n".join(p.decode("ascii", errors="replace") for p in printable[:100])

        raw_output: dict[str, Any] = {
            "file_name": file_path.name,
            "byte_size": len(raw),
            "extracted_text": all_text,
            "text_length": len(all_text),
        }

        elapsed = (datetime.now() - start).total_seconds()

        # Succeed even with empty text — better than failing silently
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            raw_output=raw_output,
            elapsed_seconds=elapsed,
            pages_parsed=1,
            blocks_extracted=len(all_text.split("\n")) if all_text.strip() else 0,
        )

    def normalize(self, result: ParseResult) -> DocIR:
        """Normalize into a simple single-page DocIR."""
        if not result.success or not result.raw_output:
            msg = f"Cannot normalize failed result: {result.error}"
            raise ValueError(msg)

        text: str = result.raw_output.get("extracted_text", "")
        blocks: list[Block] = []
        block_ids: list[str] = []

        for i, line in enumerate(text.split("\n")):
            if not line.strip():
                continue
            bid = f"blk_p1_{i}"
            blocks.append(
                Block(
                    block_id=bid,
                    page_no=1,
                    block_type=BlockType.PARAGRAPH,
                    reading_order=i,
                    bbox=(0.0, 0.0, 612.0, 12.0),
                    text_plain=line.strip(),
                    source_parser=self.name,
                    source_node_id=f"p1_line{i}",
                )
            )
            block_ids.append(bid)

        return DocIR(
            doc_id=f"doc_fallback_{id(result)}",
            source_id="",
            parser=self.name,
            parser_version=self.version,
            page_count=1,
            pages=[Page(page_no=1, width=612.0, height=792.0, blocks=block_ids)],
            blocks=blocks,
            relations=[],
            confidence=0.5,  # Lower confidence for fallback
        )
