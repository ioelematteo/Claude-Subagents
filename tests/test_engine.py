"""Tests for swarm/engine.py: DAG scheduling, escalation ladder, verify-and-repair, gates and budget.

Everything runs offline against a scripted fake LLM (no network, no API key, no callAi import).
"""
import asyncio
import types
from dataclasses import dataclass

import pytest

from swarm import config
from swarm.budget import Budget
from swarm.engine import Engine, JobSpec
from swarm.store import Store

# the implement ladder comes from config, so tuning it from eval data doesn't break the tests
L0, L1, L2 = config.PROFILES["implement"].ladder

USAGE = types.SimpleNamespace(prompt_tokens=120, completion_tokens=40)

VERIFY = "python -m pytest -q -p no:cacheprovider test_target.py"

# Created by the tests themselves in tmp_path; out.txt must end up containing "ok".
TEST_TARGET = '''\
from pathlib import Path


def test_out_txt_contains_ok():
    out = Path(__file__).with_name("out.txt")
    assert out.read_text().strip() == "ok"
'''


@dataclass
class Call:
    prompt: str
    system: str | None
    model: str | None
    thinking: bool | None
    effort: str | None


class FakeLLM:
    """Async callable with the engine's LLM signature; replays scripted responses in order.

    A scripted item is either an exception instance (raised) or a ``(content, usage)`` tuple.
    Once the script is exhausted the last item is repeated. Every call is recorded.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[Call] = []

    async def __call__(self, prompt, system=None, model=None, thinking=None, effort=None,
                       with_usage=True):
        self.calls.append(Call(prompt, system, model, thinking, effort))
        item = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(item, BaseException):
            raise item
        content, usage = item
        return content, usage

    @property
    def prompts(self):
        return [c.prompt for c in self.calls]


def file_block(path: str, content: str, lang: str = "python") -> str:
    return f"=== FILE: {path} ===\n```{lang}\n{content}\n```"


def make_engine(llm, limit_usd: float = 1.0) -> Engine:
    return Engine(Store(":memory:"), Budget(limit_usd), llm=llm)


async def await_settled(job, timeout: float = 60.0):
    """Wait for a terminal state (never hang the suite if the engine misbehaves)."""
    await asyncio.wait_for(job.settled.wait(), timeout)
    return job


def attempt_events(engine: Engine, job) -> list[dict]:
    return [e for e in engine.store.events(job.id) if e["kind"] == "attempt"]


def event_kinds(engine: Engine, job) -> list[str]:
    return [e["kind"] for e in engine.store.events(job.id)]


# ---------------------------------------------------------------- happy path


async def test_success_without_verify(tmp_path):
    llm = FakeLLM([(file_block("hello.txt", "hi", "text"), USAGE)])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Write hello.txt with 'hi'.",
                                root=str(tmp_path), apply=True))
    await await_settled(job)

    assert job.status == "done"
    assert job.attempts == 1
    assert job.tier == L0
    assert (tmp_path / "hello.txt").read_text().strip() == "hi"
    assert job.written and job.written[0]["status"] == "created"
    assert any(f.endswith("hello.txt") for f in job.files)
    assert job.cost > 0.0
    assert (job.tokens_in, job.tokens_out) == (120, 40)

    assert len(llm.calls) == 1
    assert llm.calls[0].model == "deepseek-flash"
    assert llm.calls[0].effort == config.TIERS[L0].effort
    assert "Write hello.txt with 'hi'." in llm.calls[0].prompt


# ---------------------------------------------------------------- verify loop


async def test_verify_failure_escalates_then_passes(tmp_path):
    (tmp_path / "test_target.py").write_text(TEST_TARGET)
    llm = FakeLLM([
        (file_block("out.txt", "bad", "text"), USAGE),
        (file_block("out.txt", "ok", "text"), USAGE),
    ])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Write out.txt so the test passes.",
                                root=str(tmp_path), apply=True, overwrite=True, verify=VERIFY))
    await await_settled(job)

    assert job.status == "done"
    assert job.attempts == 2
    assert (tmp_path / "out.txt").read_text().strip() == "ok"

    # first two tiers of the implement ladder
    events = attempt_events(engine, job)
    assert [e["data"]["tier"] for e in events] == [L0, L1]
    assert [e["data"]["outcome"] for e in events] == ["verify_failed", "ok"]
    assert [c.effort for c in llm.calls] == [config.TIERS[L0].effort, config.TIERS[L1].effort]
    assert [c.thinking for c in llm.calls] == [True, True]
    assert {c.model for c in llm.calls} == {"deepseek-flash"}

    # the repair prompt carries the previous answer and the real failure output
    second = llm.calls[1].prompt
    assert "<previous_attempt>" in second
    assert "<problem>" in second
    assert "bad" in second                  # the content of the failed attempt
    assert "test_target.py" in second       # the failing command
    assert "1 failed" in second             # pytest's failure summary

    # one verify event per verified attempt
    verify_events = [e for e in engine.store.events(job.id) if e["kind"] == "verify"]
    assert [e["data"]["ok"] for e in verify_events] == [False, True]


async def test_ladder_exhausted_fails_and_rolls_back_all_writes(tmp_path):
    (tmp_path / "test_target.py").write_text(TEST_TARGET)
    (tmp_path / "keep.txt").write_text("original")
    bad = file_block("out.txt", "bad", "text") + "\n" + file_block("keep.txt", "clobbered", "text")
    llm = FakeLLM([(bad, USAGE)])  # repeated for every tier
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Write out.txt and keep.txt.",
                                root=str(tmp_path), apply=True, overwrite=True, verify=VERIFY))
    await await_settled(job)

    assert job.status == "failed"
    assert job.attempts == 3                  # the full implement ladder
    assert len(llm.calls) == 3
    assert [c.effort for c in llm.calls] == [config.TIERS[t].effort for t in (L0, L1, L2)]
    assert job.error.startswith("failed after 3 attempt(s)")

    # created file deleted, overwritten file restored
    assert not (tmp_path / "out.txt").exists()
    assert (tmp_path / "keep.txt").read_text() == "original"
    assert job.backup == {}
    assert job.files == []
    assert "rolled_back" in event_kinds(engine, job)


async def test_max_attempts_one_limits_the_ladder(tmp_path):
    (tmp_path / "test_target.py").write_text(TEST_TARGET)
    llm = FakeLLM([(file_block("out.txt", "bad", "text"), USAGE)])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Write out.txt.",
                                root=str(tmp_path), apply=True, overwrite=True,
                                verify=VERIFY, max_attempts=1))
    await await_settled(job)

    assert job.status == "failed"
    assert job.attempts == 1
    assert len(llm.calls) == 1
    assert job.tier == L0
    assert not (tmp_path / "out.txt").exists()


# ---------------------------------------------------------------- worker answers


async def test_missing_context_fails_immediately_without_escalation():
    llm = FakeLLM([
        ("MISSING: the ticket does not define the response schema", USAGE),
        ("should never be called", USAGE),
    ])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Implement the endpoint."))
    await await_settled(job)

    assert job.status == "failed"
    assert job.attempts == 1
    assert job.tier == L0
    assert len(llm.calls) == 1
    assert job.notes.startswith("MISSING:")
    assert "missing context" in job.error
    assert job.settled.is_set() is not False  # settled was set (terminal)


async def test_answer_without_file_blocks_is_retried(tmp_path):
    llm = FakeLLM([
        ("Sure! Here is the plan, but without any file blocks.", USAGE),
        (file_block("hello.txt", "hi", "text"), USAGE),
    ])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Write hello.txt.",
                                root=str(tmp_path), apply=True))
    await await_settled(job)

    assert job.status == "done"
    assert job.attempts == 2
    assert (tmp_path / "hello.txt").read_text().strip() == "hi"
    assert [e["data"]["outcome"] for e in attempt_events(engine, job)] == ["no_files", "ok"]

    second = llm.calls[1].prompt
    assert "no '=== FILE: path ===' blocks" in second
    assert "<previous_attempt>" in second
    assert "Here is the plan" in second


# ---------------------------------------------------------------- budget


async def test_budget_too_small_yields_over_budget_without_calls(tmp_path):
    llm = FakeLLM([(file_block("hello.txt", "hi", "text"), USAGE)])
    engine = make_engine(llm, limit_usd=0.0)
    job = engine.submit(JobSpec(agent="implement", task="Write hello.txt.",
                                root=str(tmp_path), apply=True))
    await await_settled(job)

    assert job.status == "over_budget"
    assert job.attempts == 0
    assert llm.calls == []
    assert "budget exhausted" in job.error
    assert job.cost == 0.0
    assert not (tmp_path / "hello.txt").exists()


# ---------------------------------------------------------------- approval gate


async def test_gate_approve_then_approve(tmp_path):
    llm = FakeLLM([(file_block("hello.txt", "hi", "text"), USAGE)])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Write hello.txt.",
                                root=str(tmp_path), apply=True, gate="approve"))
    await asyncio.wait_for(job.task, 60)

    assert job.status == "awaiting_approval"
    assert (tmp_path / "hello.txt").read_text().strip() == "hi"
    assert not job.settled.is_set()

    engine.approve(job.id)
    assert job.status == "done"
    assert job.settled.is_set()
    assert "approved" in event_kinds(engine, job) or "done" in event_kinds(engine, job)


async def test_gate_reject_rolls_back(tmp_path):
    llm = FakeLLM([(file_block("hello.txt", "hi", "text"), USAGE)])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Write hello.txt.",
                                root=str(tmp_path), apply=True, gate="approve"))
    await asyncio.wait_for(job.task, 60)
    assert job.status == "awaiting_approval"

    rejected, new = engine.reject(job.id, "not what I asked for")

    assert rejected.status == "rejected"
    assert new is None
    assert rejected.error == "rejected: not what I asked for"
    assert rejected.settled.is_set()
    assert not (tmp_path / "hello.txt").exists()

    kinds = event_kinds(engine, job)
    assert "rolled_back" in kinds
    assert "rejected" in kinds


async def test_reject_with_retry_returns_new_job(tmp_path):
    llm = FakeLLM([(file_block("hello.txt", "hi", "text"), USAGE)])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Write hello.txt.", label="g",
                                root=str(tmp_path), apply=True, gate="approve"))
    await asyncio.wait_for(job.task, 60)
    assert job.status == "awaiting_approval"

    rejected, new = engine.reject(job.id, "add type hints", retry=True)

    assert rejected.status == "rejected"
    assert new is not None and new.id != job.id
    assert new.spec.agent == "implement"
    assert new.spec.label == "g-retry"
    assert new.spec.after == []
    assert "add type hints" in new.spec.context
    assert "retry_of" in event_kinds(engine, new)

    await asyncio.wait_for(new.task, 60)
    assert new.status == "awaiting_approval"
    assert new.spec.gate == "approve"


# ---------------------------------------------------------------- DAG


async def test_dependent_job_waits_and_receives_dependency_files(tmp_path):
    payload = "SHARED_PAYLOAD = 42"
    llm = FakeLLM([
        (file_block("a_out.py", payload), USAGE),
        (file_block("b_out.py", "print('b')"), USAGE),
    ])
    engine = make_engine(llm)
    a = engine.submit(JobSpec(agent="implement", task="A_TASK write a_out.py", label="a",
                              root=str(tmp_path), apply=True))
    b = engine.submit(JobSpec(agent="implement", task="B_TASK write b_out.py", label="b",
                              after=["a"], root=str(tmp_path), apply=True))

    await asyncio.wait_for(asyncio.gather(a.settled.wait(), b.settled.wait()), 60)

    assert a.status == "done" and b.status == "done"
    assert b.attempts == 1
    assert len(llm.calls) == 2
    # A ran (and finished) before B was ever prompted
    assert "A_TASK" in llm.calls[0].prompt
    assert "B_TASK" in llm.calls[1].prompt
    # B's context contains the content A wrote
    assert payload in llm.calls[1].prompt


async def test_dependency_failed_blocks_dependent():
    llm = FakeLLM([("MISSING: no schema given", USAGE)])
    engine = make_engine(llm)
    a = engine.submit(JobSpec(agent="implement", task="A_TASK", label="a"))
    b = engine.submit(JobSpec(agent="implement", task="B_TASK", label="b", after=["a"]))

    await await_settled(b)

    assert a.status == "failed"
    assert b.status == "blocked"
    assert b.error == "dependency not done: a=failed"
    assert len(llm.calls) == 1  # only A ever reached the model
    assert "waiting" in event_kinds(engine, b)


async def test_cancel_of_job_waiting_on_dependency(tmp_path):
    release = asyncio.Event()

    class HangingFake(FakeLLM):
        async def __call__(self, prompt, **kwargs):
            if "A_TASK" in prompt:
                await release.wait()
            return await super().__call__(prompt, **kwargs)

    llm = HangingFake([("MISSING: nothing to do", USAGE)])
    engine = make_engine(llm)
    a = engine.submit(JobSpec(agent="implement", task="A_TASK", label="a"))
    b = engine.submit(JobSpec(agent="implement", task="B_TASK", label="b", after=["a"]))

    for _ in range(200):
        if b.status == "waiting":
            break
        await asyncio.sleep(0.005)
    else:
        pytest.fail(f"job b never entered 'waiting' (status={b.status})")

    await engine.cancel(b.id)

    assert b.status == "cancelled"
    assert b.settled.is_set()
    assert "cancelled" in event_kinds(engine, b)
    assert len(llm.calls) == 0  # A is still hanging and B never called the model

    release.set()
    await asyncio.wait_for(a.settled.wait(), 60)


# ---------------------------------------------------------------- submission validation


async def test_duplicate_labels_rejected():
    engine = make_engine(FakeLLM([]))
    specs = [
        JobSpec(agent="implement", task="one", label="same"),
        JobSpec(agent="implement", task="two", label="same"),
    ]
    with pytest.raises(ValueError, match="labels must be unique"):
        engine.submit_many(specs)


async def test_dependency_cycle_rejected():
    engine = make_engine(FakeLLM([]))
    specs = [
        JobSpec(agent="implement", task="one", label="x", after=["y"]),
        JobSpec(agent="implement", task="two", label="y", after=["x"]),
    ]
    with pytest.raises(ValueError, match="cycle"):
        engine.submit_many(specs)


async def test_unknown_dependency_rejected():
    engine = make_engine(FakeLLM([]))
    with pytest.raises(ValueError, match="unknown dependency"):
        engine.submit(JobSpec(agent="implement", task="one", after=["nope"]))


async def test_get_unknown_job_raises():
    engine = make_engine(FakeLLM([]))
    with pytest.raises(ValueError, match="not found"):
        engine.get("deadbeef")


# ---------------------------------------------------------------- retry


async def test_retry_resubmits_from_stored_spec(tmp_path):
    llm = FakeLLM([(file_block("r.txt", "v1", "text"), USAGE), (file_block("r.txt", "v2", "text"), USAGE)])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="write r.txt", label="first",
                                root=str(tmp_path), apply=True))
    await await_settled(job)
    assert job.status == "done"

    new = engine.retry(job.id, "please add a blank line")

    assert new.id != job.id
    assert new.spec.agent == job.spec.agent
    assert new.spec.label == "first-retry"
    assert new.spec.after == []
    assert "please add a blank line" in new.spec.context
    assert "retry_of" in event_kinds(engine, new)

    await await_settled(new)
    assert new.status == "done"
    assert new.spec.overwrite  # a done job's files are replaced by its retry
    assert "v2" in (tmp_path / "r.txt").read_text()


async def test_retry_of_running_job_raises():
    release = asyncio.Event()

    class HangingFake(FakeLLM):
        async def __call__(self, prompt, **kwargs):
            await release.wait()
            return await super().__call__(prompt, **kwargs)

    llm = HangingFake([("late", USAGE)])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="slow task"))
    for _ in range(200):
        if job.status == "running":
            break
        await asyncio.sleep(0.005)
    else:
        pytest.fail(f"job never reached 'running' (status={job.status})")

    with pytest.raises(ValueError, match="still running"):
        engine.retry(job.id)

    release.set()
    await await_settled(job)


# ---------------------------------------------------------------- escalation on API error


async def test_llm_exception_escalates_and_succeeds():
    llm = FakeLLM([RuntimeError("boom"), ("all good", USAGE)])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Do the thing."))
    await await_settled(job)

    assert job.status == "done"
    assert job.attempts == 2
    assert job.tier == L1
    assert [c.effort for c in llm.calls] == [config.TIERS[L0].effort, config.TIERS[L1].effort]

    events = attempt_events(engine, job)
    assert [e["data"]["outcome"] for e in events] == ["error", "ok"]
    assert events[0]["data"]["tokens_in"] == 0
    assert events[0]["data"]["model"] == "deepseek-flash"
    assert events[0]["data"]["tier"] == L0
    assert events[1]["data"]["tier"] == L1


# ---------------------------------------------------------------- events / speculation


async def test_attempt_event_per_model_call(tmp_path):
    llm = FakeLLM([
        ("an answer with no file blocks", USAGE),
        (file_block("hello.txt", "hi", "text"), USAGE),
    ])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Write hello.txt.",
                                root=str(tmp_path), apply=True))
    await await_settled(job)

    events = attempt_events(engine, job)
    assert len(events) == len(llm.calls) == 2
    for event, call in zip(events, llm.calls, strict=True):
        assert event["data"]["model"] == call.model
        assert event["data"]["tier"] in {L0, L1}
        assert {"tier", "model", "tokens_in", "tokens_out", "cost_usd", "seconds",
                "outcome"} <= set(event["data"])
    assert [e["data"]["outcome"] for e in events] == ["no_files", "ok"]
    assert events[1]["data"]["tokens_in"] == 120
    assert events[1]["data"]["tokens_out"] == 40
    assert events[1]["data"]["cost_usd"] > 0
    assert engine.store.events(job.id)[0]["kind"] == "submitted"


# ---------------------------------------------------------------- JobSpec validation


def test_spec_verify_without_apply_raises():
    with pytest.raises(ValueError):
        JobSpec(agent="implement", task="Do it.", verify=VERIFY)


def test_spec_approve_gate_without_apply_raises():
    with pytest.raises(ValueError):
        JobSpec(agent="implement", task="Do it.", gate="approve")


def test_spec_unknown_tier_raises():
    with pytest.raises(ValueError, match="unknown tier"):
        JobSpec(agent="implement", task="Do it.", tiers=["flash-high", "not-a-tier"])


def test_spec_verify_with_shell_metacharacters_raises(tmp_path):
    with pytest.raises(ValueError):  # pydantic's ValidationError subclasses ValueError
        JobSpec(agent="implement", task="Do it.", root=str(tmp_path), apply=True,
                verify="python -m pytest -q | tee out.txt; rm -rf /")


def test_spec_accepts_a_valid_verify_command(tmp_path):
    spec = JobSpec(agent="implement", task="Do it.", root=str(tmp_path), apply=True,
                   verify=VERIFY)
    assert spec.verify == VERIFY
    assert spec.apply is True


class HTTPError(Exception):
    """Mimics the provider SDK's status errors, which carry `status_code`."""

    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


@pytest.mark.parametrize("status", [400, 401, 402, 403])
async def test_fatal_provider_error_stops_without_escalating(status):
    llm = FakeLLM([HTTPError(status), ("never reached", USAGE)])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Do it."))
    await await_settled(job)

    assert job.status == "failed"
    assert job.attempts == 1
    assert len(llm.calls) == 1
    assert f"HTTP {status}" in job.error


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_transient_provider_error_escalates(status):
    llm = FakeLLM([HTTPError(status), ("all good", USAGE)])
    engine = make_engine(llm)
    job = engine.submit(JobSpec(agent="implement", task="Do it."))
    await await_settled(job)

    assert job.status == "done"
    assert [c.model for c in llm.calls] == [config.TIERS[L0].model, config.TIERS[L1].model]


def test_context_files_outside_root_rejected_at_submit(tmp_path):
    engine = Engine(Store(":memory:"), Budget(1.0), llm=FakeLLM([("x", USAGE)]))
    with pytest.raises(ValueError, match="outside the project"):
        engine.submit(JobSpec(agent="digest", task="x", root=str(tmp_path), context_files=["../secret.txt"]))
    assert engine.jobs == {}
