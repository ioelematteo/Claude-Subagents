"""Hidden tests for the roman numeral task."""

import pytest

from solution import from_roman, to_roman


def test_to_roman_basic_values():
    cases = {
        1: "I",
        2: "II",
        3: "III",
        5: "V",
        8: "VIII",
        10: "X",
        50: "L",
        100: "C",
        500: "D",
        1000: "M",
    }
    for n, expected in cases.items():
        assert to_roman(n) == expected


def test_to_roman_subtractive_forms():
    cases = {4: "IV", 9: "IX", 40: "XL", 90: "XC", 400: "CD", 900: "CM"}
    for n, expected in cases.items():
        assert to_roman(n) == expected


def test_to_roman_composite_values():
    cases = {
        14: "XIV",
        19: "XIX",
        44: "XLIV",
        1994: "MCMXCIV",
        2024: "MMXXIV",
        3888: "MMMDCCCLXXXVIII",
        3999: "MMMCMXCIX",
    }
    for n, expected in cases.items():
        assert to_roman(n) == expected


def test_to_roman_out_of_range_raises_value_error():
    for n in (0, -1, -3999, 4000, 10000):
        with pytest.raises(ValueError):
            to_roman(n)


def test_to_roman_non_int_raises_value_error():
    for n in (3.0, "5", None, True, False, [5]):
        with pytest.raises(ValueError):
            to_roman(n)


def test_from_roman_basic_values():
    cases = {
        "I": 1,
        "III": 3,
        "V": 5,
        "VIII": 8,
        "M": 1000,
        "MMXXIV": 2024,
        "MMMCMXCIX": 3999,
    }
    for s, expected in cases.items():
        value = from_roman(s)
        assert value == expected
        assert isinstance(value, int)


def test_from_roman_subtractive_forms():
    cases = {
        "IV": 4,
        "IX": 9,
        "XL": 40,
        "XC": 90,
        "CD": 400,
        "CM": 900,
        "MCMXCIV": 1994,
    }
    for s, expected in cases.items():
        assert from_roman(s) == expected


def test_from_roman_round_trip_every_value():
    for n in range(1, 4000):
        assert from_roman(to_roman(n)) == n


def test_from_roman_rejects_invalid_characters():
    for s in ("", " ", "iv", "Xi", "ABC", "I V", "M1", "IV!", "iV", "\nX"):
        with pytest.raises(ValueError):
            from_roman(s)


def test_from_roman_rejects_non_canonical_numerals():
    bad = (
        "IIII",
        "VX",
        "IC",
        "IL",
        "XM",
        "XXXX",
        "VV",
        "IIV",
        "MCMC",
        "VIV",
        "IXI",
        "CDC",
        "DCD",
        "MMMM",
        "MMMMM",
    )
    for s in bad:
        with pytest.raises(ValueError):
            from_roman(s)


def test_from_roman_rejects_non_string_input():
    for s in (None, 5, 3.0, ["I"], ("I",)):
        with pytest.raises(ValueError):
            from_roman(s)
