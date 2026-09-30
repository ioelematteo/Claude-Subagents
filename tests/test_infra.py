"""Tests for swarm.store, swarm.budget and swarm.verify."""

from __future__ import annotations

import pytest

from swarm.budget import Budget, estimate_tokens, worst_case_cost
from swarm.config import TIERS
from swarm.store import Store
from swarm.verify import parse_command, run_check

# ------------------------------------------------------------------ store --


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _job(store: Store, job_id: str, session: str | None, created: float, **extra) -> None:
    store.upsert_job({"id": job_id, "session": session, "created": created, **extra})


def test_store_memory_and_file_backed(tmp_path):
    s = Store(":memory:")
    s.upsert_job({"id": "m1", "status": "queued"})
    assert s.get_job("m1")["status"] == "queued"
    s.close()

    path = tmp_path / "nested" / "x.db"
    s2 = Store(path)
    s2.upsert_job({"id": "f1", "status": "done"})
    s2.close()
    assert path.exists()

    s3 = Store(path)
    assert s3.get_job("f1")["status"] == "done"
    s3.close()


def test_get_job_missing_returns_none(store):
    assert store.get_job("nope") is None


def test_upsert_insert_then_partial_update_keeps_other_columns(store):
    store.upsert_job({
        "id": "j1", "session": "s", "label": "L", "profile": "implement",
        "status": "running", "tier": "flash-high", "attempts": 1,
        "tokens_in": 10, "tokens_out": 5, "cost_usd": 0.01, "created": 1.0,
    })
    store.upsert_job({"id": "j1", "status": "done"})

    job = store.get_job("j1")
    assert job["status"] == "done"
    assert job["session"] == "s"
    assert job["label"] == "L"
    assert job["profile"] == "implement"
    assert job["tier"] == "flash-high"
    assert job["attempts"] == 1
    assert job["tokens_in"] == 10
    assert job["tokens_out"] == 5
    assert job["cost_usd"] == pytest.approx(0.01)
    assert job["created"] == pytest.approx(1.0)


def test_upsert_overwrites_provided_columns(store):
    store.upsert_job({"id": "j1", "status": "running", "tokens_in": 1})
    store.upsert_job({"id": "j1", "status": "done", "tokens_in": 7})
    job = store.get_job("j1")
    assert job["status"] == "done"
    assert job["tokens_in"] == 7


@pytest.mark.parametrize("row", ["not-a-dict", 123, None])
def test_upsert_rejects_non_dict(store, row):
    with pytest.raises(ValueError):
        store.upsert_job(row)


def test_upsert_rejects_unknown_column(store):
    with pytest.raises(ValueError):
        store.upsert_job({"id": "j1", "nope": 1})


def test_upsert_requires_id(store):
    with pytest.raises(ValueError):
        store.upsert_job({"status": "queued"})


def test_files_and_spec_json_round_trip(store):
    files = ["a.py", "b/c.py"]
    spec = {"task": "x", "n": [1, 2], "nested": {"k": True}}
    store.upsert_job({"id": "j1", "files": files, "spec": spec})
    job = store.get_job("j1")
    assert job["files"] == files
    assert job["spec"] == spec


def test_json_columns_none_stay_none(store):
    store.upsert_job({"id": "j1"})
    job = store.get_job("j1")
    assert job["files"] is None
    assert job["spec"] is None


def test_list_jobs_newest_first_and_session_filter(store):
    _job(store, "a", "s1", 1.0)
    _job(store, "b", "s1", 3.0)
    _job(store, "c", "s2", 2.0)

    assert [j["id"] for j in store.list_jobs()] == ["b", "c", "a"]
    assert [j["id"] for j in store.list_jobs(session="s1")] == ["b", "a"]
    assert [j["id"] for j in store.list_jobs(session="s2")] == ["c"]


def test_list_jobs_limit_and_decoding(store):
    for i in range(5):
        _job(store, f"j{i}", "s1", float(i), files=[f"f{i}.py"])
    jobs = store.list_jobs(session="s1", limit=2)
    assert [j["id"] for j in jobs] == ["j4", "j3"]
    assert jobs[0]["files"] == ["f4.py"]


