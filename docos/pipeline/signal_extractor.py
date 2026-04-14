"""Signal Extractor — deterministic document signal extraction from raw sources.

Extracts factual signals from source files for route selection.
No LLM involvement — all extraction is deterministic and file-based.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from dataclasses import asdict
from pathlib import Path

from docos.pipeline.router import DocumentSignals


# ---------------------------------------------------------------------------
# MIME type mapping
# ---------------------------------------------------------------------------

_EXTENSION_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".epub": "application/epub+zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


class SignalExtractor:
    """Extract deterministic document signals from a source file.

    All signals are derived from file-level inspection. Running extraction
    twice on the same unchanged file returns identical signal values.
    """

    def extract(self, file_path: Path) -> DocumentSignals:
        """Extract signals from a source file.

        Args:
            file_path: Path to the source file.

        Returns:
            DocumentSignals with all fields populated.
        """
        if not file_path.exists():
            msg = f"Source file not found: {file_path}"
            raise FileNotFoundError(msg)

        mime_type = self._detect_mime(file_path)
        page_count = self._detect_page_count(file_path, mime_type)
        is_scanned = self._detect_scanned(file_path, mime_type)
        needs_ocr = self._detect_ocr_need(file_path, mime_type, is_scanned)
        is_dual_column = self._detect_dual_column(file_path, mime_type)
        is_table_heavy = self._detect_table_heavy(file_path, mime_type)
        is_formula_heavy = self._detect_formula_heavy(file_path, mime_type)
        is_image_heavy = self._detect_image_heavy(file_path, mime_type)
        language = self._detect_language(file_path, mime_type)
        target_mode = self._detect_target_mode(file_path, mime_type, page_count)
        known_failure_hints = self._detect_known_failures(file_path, mime_type)

        return DocumentSignals(
            file_type=mime_type,
            page_count=page_count,
            is_scanned=is_scanned,
            is_dual_column=is_dual_column,
            is_table_heavy=is_table_heavy,
            is_formula_heavy=is_formula_heavy,
            is_image_heavy=is_image_heavy,
            language=language,
            needs_ocr=needs_ocr,
            has_known_failures=len(known_failure_hints) > 0,
            target_mode=target_mode,
        )

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _detect_mime(self, file_path: Path) -> str:
        """Detect MIME type from extension and file content."""
        ext = file_path.suffix.lower()
        # Check explicit mapping first
        if ext in _EXTENSION_MIME:
            return _EXTENSION_MIME[ext]
        # Fall back to mimetypes module
        guessed, _ = mimetypes.guess_type(str(file_path))
        return guessed or "application/octet-stream"

    def _detect_page_count(self, file_path: Path, mime_type: str) -> int:
        """Detect page count from file content."""
        if mime_type == "application/pdf":
            return self._pdf_page_count(file_path)
        if mime_type in ("text/plain", "text/markdown"):
            # Approximate: count form feeds or estimate from line count
            content = file_path.read_text(encoding="utf-8", errors="replace")
            ff_count = content.count("\x0c")
            return max(1, ff_count) if ff_count > 0 else 1
        # Single page for images, unknown formats
        return 1

    def _pdf_page_count(self, file_path: Path) -> int:
        """Extract page count from PDF binary content."""
        try:
            raw = file_path.read_bytes()
            # Method 1: look for /Count in the PDF trailer
            count_matches = re.findall(rb"/Type\s*/Pages\s.*?/Count\s+(\d+)", raw, re.DOTALL)
            if count_matches:
                return int(count_matches[-1])
            # Method 2: count /Type /Page entries (not /Pages)
            page_matches = re.findall(rb"/Type\s*/Page[^s]", raw)
            return max(1, len(page_matches))
        except Exception:
            return 1

    def _detect_scanned(self, file_path: Path, mime_type: str) -> bool:
        """Detect if a PDF is scanned (image-based)."""
        if mime_type != "application/pdf":
            return False
        try:
            raw = file_path.read_bytes()
            # Heuristic: scanned PDFs have very high ratio of image streams to text
            image_streams = len(re.findall(rb"/Subtype\s*/Image", raw))
            text_objects = len(re.findall(rb"/Subtype\s*/Form", raw))
            # If there are many image streams relative to the file, likely scanned
            byte_size = len(raw)
            if byte_size > 0 and image_streams > 0:
                # Scanned PDFs typically have large image streams
                image_sizes = re.findall(rb"/Length\s+(\d+)", raw)
                total_image_est = sum(int(s) for s in image_sizes[:image_streams])
                if total_image_est > byte_size * 0.7:
                    return True
            return image_streams > 3 and text_objects == 0
        except Exception:
            return False

    def _detect_ocr_need(self, file_path: Path, mime_type: str, is_scanned: bool) -> bool:
        """Detect if OCR is needed."""
        if mime_type.startswith("image/"):
            return True
        if is_scanned:
            return True
        return False

    def _detect_dual_column(self, file_path: Path, mime_type: str) -> bool:
        """Detect dual-column layout (heuristic)."""
        # Without a full PDF parser, this is a conservative heuristic
        # based on file size vs page count ratio
        if mime_type != "application/pdf":
            return False
        page_count = self._pdf_page_count(file_path)
        if page_count <= 0:
            return False
        byte_size = file_path.stat().st_size
        # Academic PDFs tend to be larger per page in dual-column format
        bytes_per_page = byte_size / page_count
        # Rough heuristic: dual-column PDFs often have denser text
        # This is intentionally conservative (returns None-like=False)
        return False

    def _detect_table_heavy(self, file_path: Path, mime_type: str) -> bool:
        """Detect if a PDF is table-heavy."""
        if mime_type != "application/pdf":
            return False
        try:
            raw = file_path.read_bytes()
            # Count table-like structures
            table_markers = len(re.findall(rb"/Type\s*/Table", raw))
            # Also check for grid-like patterns in content streams
            col_specs = len(re.findall(rb"Td\s", raw))
            # Heuristic: many Td (text positioning) operations suggest tables
            page_count = self._pdf_page_count(file_path)
            if page_count > 0 and col_specs > page_count * 50:
                return True
            return table_markers > 2
        except Exception:
            return False

    def _detect_formula_heavy(self, file_path: Path, mime_type: str) -> bool:
        """Detect if a PDF contains mathematical formulas."""
        if mime_type != "application/pdf":
            return False
        try:
            raw = file_path.read_bytes()
            # Look for common PDF formula indicators
            formula_markers = 0
            # Math fonts (MiSymbol, CMMI, etc.)
            formula_markers += len(re.findall(rb"(/F\d+\s+\d+\s+Tf).*?[a-z]", raw))
            # Superscript/subscript positioning
            formula_markers += len(re.findall(rb"Ts\s", raw))
            page_count = self._pdf_page_count(file_path)
            if page_count > 0:
                return formula_markers > page_count * 10
            return formula_markers > 20
        except Exception:
            return False

    def _detect_image_heavy(self, file_path: Path, mime_type: str) -> bool:
        """Detect if a PDF is image-heavy."""
        if mime_type.startswith("image/"):
            return True
        if mime_type != "application/pdf":
            return False
        try:
            raw = file_path.read_bytes()
            image_streams = len(re.findall(rb"/Subtype\s*/Image", raw))
            page_count = self._pdf_page_count(file_path)
            if page_count > 0:
                return image_streams > page_count * 3
            return image_streams > 5
        except Exception:
            return False

    def _detect_language(self, file_path: Path, mime_type: str) -> str:
        """Detect document language (basic heuristic)."""
        if mime_type in ("application/pdf",):
            try:
                # Extract some text from PDF for language detection
                raw = file_path.read_bytes()
                # Find text between parentheses in content streams (simplified)
                text_parts = re.findall(rb"\(([^)]+)\)", raw)
                sample = b" ".join(text_parts[:50]).decode("latin-1", errors="replace")
                return self._classify_language(sample)
            except Exception:
                return "unknown"
        if mime_type in ("text/plain", "text/markdown"):
            try:
                sample = file_path.read_text(encoding="utf-8", errors="replace")[:2000]
                return self._classify_language(sample)
            except Exception:
                return "unknown"
        return "unknown"

    def _classify_language(self, text: str) -> str:
        """Simple language classification from text sample."""
        # CJK detection
        cjk_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        if cjk_count > len(text) * 0.1:
            return "zh"
        # Japanese hiragana/katakana
        jp_count = sum(1 for c in text if "\u3040" <= c <= "\u30ff")
        if jp_count > len(text) * 0.1:
            return "ja"
        # Korean
        kr_count = sum(1 for c in text if "\uac00" <= c <= "\ud7af")
        if kr_count > len(text) * 0.1:
            return "ko"
        return "en"

    def _detect_target_mode(self, file_path: Path, mime_type: str, page_count: int) -> str:
        """Detect recommended processing mode."""
        byte_size = file_path.stat().st_size
        # Large files or many pages → high throughput
        if page_count > 100 or byte_size > 50 * 1024 * 1024:
            return "high_throughput"
        # Small text files → low cost
        if mime_type in ("text/plain", "text/markdown"):
            return "low_cost"
        return "high_fidelity"

    def _detect_known_failures(self, file_path: Path, mime_type: str) -> list[str]:
        """Detect known failure patterns."""
        hints: list[str] = []
        if mime_type == "application/pdf":
            try:
                raw = file_path.read_bytes()
                # Encrypted PDF
                if rb"/Encrypt" in raw:
                    hints.append("encrypted_pdf")
                # Corrupted header
                if not raw.startswith(b"%PDF"):
                    hints.append("invalid_pdf_header")
                # Very large single-page
                page_count = self._pdf_page_count(file_path)
                if page_count == 1 and len(raw) > 100 * 1024 * 1024:
                    hints.append("oversized_single_page")
            except Exception:
                hints.append("unreadable")
        return hints


def signals_to_dict(signals: DocumentSignals) -> dict[str, object]:
    """Serialize DocumentSignals to a JSON-compatible dict."""
    return asdict(signals)


def signals_from_dict(data: dict[str, object]) -> DocumentSignals:
    """Deserialize DocumentSignals from a dict."""
    return DocumentSignals(**data)  # type: ignore[arg-type]
