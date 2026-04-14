"""Parser backend interface — pluggable parser abstraction.

Every parser backend implements this common interface so that the
pipeline can route documents to any parser without knowing internals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from docos.models.docir import DocIR


# ---------------------------------------------------------------------------
# Parser capability metadata
# ---------------------------------------------------------------------------

class ParserCapability(str, Enum):
    """Capabilities a parser may declare."""

    TEXT_EXTRACTION = "text_extraction"
    LAYOUT_ANALYSIS = "layout_analysis"
    TABLE_DETECTION = "table_detection"
    FORMULA_DETECTION = "formula_detection"
    OCR = "ocr"
    READING_ORDER = "reading_order"
    FIGURE_DETECTION = "figure_detection"
    CAPTION_BINDING = "caption_binding"
    FOOTNOTE_BINDING = "footnote_binding"
    HEADER_FOOTER_DETECTION = "header_footer_detection"
    DUAL_COLUMN = "dual_column"
    CROSS_PAGE = "cross_page"


# ---------------------------------------------------------------------------
# Parser health status
# ---------------------------------------------------------------------------

@dataclass
class HealthStatus:
    """Health check result for a parser backend."""

    healthy: bool
    parser_name: str
    checked_at: datetime = field(default_factory=datetime.now)
    latency_ms: float | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Parse result
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    """Output from a single parser execution."""

    parser_name: str
    parser_version: str
    success: bool
    docir: DocIR | None = None
    raw_output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    elapsed_seconds: float = 0.0
    pages_parsed: int = 0
    blocks_extracted: int = 0
    warnings: list[str] = field(default_factory=list)
    debug_assets: dict[str, Path] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Debug assets config
# ---------------------------------------------------------------------------

@dataclass
class DebugConfig:
    """Configuration for debug asset generation."""

    output_dir: Path
    save_raw_output: bool = True
    save_page_images: bool = False
    save_block_overlays: bool = False
    save_reading_order: bool = False


# ---------------------------------------------------------------------------
# Abstract parser backend
# ---------------------------------------------------------------------------

class ParserBackend(ABC):
    """Abstract base class for all parser backends.

    Every parser must implement this interface. The pipeline calls
    these methods in a fixed order:

        1. healthcheck() — is the parser available?
        2. parse(file) — extract raw result from file
        3. normalize(raw_result) — convert to partial DocIR
        4. export_debug_assets(...) — persist debug artifacts

    Capabilities are declared statically and used by the router for
    route selection (no hidden prompt logic).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique parser name (e.g. 'pymupdf', 'marker', 'paddleocr')."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Parser version string."""

    @abstractmethod
    def capabilities(self) -> set[ParserCapability]:
        """Return the set of capabilities this parser supports."""

    @abstractmethod
    def parse(self, file_path: Path) -> ParseResult:
        """Execute parsing on a file.

        Args:
            file_path: Path to the source file.

        Returns:
            ParseResult with raw_output populated and success flag.
        """

    @abstractmethod
    def normalize(self, result: ParseResult) -> DocIR:
        """Normalize parser-specific raw output into canonical DocIR.

        Args:
            result: The ParseResult from parse().

        Returns:
            A (possibly partial) DocIR conforming to the canonical schema.
        """

    def export_debug_assets(self, result: ParseResult, config: DebugConfig) -> dict[str, Path]:
        """Export debug assets for inspection.

        Default implementation saves raw output as JSON.
        Override for parser-specific assets (screenshots, overlays, etc.).

        Args:
            result: The ParseResult to export.
            config: Debug configuration.

        Returns:
            Mapping of asset name → file path.
        """
        assets: dict[str, Path] = {}
        config.output_dir.mkdir(parents=True, exist_ok=True)

        if config.save_raw_output and result.raw_output:
            import json
            raw_path = config.output_dir / "raw_output.json"
            raw_path.write_text(
                json.dumps(result.raw_output, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
            assets["raw_output"] = raw_path

        return assets

    @abstractmethod
    def healthcheck(self) -> HealthStatus:
        """Check if the parser is available and responsive.

        Returns:
            HealthStatus with healthy=True if the parser can accept work.
        """


# ---------------------------------------------------------------------------
# Registry of parser backends
# ---------------------------------------------------------------------------

class ParserRegistry:
    """Registry of available parser backends.

    Parsers register themselves by name. The router looks them up
    when constructing a parser plan.
    """

    def __init__(self) -> None:
        self._backends: dict[str, ParserBackend] = {}

    def register(self, backend: ParserBackend) -> None:
        self._backends[backend.name] = backend

    def get(self, name: str) -> ParserBackend | None:
        return self._backends.get(name)

    def list_parsers(self) -> list[str]:
        return list(self._backends.keys())

    def all_healthy(self) -> dict[str, HealthStatus]:
        return {name: b.healthcheck() for name, b in self._backends.items()}