def test_events_oldest_first_and_data_round_trip(store):
    store.add_event("j1", "created", {"a": 1})
    store.add_event("j1", "attempt", {"outcome": "ok"})
    store.add_event("j1", "done")
    store.add_event("j2", "created")

    events = store.events("j1")
    assert [e["kind"] for e in events] == ["created", "attempt", "done"]
    assert events[0]["data"] == {"a": 1}
    assert events[1]["data"] == {"outcome": "ok"}
    assert events[2]["data"] == {}
    assert all(isinstance(e["ts"], float) for e in events)
    assert events[0]["ts"] <= events[-1]["ts"]
    assert store.events("nope") == []


def test_attempts_merges_event_data_and_filters(store):
    _job(store, "j1", "s1", 1.0)
    _job(store, "j2", "s2", 2.0)
    store.add_event("j1", "attempt", {"tier": "flash-high", "outcome": "ok", "cost_usd": 0.02})
    store.add_event("j1", "note", {"x": 1})
    store.add_event("j2", "attempt", {"tier": "pro-high", "outcome": "error", "cost_usd": 0.05})

    all_attempts = store.attempts()
    assert [a["job_id"] for a in all_attempts] == ["j1", "j2"]
    assert all_attempts[0]["tier"] == "flash-high"
    assert all_attempts[0]["cost_usd"] == pytest.approx(0.02)
    assert isinstance(all_attempts[0]["ts"], float)

    only_s1 = store.attempts(session="s1")
    assert [a["job_id"] for a in only_s1] == ["j1"]


def _seed_summary_jobs(store: Store) -> None:
    store.upsert_job({
        "id": "a", "session": "s1", "profile": "implement", "status": "done",
        "tier": "flash-high", "attempts": 1, "tokens_in": 100, "tokens_out": 50,
        "cost_usd": 0.10, "created": 1.0, "started": 1.0, "finished": 3.0,
        "files": ["a.py", "b.py"],
    })
    store.upsert_job({
        "id": "b", "session": "s1", "profile": "implement", "status": "done",
        "tier": "flash-high", "attempts": 3, "tokens_in": 200, "tokens_out": 80,
        "cost_usd": 0.20, "created": 2.0, "started": 2.0, "finished": 5.0,
        "files": ["c.py"],
    })
    store.upsert_job({
        "id": "c", "session": "s1", "profile": "tests", "status": "failed",
        "tier": "pro-high", "attempts": 2, "tokens_in": 50, "tokens_out": 20,
        "cost_usd": 0.05, "created": 3.0,
    })
    store.upsert_job({
        "id": "d", "session": "s2", "profile": "tests", "status": "done",
        "tier": "flash-fast", "attempts": 1, "tokens_in": 999, "tokens_out": 999,
        "cost_usd": 0.30, "created": 4.0, "started": 0.0, "finished": 1.0,
        "files": ["d.py"],
    })
    store.add_event("a", "attempt", {"tier": "flash-high", "outcome": "ok", "cost_usd": 0.06})
    store.add_event("b", "attempt", {"tier": "flash-high", "outcome": "error", "cost_usd": 0.10})
    store.add_event("c", "attempt", {"tier": "pro-high", "outcome": "ok", "cost_usd": 0.05})
    store.add_event("d", "attempt", {"tier": "flash-fast", "outcome": "ok", "cost_usd": 0.30})


def test_summary_math_for_one_session(store):
    _seed_summary_jobs(store)
    s = store.summary(session="s1")

    assert s["jobs"] == 3
    assert s["by_status"] == {"done": 2, "failed": 1}
    assert s["succeeded"] == 2
    assert s["first_try"] == 1
    assert s["escalated"] == 1
    assert s["success_rate"] == pytest.approx(2 / 3)
    assert s["tokens_in"] == 350
    assert s["tokens_out"] == 150
    assert s["cost_usd"] == pytest.approx(0.35)
    assert s["cost_per_success"] == pytest.approx(0.175)
    assert s["avg_seconds"] == pytest.approx(2.5)
    assert s["files_written"] == 3
    assert set(s["by_profile"]) == {"implement", "tests"}
    assert s["by_profile"]["implement"] == {"jobs": 2, "succeeded": 2, "cost_usd": 0.30}
    assert s["by_profile"]["tests"] == {"jobs": 1, "succeeded": 0, "cost_usd": 0.05}
    assert s["by_tier"] == {
        "flash-high": {"calls": 2, "passed": 1, "cost_usd": 0.16},
        "pro-high": {"calls": 1, "passed": 1, "cost_usd": 0.05},
    }


