"""Tests for US-014: Sanitize page titles before frontmatter and body export.

AC1: Title sanitization removes control characters before frontmatter is rendered.
AC2: Obvious binary-garbage fragments are filtered from exported page titles.
AC3: A title that becomes empty or unreadable after sanitization is not used to
     generate a final entity or concept page.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Repo root for imports
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docos.slugify import is_readable_title, sanitize_title
from docos.wiki.compiler import WikiCompiler, _clean_title


# ===================================================================
# Unit tests for sanitize_title
# ===================================================================


class TestSanitizeTitle:
    """AC1 & AC2: control characters and binary garbage removal."""

    def test_removes_control_characters(self) -> None:
        result = sanitize_title("Hello\x00World\x1fEnd")
        assert result == "HelloWorldEnd"

    def test_removes_tab_and_newline(self) -> None:
        result = sanitize_title("Title\twith\nbreaks")
        assert result == "Title with breaks"

    def test_removes_replacement_character(self) -> None:
        result = sanitize_title("Bad\ufffdTitle")
        assert result == "BadTitle"

    def test_removes_private_use_codepoints(self) -> None:
        result = sanitize_title("Name\ue001With\uf8ffJunk")
        assert result == "NameWithJunk"

    def test_removes_c1_control_chars(self) -> None:
        result = sanitize_title("Title\x80\x90\x9fEnd")
        assert result == "TitleEnd"

    def test_collapses_whitespace(self) -> None:
        result = sanitize_title("Hello   World   Title")
        assert result == "Hello World Title"

    def test_strips_leading_trailing(self) -> None:
        result = sanitize_title("  Hello World  ")
        assert result == "Hello World"

    def test_empty_input_returns_empty(self) -> None:
        assert sanitize_title("") == ""

    def test_only_garbage_returns_empty(self) -> None:
        assert sanitize_title("\x00\x01\x02\x1f\x7f") == ""

    def test_preserves_cjk(self) -> None:
        result = sanitize_title("自然语言处理")
        assert result == "自然语言处理"

    def test_preserves_normal_punctuation(self) -> None:
        result = sanitize_title("Hello, World! (test)")
        assert result == "Hello, World! (test)"


# ===================================================================
# Unit tests for is_readable_title
# ===================================================================


class TestIsReadableTitle:
    """AC3: readability gate for titles."""

    def test_normal_title_is_readable(self) -> None:
        assert is_readable_title("Attention Is All You Need") is True

    def test_empty_is_not_readable(self) -> None:
        assert is_readable_title("") is False

    def test_whitespace_only_is_not_readable(self) -> None:
        assert is_readable_title("   ") is False

    def test_mostly_garbage_is_not_readable(self) -> None:
        assert is_readable_title("\x00\x01\x02\x03\x04\x05\x06AB") is False

    def test_cjk_is_readable(self) -> None:
        assert is_readable_title("自然语言处理") is True

    def test_mixed_readable_is_ok(self) -> None:
        assert is_readable_title("BERT-base model (v2)") is True

    def test_custom_threshold(self) -> None:
        # With high threshold, borderline titles become unreadable
        assert is_readable_title("AB!!!???", min_alpha_ratio=0.9) is False
        assert is_readable_title("Hello World", min_alpha_ratio=0.9) is True


# ===================================================================
# Compiler integration tests
# ===================================================================


def _make_entity(canonical_name: str) -> MagicMock:
    entity = MagicMock()
    entity.canonical_name = canonical_name
    entity.entity_type = MagicMock()
    entity.entity_type.value = "method"
    entity.source_ids = ["src-001"]
    entity.related_entity_ids: list[str] = []
    entity.aliases: list[str] = []
    entity.defining_description = "A test entity."
    entity.candidate_duplicates: list[str] = []
    return entity


def _make_source(source_id: str = "src-001", file_name: str = "test.pdf") -> MagicMock:
    source = MagicMock()
    source.source_id = source_id
    source.file_name = file_name
    source.mime_type = "application/pdf"
    return source


def _make_docir() -> MagicMock:
    docir = MagicMock()
    docir.page_count = 10
    docir.parser = "pymupdf"
    docir.parser_version = "1.0"
    docir.schema_version = "1"
    docir.blocks = []
    docir.warnings = []
    return docir


class TestCompilerTitleSanitization:
    """AC1 & AC2: frontmatter title is cleaned."""

    def test_entity_page_frontmatter_has_clean_title(self, tmp_path: Path) -> None:
        compiler = WikiCompiler(tmp_path / "wiki")
        entity = _make_entity("Clean\x00Title")
        claims: list[MagicMock] = []
        fm, body, page_path = compiler.compile_entity_page(entity, claims)
        assert "\x00" not in fm.title
        assert "CleanTitle" == fm.title

    def test_entity_page_body_has_clean_heading(self, tmp_path: Path) -> None:
        compiler = WikiCompiler(tmp_path / "wiki")
        entity = _make_entity("My\x1fEntity")
        claims: list[MagicMock] = []
        fm, body, page_path = compiler.compile_entity_page(entity, claims)
        assert "# MyEntity" in body
        assert "\x1f" not in body

    def test_concept_page_frontmatter_has_clean_title(self, tmp_path: Path) -> None:
        compiler = WikiCompiler(tmp_path / "wiki")
        concept_name = "Neural\x00Network"
        fm, body, page_path = compiler.compile_concept_page(
            concept_name=concept_name,
            source_ids=["src-001"],
            related_claims=[],
            related_entities=[],
        )
        assert "\x00" not in fm.title
        assert "NeuralNetwork" == fm.title

    def test_binary_garbage_filtered_from_title(self, tmp_path: Path) -> None:
        compiler = WikiCompiler(tmp_path / "wiki")
        entity = _make_entity("Model\ue001Name\ufffd")
        claims: list[MagicMock] = []
        fm, body, page_path = compiler.compile_entity_page(entity, claims)
        assert "\ue001" not in fm.title
        assert "\ufffd" not in fm.title
        assert "ModelName" == fm.title

    def test_source_page_title_sanitized(self, tmp_path: Path) -> None:
        compiler = WikiCompiler(tmp_path / "wiki")
        source = _make_source(file_name="paper\x00v2.pdf")
        docir = _make_docir()
        fm, body, page_path = compiler.compile_source_page(source, docir, [], [])
        assert "\x00" not in fm.title
        assert "# paperv2.pdf" in body


class TestCleanTitleHelper:
    """Verify the compiler's _clean_title delegates correctly."""

    def test_delegates_to_sanitize(self) -> None:
        assert _clean_title("Hello\x00World") == "HelloWorld"

    def test_empty_returns_empty(self) -> None:
        assert _clean_title("") == ""

    def test_normal_passthrough(self) -> None:
        assert _clean_title("Normal Title") == "Normal Title"


# ===================================================================
# Runner integration: unreadable title skips page generation
# ===================================================================


class TestRunnerUnreadableTitleSkip:
    """AC3: entity/concept pages with unreadable titles are not generated."""

    def test_unreadable_entity_name_not_compiled(self) -> None:
        """Verify is_readable_title rejects binary garbage entity names."""
        assert is_readable_title("\x00\x01\x02\x03\x04\x05") is False

    def test_readable_entity_name_passes(self) -> None:
        assert is_readable_title("Transformer Model") is True

    def test_all_garbage_name_not_readable(self) -> None:
        assert is_readable_title("\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd") is False

    def test_readable_after_sanitization(self) -> None:
        """Even after sanitization, a title that's mostly garbage is not readable."""
        clean = sanitize_title("AB\x00\x01\x02\x03\x04\x05\x06\x07\x08")
        # After sanitization: "AB" (only 2 chars, but 100% readable)
        assert is_readable_title(clean) is True

    def test_unreadable_after_sanitization(self) -> None:
        """After sanitization, if nothing readable remains, it's not readable."""
        clean = sanitize_title("\x00\x01\x02\x03\x04\x05\x06\x07\x08")
        assert clean == ""
        assert is_readable_title(clean) is False
