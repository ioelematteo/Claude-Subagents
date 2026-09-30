"""Reference implementation of the `parse_duration` eval task."""

from __future__ import annotations

import re

_UNIT_SECONDS = {"d": 86_400, "h": 3_600, "m": 60, "s": 1}
_UNIT_ORDER = ["d", "h", "m", "s"]
_COMPONENT = re.compile(r"([0-9]+)([dhms])")
_SHAPE = re.compile(r"(?:[0-9]+[dhms])+")


def parse_duration(s: str) -> int:
    """Parse a compact duration such as ``'1h30m'`` into whole seconds.

    Units are ``d``/``h``/``m``/``s``, each at most once, in strictly
    descending order. Surrounding whitespace is ignored; whitespace inside the
    string, unknown units, missing numbers, repeated/out-of-order units and a
    zero total are all rejected.

    Args:
        s: The duration string to parse.

    Returns:
        The total number of seconds as an ``int``.

    Raises:
        ValueError: If ``s`` is not a valid, strictly positive duration.
    """
    text = s.strip()
    if not text or not _SHAPE.fullmatch(text):
        raise ValueError(f"invalid duration: {s!r}")

    total = 0
    previous_rank = -1
    for number, unit in _COMPONENT.findall(text):
        rank = _UNIT_ORDER.index(unit)
        if rank <= previous_rank:
            raise ValueError(f"invalid duration: {s!r}")
        previous_rank = rank
        total += int(number) * _UNIT_SECONDS[unit]

    if total <= 0:
        raise ValueError(f"invalid duration: {s!r}")
    return total
