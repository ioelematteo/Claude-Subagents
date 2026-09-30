import pytest

from swarm import workspace


def make_root(tmp_path):
    return workspace.get_root(str(tmp_path))


# --------------------------------------------------------------------------- get_root


def test_get_root_rejects_empty():
    with pytest.raises(ValueError, match="'root' is required"):
        workspace.get_root("")


def test_get_root_rejects_missing_folder(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ValueError, match="is not a folder"):
        workspace.get_root(str(missing))


def test_get_root_rejects_a_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(ValueError, match="is not a folder"):
        workspace.get_root(str(f))


def test_get_root_returns_resolved_directory(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    root = workspace.get_root(str(d))
    assert root == d.resolve()
    assert root.is_dir()


# --------------------------------------------------------------------------- read_context


def test_read_context_explicit_paths(tmp_path):
    root = make_root(tmp_path)
    (root / "a.txt").write_text("alpha")
    (root / "b.txt").write_text("beta")

    text, included, skipped = workspace.read_context(root, ["a.txt", "b.txt"])

    assert included == ["a.txt", "b.txt"]
    assert skipped == []
    assert text == (
        "=== FILE: a.txt ===\n```\nalpha\n```"
        "\n\n"
        "=== FILE: b.txt ===\n```\nbeta\n```"
    )


def test_read_context_glob_is_sorted(tmp_path):
    root = make_root(tmp_path)
    (root / "b.txt").write_text("B")
    (root / "a.txt").write_text("A")

    _, included, _ = workspace.read_context(root, ["*.txt"])

    assert included == ["a.txt", "b.txt"]


def test_read_context_glob_recurses_into_subdirs(tmp_path):
    root = make_root(tmp_path)
    (root / "top.txt").write_text("T")
    sub = root / "sub"
    sub.mkdir()
    (sub / "nested.txt").write_text("N")

    _, included, _ = workspace.read_context(root, ["**/*.txt"])

    assert included == ["sub/nested.txt", "top.txt"]


def test_read_context_absolute_path_inside_root_is_rendered_relative(tmp_path):
    root = make_root(tmp_path)
    (root / "a.txt").write_text("A")

    text, included, _ = workspace.read_context(root, [str(root / "a.txt")])

    assert included == ["a.txt"]
    assert text.startswith("=== FILE: a.txt ===")


def test_read_context_deduplicates_repeated_matches(tmp_path):
    root = make_root(tmp_path)
    (root / "a.txt").write_text("A")

    _, included, _ = workspace.read_context(root, ["a.txt", "*.txt"])

    assert included == ["a.txt"]


def test_read_context_skips_secret_files_with_reason(tmp_path):
    root = make_root(tmp_path)
    (root / ".env").write_text("SECRET=1")
    (root / "server.pem").write_text("key")
    (root / "app.py").write_text("pass")

    text, included, skipped = workspace.read_context(root, [".env", "server.pem", "app.py"])

    assert included == ["app.py"]
    assert skipped == [".env (secret)", "server.pem (secret)"]
    assert "SECRET=1" not in text


def test_read_context_allows_allowed_secret_names(tmp_path):
    root = make_root(tmp_path)
    (root / ".env.example").write_text("A=1")

    _, included, skipped = workspace.read_context(root, [".env.example"])

    assert included == [".env.example"]
    assert skipped == []


def test_read_context_missing_secret_is_skipped_not_raised(tmp_path):
    root = make_root(tmp_path)

    _, included, skipped = workspace.read_context(root, [".env"])

    assert included == []
    assert skipped == [".env (secret)"]


def test_read_context_skips_binary_files_with_reason(tmp_path):
    root = make_root(tmp_path)
    (root / "blob.bin").write_bytes(b"\x00\x01\x02")
    (root / "ok.txt").write_text("fine")

    text, included, skipped = workspace.read_context(root, ["blob.bin", "ok.txt"])

    assert included == ["ok.txt"]
    assert skipped == ["blob.bin (binary)"]
    assert "blob" not in text


def test_read_context_skips_files_inside_skip_dirs(tmp_path):
    root = make_root(tmp_path)
    nm = root / "node_modules"
    nm.mkdir()
    (nm / "dep.js").write_text("x")

    text, included, skipped = workspace.read_context(root, ["node_modules/dep.js"])

    assert included == []
    assert skipped == []
    assert text == ""


def test_read_context_missing_file_raises(tmp_path):
    root = make_root(tmp_path)

    with pytest.raises(ValueError, match="file not found: nosuch"):
        workspace.read_context(root, ["nosuch"])


def test_read_context_glob_with_no_matches_is_empty(tmp_path):
    root = make_root(tmp_path)

    text, included, skipped = workspace.read_context(root, ["*.md"])

    assert (text, included, skipped) == ("", [], [])


def test_read_context_rejects_path_outside_root(tmp_path):
    root = make_root(tmp_path)

    with pytest.raises(ValueError, match="path outside the project"):
        workspace.read_context(root, ["../escape.txt"])


def test_read_context_too_large_raises(tmp_path):
    root = make_root(tmp_path)
    (root / "big.txt").write_text("x" * (workspace.MAX_CONTEXT_BYTES + 1))

    with pytest.raises(ValueError, match="context too large"):
        workspace.read_context(root, ["big.txt"])


# --------------------------------------------------------------------------- parse_files


def test_parse_files_single_fenced_block():
    out = "=== FILE: a.txt ===\n```\nhello\n```\n"

    files, notes = workspace.parse_files(out)

    assert files == {"a.txt": "hello\n"}
    assert notes == ""


def test_parse_files_keeps_notes_before_first_header():
    out = "Here is the plan.\n\n=== FILE: a.txt ===\n```\nA\n```\n"

    files, notes = workspace.parse_files(out)

    assert files == {"a.txt": "A\n"}
    assert notes == "Here is the plan."


def test_parse_files_multiple_files():
    out = (
        "=== FILE: a.txt ===\n```\nA\n```\n"
        "\n"
        "=== FILE: pkg/b.py ===\n```\nprint('b')\n```\n"
    )

    files, notes = workspace.parse_files(out)

    assert files == {"a.txt": "A\n", "pkg/b.py": "print('b')\n"}
    assert notes == ""


def test_parse_files_markdown_keeps_its_own_fences():
    out = (
        "=== FILE: doc.md ===\n"
        "```\n"
        "before\n"
        "```\n"
        "code\n"
        "```\n"
        "after\n"
        "```"
    )

    files, notes = workspace.parse_files(out)

    assert files == {"doc.md": "before\n```\ncode\n```\nafter\n"}
    assert notes == ""


def test_parse_files_block_without_fences():
    out = "=== FILE: a.txt ===\nplain content\n"

    files, _ = workspace.parse_files(out)

    assert files == {"a.txt": "plain content\n"}


def test_parse_files_empty_fenced_body():
    out = "=== FILE: empty.txt ===\n```\n```\n"

    files, _ = workspace.parse_files(out)

    assert files == {"empty.txt": "\n"}


def test_parse_files_no_headers_returns_whole_output_as_notes():
    files, notes = workspace.parse_files("just some text\n")

    assert files == {}
    assert notes == "just some text"


def test_parse_files_header_allows_trailing_whitespace_and_spaces():
    out = "=== FILE:  spaced.txt  ===   \n```\nA\n```\n"

    files, _ = workspace.parse_files(out)

    assert files == {"spaced.txt": "A\n"}


def test_parse_files_headers_with_empty_bodies():
    out = "=== FILE: a.txt ===\n=== FILE: b.txt ===\n"

    files, notes = workspace.parse_files(out)

    assert files == {"a.txt": "\n", "b.txt": "\n"}
    assert notes == ""


def test_parse_files_roundtrips_read_context_output(tmp_path):
    root = make_root(tmp_path)
    (root / "a.txt").write_text("hello")

    text, _, _ = workspace.read_context(root, ["a.txt"])
    files, notes = workspace.parse_files(text)

    assert files == {"a.txt": "hello\n"}
    assert notes == ""


# --------------------------------------------------------------------------- write_files


def test_write_files_creates_file_and_reports_lines(tmp_path):
    root = make_root(tmp_path)

    report = workspace.write_files(root, {"a.txt": "one\ntwo\n"}, overwrite=False)

    assert (root / "a.txt").read_text() == "one\ntwo\n"
    assert report == [{"path": "a.txt", "status": "created", "lines": 2}]


def test_write_files_creates_parent_directories(tmp_path):
    root = make_root(tmp_path)

    report = workspace.write_files(root, {"pkg/sub/b.py": "x"}, overwrite=False)

    assert (root / "pkg/sub/b.py").read_text() == "x"
    assert report == [{"path": "pkg/sub/b.py", "status": "created", "lines": 0}]


def test_write_files_overwrites_when_allowed(tmp_path):
    root = make_root(tmp_path)
    (root / "a.txt").write_text("old")

    report = workspace.write_files(root, {"a.txt": "new"}, overwrite=True)

    assert (root / "a.txt").read_text() == "new"
    assert report == [{"path": "a.txt", "status": "overwritten", "lines": 0}]


def test_write_files_skips_existing_without_overwrite(tmp_path):
    root = make_root(tmp_path)
    (root / "a.txt").write_text("old")

    report = workspace.write_files(root, {"a.txt": "new"}, overwrite=False)

    assert (root / "a.txt").read_text() == "old"
    assert report == [
        {"path": "a.txt", "status": "skipped: already exists (use overwrite=true)"}
    ]


def test_write_files_backup_allows_rewrite_without_overwrite(tmp_path):
    root = make_root(tmp_path)
    (root / "a.txt").write_text("old")
    backup = {}

    # a file that existed before the job is protected without overwrite...
    first = workspace.write_files(root, {"a.txt": "first"}, overwrite=False, backup=backup)
    assert first[0]["status"].startswith("skipped")
    assert backup == {}

    # ...but a file the job itself created can be rewritten by a later attempt
    workspace.write_files(root, {"b.txt": "first"}, overwrite=False, backup=backup)
    assert backup == {"b.txt": None}
    second = workspace.write_files(root, {"b.txt": "second"}, overwrite=False, backup=backup)

    assert second == [{"path": "b.txt", "status": "overwritten", "lines": 0}]
    assert (root / "b.txt").read_text() == "second"
    assert backup == {"b.txt": None}


def test_write_files_backup_records_none_for_new_files(tmp_path):
    root = make_root(tmp_path)
    backup = {}

    workspace.write_files(root, {"new.txt": "n"}, overwrite=False, backup=backup)

    assert backup == {"new.txt": None}


def test_write_files_backup_untouched_when_file_skipped(tmp_path):
    root = make_root(tmp_path)
    (root / "a.txt").write_text("old")
    backup = {}

    workspace.write_files(root, {"a.txt": "new"}, overwrite=False, backup=backup)

    assert backup == {}
    assert (root / "a.txt").read_text() == "old"


def test_write_files_refuses_path_traversal(tmp_path):
    root = make_root(tmp_path)

    report = workspace.write_files(root, {"../escape_me.txt": "boom"}, overwrite=True)

    assert report == [
        {
            "path": "../escape_me.txt",
            "status": report[0]["status"],
        }
    ]
    assert report[0]["status"].startswith("refused: path outside the project")
    assert not (tmp_path.parent / "escape_me.txt").exists()


@pytest.mark.parametrize("rel", [".env", "id_rsa", "my_secret_notes.txt", "server.key"])
def test_write_files_refuses_secret_files(tmp_path, rel):
    root = make_root(tmp_path)

    report = workspace.write_files(root, {rel: "x"}, overwrite=True)

    assert report == [{"path": rel, "status": "refused: looks like a secret file"}]
    assert not (root / rel).exists()


# --------------------------------------------------------------------------- rollback


def test_rollback_restores_originals_and_deletes_created(tmp_path):
    root = make_root(tmp_path)
    (root / "keep.txt").write_text("original")
    backup = {}

    report = workspace.write_files(
        root,
        {"keep.txt": "modified", "new/deep.txt": "fresh"},
        overwrite=True,
        backup=backup,
    )

    assert [r["status"] for r in report] == ["overwritten", "created"]
    assert backup == {"keep.txt": b"original", "new/deep.txt": None}

    restored = workspace.rollback(root, backup)

    assert restored == ["keep.txt", "new/deep.txt"]
    assert (root / "keep.txt").read_text() == "original"
    assert not (root / "new/deep.txt").exists()


def test_rollback_of_created_file_is_idempotent(tmp_path):
    root = make_root(tmp_path)
    backup = {}
    workspace.write_files(root, {"fresh.txt": "x"}, overwrite=False, backup=backup)

    workspace.rollback(root, backup)
    restored = workspace.rollback(root, backup)

    assert restored == ["fresh.txt"]
    assert not (root / "fresh.txt").exists()
