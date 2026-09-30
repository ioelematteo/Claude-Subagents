"""Hidden tests for the LRUCache task. Deterministic, no network, no sleeping."""

import pytest

from solution import LRUCache


def test_get_returns_none_for_missing_key():
    cache = LRUCache(3)
    assert cache.get("missing") is None
    assert len(cache) == 0


def test_put_then_get_roundtrip():
    cache = LRUCache(3)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert len(cache) == 2


def test_put_returns_none():
    cache = LRUCache(1)
    assert cache.put("a", 1) is None


def test_update_existing_key_replaces_value_without_growing():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("a", 99)
    assert cache.get("a") == 99
    assert len(cache) == 1


def test_evicts_least_recently_used_entry():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)  # 'a' is the least recently used
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert len(cache) == 2


def test_get_refreshes_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # 'a' becomes most recent
    cache.put("c", 3)  # evicts 'b'
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_put_on_existing_key_refreshes_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)  # update => 'a' becomes most recent
    cache.put("c", 3)  # evicts 'b'
    assert cache.get("b") is None
    assert cache.get("a") == 10
    assert cache.get("c") == 3
    assert len(cache) == 2


def test_capacity_one_keeps_only_last_put():
    cache = LRUCache(1)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert len(cache) == 1


def test_len_grows_until_capacity_and_then_stays():
    cache = LRUCache(3)
    assert len(cache) == 0
    for i in range(10):
        cache.put(i, i * i)
        assert len(cache) == min(i + 1, 3)


def test_eviction_order_with_many_accesses():
    cache = LRUCache(3)
    for key in ("a", "b", "c"):
        cache.put(key, key.upper())
    cache.get("a")  # order: b, c, a
    cache.get("b")  # order: c, a, b
    cache.put("d", "D")  # evicts 'c'
    assert cache.get("c") is None
    assert cache.get("a") == "A"
    assert cache.get("b") == "B"
    assert cache.get("d") == "D"
    assert len(cache) == 3


def test_remaining_entry_survives_many_puts():
    cache = LRUCache(2)
    cache.put("keep", "kept")
    for i in range(20):
        cache.get("keep")
        cache.put(i, i)
    assert cache.get("keep") == "kept"
    assert len(cache) == 2


def test_supports_arbitrary_keys_and_values():
    cache = LRUCache(2)
    key = (1, "a")
    sentinel = object()
    cache.put(key, sentinel)
    cache.put(0, [1, 2, 3])
    assert cache.get(key) is sentinel
    assert cache.get(0) == [1, 2, 3]
    assert cache.get("never") is None
    assert len(cache) == 2


@pytest.mark.parametrize("capacity", [0, -1, -100])
def test_invalid_capacity_raises_value_error(capacity):
    with pytest.raises(ValueError):
        LRUCache(capacity)
