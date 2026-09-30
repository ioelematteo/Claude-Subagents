"""Hidden tests for the `slugify` eval task."""

from __future__ import annotations

from solution import slugify


def test_basic_punctuation_becomes_separator() -> None:
    assert slugify("Hello, World!") == "hello-world"


def test_runs_collapse_and_edges_are_stripped() -> None:
    assert slugify("  Foo--Bar  ") == "foo-bar"
    assert slugify("---") == ""
    assert slugify("a//b") == "a-b"


def test_empty_and_punctuation_only_inputs_return_empty_string() -> None:
    assert slugify("") == ""
    assert slugify("!!!") == ""
    assert slugify("   \t\n ") == ""


def test_accents_are_removed() -> None:
    assert slugify("\u00dcn\u00efc\u00f6d\u00e9 \u00c0ccents") == "unicode-accents"
    assert slugify("caf\u00e9 au lait") == "cafe-au-lait"


def test_non_decomposable_letters_are_separators() -> None:
    assert slugify("Gr\u00fc\u00dfe") == "gru-e"
    assert slugify("sm\u00f8rrebr\u00f8d") == "sm-rrebr-d"


def test_digits_are_kept() -> None:
    assert slugify("Top 10 Songs of 2024") == "top-10-songs-of-2024"
    assert slugify("Route 66") == "route-66"


def test_lowercasing() -> None:
    assert slugify("ALLCAPS MiXeD case") == "allcaps-mixed-case"


def test_underscores_and_slashes_are_separators() -> None:
    assert slugify("foo_bar/baz.qux") == "foo-bar-baz-qux"


def test_nfkd_compatibility_decomposition() -> None:
    # NFKD decomposes compatibility characters (ligature fi, circled digit) but not \u00c6.
    assert slugify("\ufb01le \u2460") == "file-1"
    assert slugify("\u00c6ther") == "ther"


def test_max_len_truncates_then_strips_trailing_separator() -> None:
    assert slugify("Hello World", 7) == "hello-w"
    assert slugify("Hello World", 6) == "hello"


def test_max_len_at_least_slug_length_is_a_no_op() -> None:
    assert slugify("Hello World", 11) == "hello-world"
    assert slugify("Hello World", 12) == "hello-world"
    assert slugify("Hello World", 100) == "hello-world"


def test_non_positive_max_len_returns_empty_string() -> None:
    assert slugify("Hello World", 0) == ""
    assert slugify("Hello World", -5) == ""


def test_max_len_is_never_exceeded_and_result_never_ends_with_separator() -> None:
    for limit in range(1, 12):
        result = slugify("Hello World!", limit)
        assert len(result) <= limit
        assert not result.endswith("-")


def test_default_max_len_is_none() -> None:
    assert slugify("Hello World") == "hello-world"
