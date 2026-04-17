"""Tests for US-012: deterministic ASCII-safe slug sanitizer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is importable.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docos.slugify import slugify


# ---------------------------------------------------------------------------
# AC1: All wiki page paths go through one deterministic sanitizer
# ---------------------------------------------------------------------------


class TestCanonicalSanitizerPath:
    """Verify compiler delegates slug generation to docos.slugify.slugify."""

    def test_compiler_slug_delegates_to_slugify(self) -> None:
        """_slug in compiler.py delegates to docos.slugify.slugify."""
        from docos.wiki.compiler import _slug

        assert _slug("Hello World") == slugify("Hello World")

    def test_compiler_slug_matches_slugify_unicode(self) -> None:
        """_slug handles unicode identically to slugify."""
        from docos.wiki.compiler import _slug

        assert _slug("Ünïcödé Tëst") == slugify("Ünïcödé Tëst")


# ---------------------------------------------------------------------------
# AC2: Sanitized slugs contain only safe ASCII characters
# ---------------------------------------------------------------------------


class TestASCIISafeSlugs:
    """Slugs contain only [a-z0-9-] and no control characters."""

    @pytest.mark.parametrize(
        "input_text",
        [
            "Hello World",
            "Test/Path\\Here",
            "file (1).txt",
            "café résumé",
            "Hello\x00World\x1f!",
            "foo\x7fbar",
        ],
    )
    def test_slug_only_contains_safe_chars(self, input_text: str) -> None:
        result = slugify(input_text)
        # Safe chars: a-z, 0-9, hyphen
        import re

        assert re.fullmatch(r"[a-z0-9-]*", result), (
            f"Slug '{result}' contains unsafe characters"
        )

    def test_control_characters_removed(self) -> None:
        """Control characters \\x00-\\x1f and \\x7f are excluded."""
        result = slugify("hello\x00\x01\x1f\x7fworld")
        # Control chars are stripped (not replaced with hyphens).
        assert result == "helloworld"
        assert "\x00" not in result
        assert "\x1f" not in result
        assert "\x7f" not in result

    def test_unicode_decomposed_to_ascii(self) -> None:
        """Non-ASCII characters are decomposed to ASCII base where possible."""
        result = slugify("café")
        assert result == "cafe"
        assert "é" not in result

    def test_empty_fallback(self) -> None:
        """Input that yields no safe characters returns 'untitled'."""
        result = slugify("!!!")
        assert result == "untitled"

    def test_spaces_replaced_with_hyphens(self) -> None:
        result = slugify("hello world")
        assert result == "hello-world"
        assert " " not in result


# ---------------------------------------------------------------------------
# AC3: Deterministic — same input produces same output
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Slug generation is deterministic across calls."""

    @pytest.mark.parametrize(
        "input_text",
        [
            "Hello World",
            "Test Title 123",
            "café résumé",
            "  leading and trailing  ",
            "multiple   spaces   here",
        ],
    )
    def test_same_input_same_output(self, input_text: str) -> None:
        results = [slugify(input_text) for _ in range(10)]
        assert len(set(results)) == 1, f"Non-deterministic for '{input_text}': {set(results)}"

    def test_different_inputs_different_slugs(self) -> None:
        """Different inputs produce different slugs (when they differ meaningfully)."""
        assert slugify("Foo") != slugify("Bar")

    def test_case_insensitive_determinism(self) -> None:
        """Title-case and lowercase produce same slug."""
        assert slugify("Hello World") == slugify("hello world")

    def test_max_length_truncation_deterministic(self) -> None:
        result1 = slugify("a" * 200, max_length=50)
        result2 = slugify("a" * 200, max_length=50)
        assert result1 == result2
        assert len(result1) <= 50
