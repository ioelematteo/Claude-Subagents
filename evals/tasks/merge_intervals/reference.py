"""Reference implementation for the merge_intervals task."""

from __future__ import annotations


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort and merge overlapping or touching intervals.

    Args:
        intervals: Arbitrary-ordered list of ``(start, end)`` int pairs.

    Returns:
        A new list of ``(start, end)`` tuples sorted by start, where every pair of
        intervals that overlap or touch has been merged into one interval.

    Raises:
        ValueError: If any interval has ``start > end``.
    """
    for start, end in intervals:
        if start > end:
            raise ValueError(f"invalid interval ({start}, {end}): start must not exceed end")

    if not intervals:
        return []

    ordered = sorted(intervals, key=lambda interval: (interval[0], interval[1]))
    merged: list[tuple[int, int]] = [(ordered[0][0], ordered[0][1])]

    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            if end > last_end:
                merged[-1] = (last_start, end)
        else:
            merged.append((start, end))

    return merged
