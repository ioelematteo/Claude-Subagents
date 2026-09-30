"""Hidden tests for the `parse_duration` eval task."""

from __future__ import annotations

import pytest

from solution import parse_duration


def test_single_units() -> None:
    assert parse_duration("45s") == 45
    assert parse_duration("30m") == 1800
    assert parse_duration("2h") == 7200
    assert parse_duration("3d") == 259200


def test_combined_units() -> None:
    assert parse_duration("1h30m") == 5400
    assert parse_duration("2d4h") == 187200


def test_all_units_in_descending_order() -> None:
    assert parse_duration("1d10h30m15s") == 124215


def test_leading_zeros_and_large_components() -> None:
    assert parse_duration("007m") == 420
    assert parse_duration("90m") == 5400
    assert parse_duration("100s") == 100


def test_surrounding_whitespace_is_allowed() -> None:
    assert parse_duration("  1h30m  ") == 5400
    assert parse_duration("\t45s\n") == 45


def test_zero_components_are_allowed_when_total_is_positive() -> None:
    assert parse_duration("1h0m") == 3600
    assert parse_duration("1d0h0m5s") == 86405


def test_result_type_is_int() -> None:
    assert isinstance(parse_duration("1h30m"), int)
    assert isinstance(parse_duration("45s"), int)


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_empty_input_raises(value: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(value)


@pytest.mark.parametrize("value", ["1h 30m", "1 h30m", "1h30 m", " 1h\t30m "])
def test_inner_whitespace_raises(value: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(value)


@pytest.mark.parametrize("value", ["1x", "1H", "abc", "1.5h", "-1h", "1,5h"])
def test_unknown_or_non_numeric_components_raise(value: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(value)


@pytest.mark.parametrize("value", ["h", "m30s", "30", "1h30", "1hh"])
def test_missing_number_raises(value: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(value)


@pytest.mark.parametrize("value", ["1h2h", "1s1s", "1d1d", "1m2m"])
def test_repeated_unit_raises(value: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(value)


@pytest.mark.parametrize("value", ["30m1h", "1s30m", "1m1d", "1h1d", "15s30m"])
def test_out_of_order_units_raise(value: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(value)


@pytest.mark.parametrize("value", ["0s", "0h0m", "0d0h0m0s"])
def test_zero_total_raises(value: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(value)