def test_summary_math_across_all_sessions(store):
    _seed_summary_jobs(store)
    s = store.summary()

    assert s["jobs"] == 4
    assert s["by_status"] == {"done": 3, "failed": 1}
    assert s["succeeded"] == 3
    assert s["first_try"] == 2
    assert s["escalated"] == 1
    assert s["success_rate"] == pytest.approx(3 / 4)
    assert s["tokens_in"] == 1349
    assert s["tokens_out"] == 1149
    assert s["cost_usd"] == pytest.approx(0.65)
    assert s["cost_per_success"] == pytest.approx(0.65 / 3, abs=1e-5)  # store rounds money to 5 decimals
    assert s["avg_seconds"] == pytest.approx((2.0 + 3.0 + 1.0) / 3)
    assert s["files_written"] == 4
    assert s["by_tier"] == {
        "flash-fast": {"calls": 1, "passed": 1, "cost_usd": 0.30},
        "flash-high": {"calls": 2, "passed": 1, "cost_usd": 0.16},
        "pro-high": {"calls": 1, "passed": 1, "cost_usd": 0.05},
    }


def test_summary_empty(store):
    s = store.summary()
    assert s["jobs"] == 0
    assert s["by_status"] == {}
    assert s["succeeded"] == 0
    assert s["first_try"] == 0
    assert s["escalated"] == 0
    assert s["success_rate"] == 0.0
    assert s["tokens_in"] == 0
    assert s["tokens_out"] == 0
    assert s["cost_usd"] == 0.0
    assert s["cost_per_success"] is None
    assert s["avg_seconds"] is None
    assert s["files_written"] == 0
    assert s["by_profile"] == {}
    assert s["by_tier"] == {}


def test_summary_without_any_success(store):
    store.upsert_job({
        "id": "f", "session": "sx", "profile": "tests", "status": "failed",
        "cost_usd": 0.2, "created": 1.0,
    })
    s = store.summary(session="sx")
    assert s["succeeded"] == 0
    assert s["success_rate"] == 0.0
    assert s["cost_per_success"] is None
    assert s["avg_seconds"] is None
    assert s["by_profile"] == {"tests": {"jobs": 1, "succeeded": 0, "cost_usd": 0.2}}


def test_mark_interrupted_only_touches_non_terminal_jobs(store):
    _job(store, "run", "s1", 1.0, status="running")
    _job(store, "queue", "s1", 2.0, status="queued")
    _job(store, "nostatus", "s1", 3.0)
    _job(store, "donejob", "s1", 4.0, status="done")
    _job(store, "failjob", "s1", 5.0, status="failed")

    assert store.mark_interrupted() == 3

    for job_id in ("run", "queue", "nostatus"):
        job = store.get_job(job_id)
        assert job["status"] == "interrupted"
        assert job["finished"] is not None
        assert [e["kind"] for e in store.events(job_id)] == ["interrupted"]

    assert store.get_job("donejob")["status"] == "done"
    assert store.get_job("donejob")["finished"] is None
    assert store.get_job("failjob")["status"] == "failed"
    assert store.events("donejob") == []

    assert store.mark_interrupted() == 0


# ----------------------------------------------------------------- budget --


def test_reserve_within_and_over_limit():
    b = Budget(limit_usd=1.0)
    assert b.remaining_usd == pytest.approx(1.0)

    assert b.reserve(0.25) is True
    assert b.reserved_usd == pytest.approx(0.25)
    assert b.remaining_usd == pytest.approx(0.75)

    assert b.reserve(0.80) is False
    assert b.reserved_usd == pytest.approx(0.25)
    assert b.remaining_usd == pytest.approx(0.75)

    assert b.reserve(0.75) is True
    assert b.remaining_usd == pytest.approx(0.0)
    assert b.reserve(0.0001) is False


def test_reserve_exactly_remaining_is_allowed():
    b = Budget(limit_usd=1.0)
    assert b.reserve(1.0) is True
    assert b.remaining_usd == pytest.approx(0.0)


def test_settle_moves_reserved_to_spent():
    b = Budget(limit_usd=1.0)
    assert b.reserve(0.5) is True
    b.settle(0.5, 0.2)
    assert b.reserved_usd == pytest.approx(0.0)
    assert b.spent_usd == pytest.approx(0.2)
    assert b.remaining_usd == pytest.approx(0.8)


