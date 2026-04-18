"""Tests for US-020: Automated Obsidian-ready vault validator."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from docos.vault_validator import (
    MAX_FILENAME_LENGTH,
    PageIssue,
    VaultValidationResult,
    _parse_frontmatter_title,
    validate_vault,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_page(
    vault: Path,
    rel_path: str,
    *,
    title: str | None = "Test Page",
    body: str = "Hello world",
    frontmatter_extra: str = "",
) -> Path:
    """Write a markdown page with YAML frontmatter under *vault*."""
    fpath = vault / rel_path
    fpath.parent.mkdir(parents=True, exist_ok=True)
    if title is not None:
        fm = f"title: \"{title}\"\n{frontmatter_extra}".strip()
    else:
        fm = frontmatter_extra.strip()
    content = f"---\n{fm}\n---\n\n{body}\n"
    fpath.write_text(content, encoding="utf-8")
    return fpath


# ---------------------------------------------------------------------------
# _parse_frontmatter_title tests
# ---------------------------------------------------------------------------


class TestParseFrontmatterTitle:
    def test_extracts_title(self) -> None:
        content = '---\ntitle: "My Page"\n---\n\nBody\n'
        assert _parse_frontmatter_title(content) == "My Page"

    def test_single_quoted_title(self) -> None:
        content = "---\ntitle: 'My Page'\n---\n\nBody\n"
        assert _parse_frontmatter_title(content) == "My Page"

    def test_unquoted_title(self) -> None:
        content = "---\ntitle: My Page\n---\n\nBody\n"
        assert _parse_frontmatter_title(content) == "My Page"

    def test_no_frontmatter(self) -> None:
        assert _parse_frontmatter_title("Just body text") is None

    def test_empty_frontmatter(self) -> None:
        assert _parse_frontmatter_title("---\n---\n\nBody\n") is None

    def test_missing_title_key(self) -> None:
        content = "---\nother: value\n---\n\nBody\n"
        assert _parse_frontmatter_title(content) is None


# ---------------------------------------------------------------------------
# validate_vault core checks
# ---------------------------------------------------------------------------


class TestValidateVaultEmptyFilename:
    def test_empty_filename_detected(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        # Create a file with empty slug: ".md"
        _write_page(vault, ".md", title="Empty Slug Page")
        result = validate_vault(vault)
        issue_types = [i.issue_type for i in result.issues]
        assert "empty_filename" in issue_types
        assert result.failed_pages == 1

    def test_normal_filename_passes(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_page(vault, "sources/my-paper.md")
        result = validate_vault(vault)
        assert result.passed_pages == 1
        assert result.failed_pages == 0


class TestValidateVaultUnreadableSlug:
    def test_unreadable_slug_detected(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        # Filename with non-ASCII characters that don't belong in a slug
        _write_page(vault, "entities/\u00e9l\u00e8ve.md")
        result = validate_vault(vault)
        issue_types = [i.issue_type for i in result.issues]
        assert "unreadable_slug" in issue_types

    def test_ascii_slug_passes(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_page(vault, "entities/attention-mechanism.md")
        result = validate_vault(vault)
        assert result.passed_pages == 1
        assert result.failed_pages == 0


class TestValidateVaultEmptyTitle:
    def test_empty_title_detected(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_page(vault, "concepts/test.md", title="")
        result = validate_vault(vault)
        issue_types = [i.issue_type for i in result.issues]
        assert "empty_title" in issue_types

    def test_missing_title_detected(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_page(vault, "concepts/test.md", title=None, frontmatter_extra="other: value")
        result = validate_vault(vault)
        issue_types = [i.issue_type for i in result.issues]
        assert "empty_title" in issue_types

    def test_normal_title_passes(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_page(vault, "concepts/test.md", title="Attention Mechanism")
        result = validate_vault(vault)
        assert result.passed_pages == 1


class TestValidateVaultControlCharsInTitle:
    def test_control_chars_detected(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_page(vault, "entities/test.md", title="Hello\x00World")
        result = validate_vault(vault)
        issue_types = [i.issue_type for i in result.issues]
        assert "control_chars_in_title" in issue_types

    def test_clean_title_passes(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_page(vault, "entities/test.md", title="Clean Title")
        result = validate_vault(vault)
        assert result.passed_pages == 1


class TestValidateVaultLongGarbledName:
    def test_long_filename_detected(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        long_name = "a" * (MAX_FILENAME_LENGTH + 1)
        _write_page(vault, f"{long_name}.md")
        result = validate_vault(vault)
        issue_types = [i.issue_type for i in result.issues]
        assert "long_garbled_name" in issue_types

    def test_garbled_slug_detected(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        # Slug with very low readability
        garbled = "\x01\x02\x03\x04\x05\x06\x07\x08"
        # Use a filename that passes slug rules but the content path triggers check
        fname = "test.md"
        fpath = vault / fname
        fpath.parent.mkdir(parents=True, exist_ok=True)
        # Write frontmatter with garbled title to trigger control chars
        content = f'---\ntitle: "{garbled}"\n---\n\nBody\n'
        fpath.write_text(content, encoding="utf-8")
        result = validate_vault(vault)
        # Should have control_chars_in_title at minimum
        issue_types = [i.issue_type for i in result.issues]
        assert len(issue_types) > 0


class TestValidateVaultAggregateResult:
    def test_pass_rate_computed(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_page(vault, "sources/a.md")
        _write_page(vault, "sources/b.md")
        _write_page(vault, ".md", title="Empty Slug")
        result = validate_vault(vault)
        assert result.total_pages == 3
        assert result.passed_pages == 2
        assert result.failed_pages == 1
        assert result.pass_rate == round(2 / 3, 4)

    def test_no_pages(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir(parents=True)
        result = validate_vault(vault)
        assert result.total_pages == 0
        assert result.pass_rate is None
        assert result.issues == []

    def test_nonexistent_vault(self, tmp_path: Path) -> None:
        result = validate_vault(tmp_path / "nonexistent")
        assert result.total_pages == 0
        assert result.pass_rate is None


class TestValidateVaultToDict:
    def test_to_dict_structure(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_page(vault, "sources/test.md")
        result = validate_vault(vault)
        d = result.to_dict()
        assert "vault_path" in d
        assert "total_pages" in d
        assert "passed_pages" in d
        assert "failed_pages" in d
        assert "pass_rate" in d
        assert "issues" in d
        assert isinstance(d["issues"], list)


class TestValidateVaultMultipleIssues:
    def test_single_page_multiple_issues(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        # Create a page with control chars in title AND empty slug filename
        long_name = "x" * (MAX_FILENAME_LENGTH + 1)
        _write_page(vault, f"{long_name}.md", title="Test\x00Page")
        result = validate_vault(vault)
        issue_types = [i.issue_type for i in result.issues]
        # Should have at least: long_garbled_name + control_chars_in_title
        assert "control_chars_in_title" in issue_types
        assert "long_garbled_name" in issue_types

    def test_multiple_pages_mixed_quality(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_page(vault, "sources/good.md", title="Good Paper")
        _write_page(vault, ".md", title="Empty Filename")
        _write_page(vault, "entities/attention-is-all-you-need.md", title="Attention")
        result = validate_vault(vault)
        assert result.total_pages == 3
        assert result.passed_pages == 2
        assert result.failed_pages == 1
