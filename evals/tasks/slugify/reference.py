"""Reference implementation of the `slugify` eval task."""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int | None = None) -> str:
    """Turn ``text`` into a lowercase ASCII slug.

    The text is NFKD-normalized, combining marks are dropped, the result is
    lowercased, runs of non ``[a-z0-9]`` characters collapse into a single
    ``-``, and leading/trailing ``-`` are stripped. When ``max_len`` is given,
    the slug is truncated to that many characters and any ``-`` left by the cut
    is removed; ``max_len <= 0`` yields ``""``.

    Args:
        text: Arbitrary text to slugify.
        max_len: Optional maximum length of the returned slug.

    Returns:
        The slug, or ``""`` when nothing survives the transformation.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    slug = _NON_ALNUM.sub("-", without_marks.lower()).strip("-")
    if max_len is None:
        return slug
    if max_len <= 0:
        return ""
    return slug[:max_len].rstrip("-")