def test_settle_never_drives_reserved_negative():
    b = Budget(limit_usd=1.0, reserved_usd=0.1)
    b.settle(0.5, 0.0)
    assert b.reserved_usd == 0.0


def test_budget_status_snapshot():
    b = Budget(limit_usd=2.0)
    b.reserve(0.5)
    b.settle(0.5, 0.3)
    assert b.status() == {
        "limit_usd": 2.0,
        "spent_usd": 0.3,
        "reserved_usd": 0.0,
        "remaining_usd": 1.7,
    }


def test_estimate_tokens():
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 7) == 3


def test_worst_case_cost_uses_tier_prices_and_reserve_out():
    tier = TIERS["flash-fast"]
    prompt, system = "a" * 100, "b" * 50
    expected = tier.cost(
        estimate_tokens(prompt) + estimate_tokens(system), tier.reserve_out
    )
    assert worst_case_cost(tier, prompt, system) == pytest.approx(expected)


def test_worst_case_cost_grows_with_prompt_and_system():
    tier = TIERS["flash-fast"]
    baseline = worst_case_cost(tier, "", "")
    assert worst_case_cost(tier, "x" * 1000, "") > baseline
    assert worst_case_cost(tier, "", "x" * 1000) > baseline
    assert worst_case_cost(tier, "y" * 4000, "") > worst_case_cost(tier, "y" * 40, "")


def test_worst_case_cost_reflects_reserve_out():
    # same prices, different reserve_out
    assert TIERS["flash-high"].price_in == TIERS["flash-fast"].price_in
    assert TIERS["flash-high"].price_out == TIERS["flash-fast"].price_out
    assert worst_case_cost(TIERS["flash-high"], "", "") > worst_case_cost(TIERS["flash-fast"], "", "")


def test_tier_cost_math():
    tier = TIERS["flash-fast"]
    assert tier.cost(0, 0) == 0.0
    assert tier.cost(1_000_000, 0) == pytest.approx(tier.price_in)
    assert tier.cost(0, 1_000_000) == pytest.approx(tier.price_out)
    assert tier.cost(2_000_000, 1_000_000) == pytest.approx(2 * tier.price_in + tier.price_out)


# ----------------------------------------------------------------- verify --


def test_parse_command_accepts_allowlisted_program():
    args = parse_command("python -m pytest -q")
    assert len(args) == 4
    assert args[1:] == ["-m", "pytest", "-q"]
    assert args[0]


@pytest.mark.parametrize("cmd", ["rm -rf /", "curl http://example.com", "bash -c ls"])
def test_parse_command_rejects_non_allowlisted_programs(cmd):
    with pytest.raises(ValueError):
        parse_command(cmd)


@pytest.mark.parametrize("cmd", [
    "pytest; rm -rf /",
    "pytest | cat",
    "pytest && echo hi",
    "pytest < input.txt",
    "pytest > out.txt",
    "pytest $HOME",
    "pytest `whoami`",
    'python -c "a; b"',
])
def test_parse_command_rejects_shell_metachars(cmd):
    with pytest.raises(ValueError):
        parse_command(cmd)


@pytest.mark.parametrize("cmd", ["", "   "])
def test_parse_command_rejects_empty(cmd):
    with pytest.raises(ValueError):
        parse_command(cmd)


async def test_run_check_success(tmp_path):
    result = await run_check(tmp_path, 'python -c "print(42)"', timeout=30)
    assert result.ok is True
    assert result.code == 0
    assert "42" in result.output


async def test_run_check_nonzero_exit(tmp_path):
    result = await run_check(tmp_path, 'python -c "raise SystemExit(3)"', timeout=30)
    assert result.ok is False
    assert result.code == 3


async def test_run_check_merges_stderr_into_output(tmp_path):
    result = await run_check(
        tmp_path, 'python -c "__import__(\'sys\').stderr.write(\'boom\')"', timeout=30
    )
    assert result.ok is True
    assert "boom" in result.output


async def test_run_check_timeout(tmp_path):
    result = await run_check(
        tmp_path, 'python -c "__import__(\'time\').sleep(5)"', timeout=1.0
    )
    assert result.ok is False
    assert result.code is None
    assert "timed out" in result.output


async def test_run_check_rejects_bad_command(tmp_path):
    with pytest.raises(ValueError):
        await run_check(tmp_path, "rm -rf /", timeout=5)
