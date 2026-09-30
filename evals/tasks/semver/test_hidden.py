import pytest

from solution import compare, sort_versions


def test_compare_core_numbers():
    assert compare("1.0.0", "2.0.0") == -1
    assert compare("2.0.0", "1.0.0") == 1
    assert compare("1.2.0", "1.10.0") == -1
    assert compare("1.0.1", "1.0.0") == 1
    assert compare("1.0.0", "1.0.0") == 0


def test_build_metadata_is_ignored():
    assert compare("1.0.0+20130313144700", "1.0.0") == 0
    assert compare("1.0.0+001", "1.0.0+002") == 0
    assert compare("1.2.3+a.b-c", "1.2.3") == 0
    assert compare("1.2.3+build.1", "1.2.4+build.1") == -1


def test_release_beats_prerelease():
    assert compare("1.0.0-alpha", "1.0.0") == -1
    assert compare("1.0.0", "1.0.0-rc.1") == 1
    assert compare("1.0.1-alpha", "1.0.0") == 1
    assert compare("1.0.0-0", "1.0.0") == -1


def test_numeric_identifiers_compared_numerically():
    assert compare("1.0.0-beta.2", "1.0.0-beta.11") == -1
    assert compare("1.0.0-beta.11", "1.0.0-beta.2") == 1
    assert compare("1.0.0-1.2", "1.0.0-1.10") == -1


def test_numeric_identifiers_lower_than_alphanumeric():
    assert compare("1.0.0-1", "1.0.0-alpha") == -1
    assert compare("1.0.0-alpha", "1.0.0-1") == 1
    assert compare("1.0.0-0", "1.0.0-0a") == -1
    assert compare("1.0.0-999", "1.0.0-A") == -1


def test_alphanumeric_identifiers_use_ascii_order():
    assert compare("1.0.0-alpha", "1.0.0-beta") == -1
    assert compare("1.0.0-Alpha", "1.0.0-alpha") == -1
    assert compare("1.0.0-alpha", "1.0.0-Alpha") == 1
    assert compare("1.0.0-alpha-1", "1.0.0-alpha") == 1


def test_larger_prerelease_set_wins_when_prefix_equal():
    assert compare("1.0.0-alpha", "1.0.0-alpha.1") == -1
    assert compare("1.0.0-alpha.1", "1.0.0-alpha") == 1
    assert compare("1.0.0-alpha.1", "1.0.0-alpha.1") == 0
    assert compare("1.0.0-alpha.a", "1.0.0-alpha.a.0") == -1


def test_canonical_semver_chain():
    chain = [
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
    ]
    for lower, higher in zip(chain, chain[1:]):
        assert compare(lower, higher) == -1
        assert compare(higher, lower) == 1
    assert sort_versions(list(reversed(chain))) == chain


def test_sort_versions_ascending():
    versions = ["1.0.0", "0.1.0", "1.0.0-rc.1", "1.0.0+build.5", "2.0.0-alpha", "1.0.0-alpha"]
    assert sort_versions(versions) == [
        "0.1.0",
        "1.0.0-alpha",
        "1.0.0-rc.1",
        "1.0.0",
        "1.0.0+build.5",
        "2.0.0-alpha",
    ]


def test_sort_versions_empty_single_and_duplicates():
    assert sort_versions([]) == []
    assert sort_versions(["1.2.3"]) == ["1.2.3"]
    assert sort_versions(["1.0.0", "1.0.0", "0.1.0"]) == ["0.1.0", "1.0.0", "1.0.0"]


def test_sort_versions_does_not_mutate_input():
    versions = ["2.0.0", "1.0.0"]
    out = sort_versions(versions)
    assert versions == ["2.0.0", "1.0.0"]
    assert out == ["1.0.0", "2.0.0"]


@pytest.mark.parametrize(
    "bad",
    [
        "1.2",
        "01.2.3",
        "1.2.03",
        "1.2.3-",
        "1.2.3-01",
        "1.2.3-alpha..1",
        "1.2.3+",
        "1.2.3.4",
        "",
        "v1.2.3",
        "1.2.3 ",
        "1.2.3-alpha+",
        "a.b.c",
    ],
)
def test_invalid_versions_raise(bad):
    with pytest.raises(ValueError):
        compare(bad, "1.0.0")
    with pytest.raises(ValueError):
        compare("1.0.0", bad)
    with pytest.raises(ValueError):
        sort_versions([bad])
    with pytest.raises(ValueError):
        sort_versions(["1.0.0", bad])
