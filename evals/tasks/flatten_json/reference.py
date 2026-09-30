"""Reference implementation for the flatten task."""

from __future__ import annotations

from typing import Any


def flatten(obj: dict, sep: str = ".") -> dict:
    """Flatten nested dicts and lists into a single-level dict with `sep`-joined keys.

    Dict keys are used as path segments, list indices are used as string path segments.
    Empty dicts/lists are kept as-is at their key. Keys containing `sep` raise ValueError.
    """
    if not isinstance(obj, dict):
        raise TypeError(f"obj must be a dict, got {type(obj).__name__}")
    out: dict[str, Any] = {}
    for key, value in obj.items():
        if not isinstance(key, str):
            raise TypeError(f"dict keys must be str, got {type(key).__name__}")
        if sep in key:
            raise ValueError(f"key {key!r} contains the separator {sep!r}")
        _walk(value, key, out, sep)
    return out


def _walk(value: Any, prefix: str, out: dict, sep: str) -> None:
    if isinstance(value, dict):
        if not value:
            out[prefix] = {}
            return
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"dict keys must be str, got {type(key).__name__}")
            if sep in key:
                raise ValueError(f"key {key!r} contains the separator {sep!r}")
            _walk(item, f"{prefix}{sep}{key}", out, sep)
    elif isinstance(value, list):
        if not value:
            out[prefix] = []
            return
        for index, item in enumerate(value):
            _walk(item, f"{prefix}{sep}{index}", out, sep)
    else:
        out[prefix] = value
