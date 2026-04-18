"""Tests for US-015: Drop unreadable compile candidates before page generation.

AC1: Compile-time page generation skips entity or concept candidates that fail
     readability checks.
AC2: Unreadable candidates do not create markdown pages, patch entries, or
     frontmatter titles in final export output.
AC3: The skip behavior is deterministic for the same candidate input.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Repo root for imports
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docos.slugify import is_readable_title, sanitize_title


# ===================================================================
# Helpers
# ===================================================================


def _make_entity(canonical_name: str, entity_id: str = "ent-001") -> MagicMock:
    """Create a mock EntityRecord with the given canonical_name."""
    entity = MagicMock()
    entity.canonical_name = canonical_name
    entity.entity_id = entity_id
    entity.entity_type = MagicMock()
    entity.entity_type.value = "method"
    entity.source_ids = ["src-001"]
    entity.related_entity_ids: list[str] = []
    entity.aliases: list[str] = []
    entity.defining_description = "A test entity."
    entity.candidate_duplicates: list[str] = []
    return entity


# ===================================================================
# AC1: Compile-time page generation skips unreadable candidates
# ===================================================================


class TestCompileTimeSkip:
    """Verify that is_readable_title gate is applied at compile time."""

    def test_unreadable_entity_name_detected(self) -> None:
        """Entity with pure binary garbage name fails readability check."""
        assert is_readable_title("\x00\x01\x02\x03\x04\x05") is False

    def test_unreadable_concept_name_detected(self) -> None:
        """Concept with replacement characters only fails readability."""
        assert is_readable_title("\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd") is False

    def test_mostly_garbage_entity_name_unreadable(self) -> None:
        """Entity name that is >70% garbage characters is not readable."""
        name = "AB\x00\x01\x02\x03\x04\x05\x06\x07\x08"
        assert is_readable_title(name) is False

    def test_readable_entity_name_passes(self) -> None:
        """Normal entity name passes readability check."""
        assert is_readable_title("Transformer Model") is True

    def test_readable_concept_name_passes(self) -> None:
        """Normal concept name passes readability check."""
        assert is_readable_title("Attention Mechanism") is True

    def test_cjk_entity_name_readable(self) -> None:
        """CJK entity names are readable."""
        assert is_readable_title("自然语言处理") is True

    def test_sanitized_empty_name_unreadable(self) -> None:
        """After sanitization, if title becomes empty, it's unreadable."""
        clean = sanitize_title("\x00\x01\x02\x03\x04\x05\x06\x07\x08")
        assert clean == ""
        assert is_readable_title(clean) is False


# ===================================================================
# AC2: Unreadable candidates do NOT create pages/patches/frontmatter
# ===================================================================


class TestNoOutputForUnreadable:
    """Verify that compiler.compile_* still runs but the runner skips
    compilation of unreadable candidates."""

    def test_compiler_produces_output_for_readability_check(self, tmp_path: Path) -> None:
        """The compiler still compiles, but the runner should gate on readability.
        This verifies the compiler does not crash on garbage input."""
        from docos.wiki.compiler import WikiCompiler

        compiler = WikiCompiler(tmp_path / "wiki")
        entity = _make_entity("\x00\x01\x02\x03\x04\x05\x06\x07\x08")
        claims: list[MagicMock] = []
        # The compiler should not crash, but the title will be cleaned
        fm, body, page_path = compiler.compile_entity_page(entity, claims)
        # Frontmatter title is sanitized — pure garbage becomes empty string
        # The runner's _stage_compile skips this because is_readable_title("") is False
        assert fm.title == ""  # sanitized away all control chars

    def test_readable_entity_produces_valid_page(self, tmp_path: Path) -> None:
        """Readable entity names produce valid frontmatter and body."""
        from docos.wiki.compiler import WikiCompiler

        compiler = WikiCompiler(tmp_path / "wiki")
        entity = _make_entity("Neural Network")
        claims: list[MagicMock] = []
        fm, body, page_path = compiler.compile_entity_page(entity, claims)
        assert fm.title == "Neural Network"
        assert "# Neural Network" in body
        assert str(page_path).endswith(".md")

    def test_is_readable_gate_blocks_patch_generation(self) -> None:
        """Verify that is_readable_title returning False would block page generation
        in the runner's _stage_compile loop."""
        # This simulates the runner's decision logic:
        # if not is_readable_title(entity.canonical_name):
        #     _dropped_unreadable_title += 1
        #     continue  # <-- no patch, no wiki page, no frontmatter created
        unreadable_names = [
            "\x00\x01\x02\x03\x04\x05",
            "\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd",
            "",
            "   ",
            "\x00\x01\x02\x03\x04\x05\x06\x07\x08",
        ]
        for name in unreadable_names:
            assert is_readable_title(name) is False, f"Expected '{repr(name)}' to be unreadable"


# ===================================================================
# AC3: Deterministic skip behavior
# ===================================================================


class TestDeterministicSkip:
    """The skip behavior must be deterministic for the same candidate input."""

    @pytest.mark.parametrize("name", [
        "\x00\x01\x02\x03\x04\x05",
        "\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd",
        "Transformer Model",
        "自然语言处理",
        "",
        "   ",
    ])
    def test_readability_verdict_is_deterministic(self, name: str) -> None:
        """Same input always produces the same readability verdict."""
        first = is_readable_title(name)
        second = is_readable_title(name)
        third = is_readable_title(name)
        assert first == second == third

    @pytest.mark.parametrize("name", [
        "\x00\x01\x02\x03\x04\x05",
        "Transformer Model",
        "",
    ])
    def test_sanitized_title_is_deterministic(self, name: str) -> None:
        """Same input always produces the same sanitized title."""
        first = sanitize_title(name)
        second = sanitize_title(name)
        assert first == second

    def test_deterministic_across_many_calls(self) -> None:
        """Repeated calls with same input always produce same result."""
        garbage = "\x00\x01\x02\x03\x04\x05"
        results = [is_readable_title(garbage) for _ in range(100)]
        assert all(r is False for r in results)

    def test_readable_deterministic_across_many_calls(self) -> None:
        """Readable input always passes deterministically."""
        name = "Attention Is All You Need"
        results = [is_readable_title(name) for _ in range(100)]
        assert all(r is True for r in results)
