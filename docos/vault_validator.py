"""Obsidian-ready vault validator — checks exported wiki pages for Obsidian compatibility.

Scans an exported wiki vault directory and detects:

* Empty filenames (e.g. ``.md``)
* Unreadable slugs (non-ASCII-safe characters in filenames)
* Empty frontmatter titles
* Control characters embedded in titles
* Abnormally long or garbled page names

Results are written to a structured payload that batch scripts can consume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docos.slugify import is_readable_title

# ---------------------------------------------------------------------------
# Thresholds (documented for downstream consumers)
# ---------------------------------------------------------------------------

#: Maximum filename length before a page is flagged as abnormally long.
MAX_FILENAME_LENGTH: int = 200

#: Minimum alphanumeric ratio for a slug to be considered readable.
MIN_SLUG_READABLE_RATIO: float = 0.3

# ---------------------------------------------------------------------------
# Internal patterns
# ---------------------------------------------------------------------------

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd]")
_UNSAFE_SLUG_CHARS = re.compile(r"[^a-z0-9._-]")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PageIssue:
    """A single Obsidian-readiness issue found on one page."""

    page_path: str
    issue_type: str  # noqa: RUF012 — literal check in tests
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "page_path": self.page_path,
            "issue_type": self.issue_type,
            "detail": self.detail,
        }


@dataclass
class VaultValidationResult:
    """Aggregate result of validating one vault directory."""

    vault_path: str
    total_pages: int = 0
    passed_pages: int = 0
    failed_pages: int = 0
    pass_rate: float | None = None
    issues: list[PageIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vault_path": self.vault_path,
            "total_pages": self.total_pages,
            "passed_pages": self.passed_pages,
            "failed_pages": self.failed_pages,
            "pass_rate": self.pass_rate,
            "issues": [i.to_dict() for i in self.issues],
        }


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter_title(content: str) -> str | None:
    """Extract the ``title`` field from YAML frontmatter in *content*.

    Returns the title string or ``None`` when frontmatter or the title key is
    absent.
    """
    text = content.strip()
    if not text.startswith("---"):
        return None

    end = text.find("---", 3)
    if end == -1:
        return None

    fm_block = text[3:end]
    for line in fm_block.splitlines():
        line = line.strip()
        if line.startswith("title:"):
            title_value = line[len("title:"):].strip().strip('"').strip("'")
            return title_value
    return None


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------


def validate_vault(vault_path: Path) -> VaultValidationResult:
    """Validate all ``.md`` pages under *vault_path* for Obsidian readiness.

    Checks applied to every page:
    1. **empty_filename** — slug portion of the filename is empty.
    2. **unreadable_slug** — filename contains characters outside the safe
       set ``[a-z0-9._-]`` after lowering.
    3. **empty_title** — frontmatter ``title`` is missing or empty.
    4. **control_chars_in_title** — title contains control characters.
    5. **long_garbled_name** — filename exceeds :data:`MAX_FILENAME_LENGTH`
       or the slug portion has a readable-character ratio below
       :data:`MIN_SLUG_READABLE_RATIO`.

    Returns a :class:`VaultValidationResult` summarising all findings.
    """
    if not vault_path.exists():
        return VaultValidationResult(vault_path=str(vault_path))

    md_files = sorted(vault_path.rglob("*.md"))
    result = VaultValidationResult(
        vault_path=str(vault_path),
        total_pages=len(md_files),
    )

    for md_file in md_files:
        page_issues: list[PageIssue] = []
        rel = str(md_file.relative_to(vault_path))
        fname = md_file.name
        slug_part = fname[:-3] if fname.endswith(".md") else fname

        # 1. Empty filename
        if not slug_part.strip():
            page_issues.append(
                PageIssue(
                    page_path=rel,
                    issue_type="empty_filename",
                    detail="Filename slug is empty",
                ),
            )

        # 2. Unreadable slug
        slug_lower = slug_part.lower()
        if _UNSAFE_SLUG_CHARS.search(slug_lower):
            page_issues.append(
                PageIssue(
                    page_path=rel,
                    issue_type="unreadable_slug",
                    detail=f"Slug contains unsafe characters: {slug_part!r}",
                ),
            )

        # 3 & 4. Frontmatter title checks
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            content = ""

        title = _parse_frontmatter_title(content)

        if not title:
            page_issues.append(
                PageIssue(
                    page_path=rel,
                    issue_type="empty_title",
                    detail="Frontmatter title is missing or empty",
                ),
            )
        else:
            if _CONTROL_CHARS.search(title):
                page_issues.append(
                    PageIssue(
                        page_path=rel,
                        issue_type="control_chars_in_title",
                        detail=f"Title contains control characters: {title!r}",
                    ),
                )

        # 5. Long or garbled name
        if len(fname) > MAX_FILENAME_LENGTH:
            page_issues.append(
                PageIssue(
                    page_path=rel,
                    issue_type="long_garbled_name",
                    detail=f"Filename exceeds {MAX_FILENAME_LENGTH} characters ({len(fname)} chars)",
                ),
            )
        elif slug_part and not is_readable_title(slug_part, min_alpha_ratio=MIN_SLUG_READABLE_RATIO):
            page_issues.append(
                PageIssue(
                    page_path=rel,
                    issue_type="long_garbled_name",
                    detail=f"Slug has low readable-character ratio: {slug_part!r}",
                ),
            )

        result.issues.extend(page_issues)
        if page_issues:
            result.failed_pages += 1
        else:
            result.passed_pages += 1

    if result.total_pages > 0:
        result.pass_rate = round(result.passed_pages / result.total_pages, 4)
    else:
        result.pass_rate = None

    return result
