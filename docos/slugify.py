"""Deterministic ASCII-safe slug sanitizer for wiki page export paths.

All wiki page filenames go through :func:`slugify` so that exported files
remain portable, readable, and deterministic across reruns.
"""

from __future__ import annotations

import re
import unicodedata

# Pre-compiled patterns for deterministic slug generation.
_NON_ASCII_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NON_SAFE_CHARS = re.compile(r"[^a-z0-9-]")
_MULTI_HYPHEN = re.compile(r"-{2,}")

# Patterns for title sanitisation.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd]")
_PRIVATE_USE = re.compile(r"[\ue000-\uf8ff]")
_MULTI_SPACE = re.compile(r"\s+")


def slugify(text: str, *, max_length: int = 80) -> str:
    """Return a deterministic, ASCII-safe slug for *text*.

    Guarantees:
    * Output contains only ``[a-z0-9-]`` (lowercase alphanumeric + hyphen).
    * Control characters (``\\x00``-``\\x1f``, ``\\x7f``) are removed.
    * Non-ASCII characters are decomposed via NFKD then stripped; their
      ASCII base characters survive when available (e.g. ``\\u00e9`` → ``e``).
    * Same input always produces the same output.
    * Output is truncated to *max_length* characters (default 80).

    Args:
        text: Raw title or label to slugify.
        max_length: Maximum output length (must be > 0).

    Returns:
        A non-empty sanitized slug string, or ``"untitled"`` when the input
        yields no safe characters.
    """
    if max_length <= 0:
        max_length = 80

    # 1. Unicode normalisation (NFKD decomposes combined chars).
    s = unicodedata.normalize("NFKD", text)

    # 2. Keep only ASCII after decomposition (strips combining marks).
    s = s.encode("ascii", "ignore").decode("ascii")

    # 3. Lowercase.
    s = s.lower()

    # 4. Remove control characters.
    s = _NON_ASCII_CONTROL.sub("", s)

    # 5. Replace all non-safe characters with a hyphen.
    s = _NON_SAFE_CHARS.sub("-", s)

    # 6. Collapse consecutive hyphens.
    s = _MULTI_HYPHEN.sub("-", s)

    # 7. Strip leading/trailing hyphens.
    s = s.strip("-")

    # 8. Truncate to max_length, then strip trailing hyphens again.
    s = s[:max_length].rstrip("-")

    # 9. Fallback for empty results.
    return s or "untitled"


def sanitize_title(text: str) -> str:
    """Remove control characters and binary garbage from a page title.

    Guarantees:
    * Control characters (``\\x00``–``\\x1f``, ``\\x7f``–``\\x9f``, ``\\ufffd``)
      are removed.
    * Private-use Unicode code-points are removed.
    * Consecutive whitespace is collapsed to a single space.

    Args:
        text: Raw title string to clean.

    Returns:
        Cleaned title string.  May be empty when the input contained no
        readable content.
    """
    if not text:
        return ""

    # 1. Remove control characters and replacement character.
    s = _CONTROL_CHARS.sub("", text)

    # 2. Remove private-use code-points (common binary-garbage indicator).
    s = _PRIVATE_USE.sub("", s)

    # 3. Collapse whitespace.
    s = _MULTI_SPACE.sub(" ", s).strip()

    return s


def is_readable_title(text: str, *, min_alpha_ratio: float = 0.5) -> bool:
    """Return ``True`` when *text* contains enough readable characters.

    A title is considered readable when **all** of the following hold:

    * It is non-empty after stripping whitespace.
    * At least ``min_alpha_ratio`` (default 50 %) of characters are
      alphanumeric, whitespace, or common punctuation.
    * At least ``min_alpha_ratio`` of characters are **ASCII** letters.
      This prevents garbled PDF text (e.g. ``"ôsôíæõq wêúçhï"``) from
      passing — such strings have high ``isalnum()`` ratio but almost no
      ASCII letters.

    Args:
        text: Title to evaluate.
        min_alpha_ratio: Minimum fraction of readable characters (0–1).
            Default is 0.5 (50 %).  Callers that need a weaker check
            (e.g. vault validator inspecting slug-like identifiers) can
            pass a lower value.

    Returns:
        Boolean readability verdict.
    """
    if not text or not text.strip():
        return False
    total = len(text)
    if total == 0:
        return False
    # Broad readability check (Unicode letters + punctuation)
    readable = sum(1 for c in text if c.isalnum() or c.isspace() or c in "._-,;:!'\"()")
    if (readable / total) < min_alpha_ratio:
        return False
    # ASCII readability gate — rejects garbled PDF text that passes isalnum()
    # but consists mostly of non-ASCII Unicode letters.  Uses the same
    # threshold so callers (like the vault validator) can relax it when
    # checking slug-style identifiers that legitimately contain digits.
    #
    # Exception: CJK text (Chinese/Japanese/Korean) is inherently readable
    # even without ASCII letters.  Garbled PDF text consists mainly of Latin
    # Extended characters (ô, ê, ç, ß, etc.), not CJK ideographs.
    has_cjk = any(
        "\u4e00" <= c <= "\u9fff"      # CJK Unified Ideographs
        or "\u3040" <= c <= "\u309f"    # Hiragana
        or "\u30a0" <= c <= "\u30ff"    # Katakana
        or "\uac00" <= c <= "\ud7af"    # Hangul Syllables
        for c in text
    )
    if has_cjk:
        return True
    ascii_letters = sum(1 for c in text if c.isascii() and c.isalpha())
    return (ascii_letters / total) >= min_alpha_ratio
