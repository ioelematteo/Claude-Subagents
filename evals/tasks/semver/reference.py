"""Reference implementation for the SemVer precedence task."""

from __future__ import annotations

import re
from functools import cmp_to_key

_SEMVER_RE = re.compile(
    r"""
    (?P<major>0|[1-9]\d*)
    \.
    (?P<minor>0|[1-9]\d*)
    \.
    (?P<patch>0|[1-9]\d*)
    (?:-(?P<prerelease>
        (?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)
        (?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*
    ))?
    (?:\+(?P<build>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?
    """,
    re.VERBOSE,
)


def _parse(version: str) -> tuple[tuple[int, int, int], list[str] | None]:
    """Return ((major, minor, patch), prerelease identifiers or None); raise ValueError if invalid."""
    if not isinstance(version, str):
        raise ValueError(f"invalid version: {version!r}")
    match = _SEMVER_RE.fullmatch(version)
    if match is None:
        raise ValueError(f"invalid version: {version!r}")
    prerelease = match.group("prerelease")
    core = (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )
    return core, prerelease.split(".") if prerelease is not None else None


def _compare_identifier(left: str, right: str) -> int:
    left_numeric = left.isdigit()
    right_numeric = right.isdigit()
    if left_numeric and right_numeric:
        left_int, right_int = int(left), int(right)
        if left_int == right_int:
            return 0
        return -1 if left_int < right_int else 1
    if left_numeric:
        return -1
    if right_numeric:
        return 1
    if left == right:
        return 0
    return -1 if left < right else 1


def compare(a: str, b: str) -> int:
    """Compare two SemVer 2.0.0 strings: -1 if a < b, 0 if equal, 1 if a > b."""
    core_a, pre_a = _parse(a)
    core_b, pre_b = _parse(b)
    if core_a != core_b:
        return -1 if core_a < core_b else 1
    if pre_a is None and pre_b is None:
        return 0
    if pre_a is None:
        return 1
    if pre_b is None:
        return -1
    for left, right in zip(pre_a, pre_b):
        result = _compare_identifier(left, right)
        if result != 0:
            return result
    if len(pre_a) == len(pre_b):
        return 0
    return -1 if len(pre_a) < len(pre_b) else 1


def sort_versions(vs: list[str]) -> list[str]:
    """Return a new list with `vs` sorted ascending by SemVer precedence."""
    for version in vs:
        _parse(version)
    return sorted(vs, key=cmp_to_key(compare))
