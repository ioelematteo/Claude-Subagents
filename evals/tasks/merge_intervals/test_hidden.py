"""Hidden tests for the merge_intervals task."""

import pytest

from solution import merge_intervals


def test_empty_list_returns_empty_list():
    assert merge_intervals([]) == []


def test_single_interval_is_returned_as_one_tuple():
    result = merge_intervals([(2, 5)])
    assert result == [(2, 5)]
    assert isinstance(result, list)
    assert all(isinstance(interval, tuple) for interval in result)


def test_disjoint_intervals_are_sorted_and_kept():
    assert merge_intervals([(10, 12), (1, 3), (5, 7)]) == [(1, 3), (5, 7), (10, 12)]


def test_touching_intervals_merge():
    assert merge_intervals([(1, 3), (3, 5)]) == [(1, 5)]
    assert merge_intervals([(3, 5), (1, 3)]) == [(1, 5)]


def test_overlapping_intervals_merge():
    assert merge_intervals([(1, 4), (2, 6)]) == [(1, 6)]
    assert merge_intervals([(2, 6), (1, 4)]) == [(1, 6)]


def test_contained_interval_does_not_shrink_the_result():
    assert merge_intervals([(1, 10), (2, 5)]) == [(1, 10)]
    assert merge_intervals([(2, 5), (1, 10)]) == [(1, 10)]


def test_chain_is_fully_merged():
    assert merge_intervals([(1, 2), (2, 3), (3, 4), (4, 5)]) == [(1, 5)]


def test_duplicates_collapse():
    assert merge_intervals([(4, 7), (4, 7), (4, 7)]) == [(4, 7)]


def test_negative_bounds_are_supported():
    assert merge_intervals([(-5, -3), (-3, 0), (2, 4)]) == [(-5, 0), (2, 4)]
    assert merge_intervals([(-10, -8), (-9, -1)]) == [(-10, -1)]


def test_zero_length_intervals_touch_and_merge():
    assert merge_intervals([(5, 5), (5, 7)]) == [(5, 7)]
    assert merge_intervals([(1, 3), (3, 3), (3, 5)]) == [(1, 5)]
    assert merge_intervals([(6, 6)]) == [(6, 6)]


def test_invalid_interval_raises_value_error():
    with pytest.raises(ValueError):
        merge_intervals([(5, 4)])


def test_invalid_interval_is_detected_before_merging():
    with pytest.raises(ValueError):
        merge_intervals([(1, 3), (10, 2), (4, 6)])
    with pytest.raises(ValueError):
        merge_intervals([(5, 5), (7, 6)])


def test_input_list_is_not_modified():
    intervals = [(3, 5), (1, 3), (1, 3)]
    snapshot = list(intervals)
    merge_intervals(intervals)
    assert intervals == snapshot
    assert intervals[0] == (3, 5)


def test_larger_scenario():
    assert merge_intervals([(1, 3), (8, 10), (2, 6), (15, 18), (10, 12), (20, 20)]) == [
        (1, 6),
        (8, 12),
        (15, 18),
        (20, 20),
    ]
