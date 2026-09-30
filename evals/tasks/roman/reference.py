"""Reference implementation for the roman numeral task."""

from __future__ import annotations

_MIN_VALUE = 1
_MAX_VALUE = 3999

_ROMAN_TABLE: tuple[tuple[int, str], ...] = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)

_SYMBOL_VALUES: dict[str, int] = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}


def to_roman(n: int) -> str:
    """Convert an integer in 1..3999 to its canonical Roman numeral string.

    Args:
        n: The value to convert.

    Returns:
        The canonical uppercase Roman numeral using subtractive notation.

    Raises:
        ValueError: If ``n`` is not an int (bool is rejected) or is outside 1..3999.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise ValueError(f"n must be an int, got {type(n).__name__}")
    if not _MIN_VALUE <= n <= _MAX_VALUE:
        raise ValueError(f"n must be in {_MIN_VALUE}..{_MAX_VALUE}, got {n}")

    parts: list[str] = []
    remaining = n
    for value, symbol in _ROMAN_TABLE:
        while remaining >= value:
            parts.append(symbol)
            remaining -= value
    return "".join(parts)


def from_roman(s: str) -> int:
    """Convert a canonical uppercase Roman numeral to its integer value.

    Args:
        s: The Roman numeral string.

    Returns:
        The integer value in 1..3999.

    Raises:
        ValueError: If ``s`` is not a str, is empty, contains characters outside the
            seven Roman symbols, or is not in canonical form.
    """
    if not isinstance(s, str):
        raise ValueError(f"s must be a str, got {type(s).__name__}")
    if not s:
        raise ValueError("s must not be empty")
    for char in s:
        if char not in _SYMBOL_VALUES:
            raise ValueError(f"invalid roman numeral character {char!r} in {s!r}")

    total = 0
    for index, char in enumerate(s):
        value = _SYMBOL_VALUES[char]
        if index + 1 < len(s) and _SYMBOL_VALUES[s[index + 1]] > value:
            total -= value
        else:
            total += value

    # to_roman also raises ValueError when total is outside 1..3999 (e.g. "MMMM").
    if to_roman(total) != s:
        raise ValueError(f"non-canonical roman numeral: {s!r}")
    return total
