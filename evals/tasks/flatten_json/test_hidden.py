import copy

import pytest

from solution import flatten


def test_nested_dicts_become_dotted_keys():
    assert flatten({"a": {"b": {"c": 1}}}) == {"a.b.c": 1}


def test_lists_use_index_as_key_segment():
    assert flatten({"a": [1, 2]}) == {"a.0": 1, "a.1": 2}
    assert flatten({"a": [{"b": 1}]}) == {"a.0.b": 1}
    assert flatten({"a": [[1], [2, 3]]}) == {"a.0.0": 1, "a.1.0": 2, "a.1.1": 3}


def test_empty_containers_are_kept():
    assert flatten({"a": {}, "b": []}) == {"a": {}, "b": []}
    assert flatten({"a": {"b": {}}}) == {"a.b": {}}
    assert flatten({"a": {"b": []}}) == {"a.b": []}
    assert flatten({"a": [[]]}) == {"a.0": []}
    assert flatten({"a": {"b": [{"c": {}}]}}) == {"a.b.0.c": {}}


def test_scalars_are_untouched():
    data = {"a": 1, "b": 2.5, "c": "x", "d": True, "e": None}
    assert flatten(data) == dict(data)


def test_top_level_empty_dict():
    assert flatten({}) == {}


def test_custom_separator():
    assert flatten({"a": {"b": 1}}, sep="/") == {"a/b": 1}
    assert flatten({"a": [{"b": 2}]}, sep="::") == {"a::0::b": 2}


def test_separator_in_key_raises():
    with pytest.raises(ValueError):
        flatten({"a.b": 1})
    with pytest.raises(ValueError):
        flatten({"a": {"b.c": {"d": 1}}})
    with pytest.raises(ValueError):
        flatten({"a": [{"b.c": 1}]})
    with pytest.raises(ValueError):
        flatten({"a": [{"b": [{"c.d": 1}]}]})


def test_custom_separator_in_key_raises():
    with pytest.raises(ValueError):
        flatten({"a/b": 1}, sep="/")
    with pytest.raises(ValueError):
        flatten({"a": {"b/c": 1}}, sep="/")


def test_deep_mixed_structure():
    src = {"x": {"y": [{"z": {"w": 1}}, 2]}, "k": {}}
    assert flatten(src) == {"x.y.0.z.w": 1, "x.y.1": 2, "k": {}}


def test_input_is_not_mutated():
    src = {"a": {"b": [1, {"c": 2}]}}
    snapshot = copy.deepcopy(src)
    out = flatten(src)
    assert src == snapshot
    out["a.b.1.c"] = 99
    assert src == snapshot
