"""Reference implementation of a fixed-capacity LRU cache."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class LRUCache:
    """Least-recently-used cache holding at most `capacity` entries."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._entries: "OrderedDict[Any, Any]" = OrderedDict()

    def get(self, key: Any) -> Any:
        """Return the value stored under `key`, or None; mark `key` as most recent."""
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key: Any, value: Any) -> None:
        """Store `value` under `key`, evicting the least recently used entry if needed."""
        if key in self._entries:
            self._entries[key] = value
            self._entries.move_to_end(key)
            return
        self._entries[key] = value
        if len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)
