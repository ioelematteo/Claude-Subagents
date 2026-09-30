"""Job engine: DAG scheduling, escalation ladder, verify-and-repair loop, approval gates, cost budget.

One Engine lives for the whole MCP session. Jobs run as asyncio tasks; every state change is persisted
to the Store so history, stats and retries survive restarts.
"""
import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from swarm import config, workspace
from swarm.budget import Budget, worst_case_cost
from swarm.store import TERMINAL, Store
from swarm.verify import parse_command, run_check

ProfileName = Literal["implement", "tests", "review", "bulk", "digest", "write"]
LLM = Callable[..., Awaitable[tuple[str, Any]]]

OK_WRITES = ("created", "overwritten")
# Provider errors that escalation cannot fix: stop the job instead of burning the ladder.
FATAL_HTTP = {400: "bad request", 401: "invalid API key", 402: "account out of credit", 403: "forbidden"}


class JobSpec(BaseModel):
    agent: ProfileName
    task: str = Field(description="One imperative instruction that names the output path(s).")
    context: str = Field("", description="Spec, contracts, conventions. Pass code via context_files.")
    context_files: list[str] = Field(default_factory=list, description="Paths or globs relative to root; the server reads them.")
    root: str = Field("", description="Absolute project path. Required with context_files, apply or verify.")
    apply: bool = Field(False, description="The server writes produced files under root (transactionally).")
    overwrite: bool = Field(False, description="With apply: allow overwriting files that existed before the job.")
    label: str = Field("", description="Short unique name; other jobs in the batch can depend on it via `after`.")
    after: list[str] = Field(default_factory=list, description="Labels or job ids that must be done first; their written files are added to this job's context.")
    verify: str = Field("", description="Command run in root after writing (e.g. 'python -m pytest -q tests/test_x.py'). On failure the error is fed back and the job escalates to a stronger tier; if every tier fails, its writes are rolled back.")
    max_attempts: int = Field(0, ge=0, le=6, description="0 = the profile's full escalation ladder.")
    gate: Literal["auto", "approve"] = Field("auto", description="'approve': after passing, wait for approve/reject (reject rolls back).")
    tiers: list[str] | None = Field(None, description="Override the escalation ladder (tier names). Mostly for evals.")

    @model_validator(mode="after")
    def _check(self) -> "JobSpec":
        if (self.verify or self.gate == "approve") and not self.apply:
            raise ValueError("verify and gate='approve' require apply=true")
        for t in self.tiers or []:
            if t not in config.TIERS:
                raise ValueError(f"unknown tier '{t}'. Valid: {list(config.TIERS)}")
        if self.verify:
            parse_command(self.verify)
        return self


@dataclass
class Job:
    id: str
    spec: JobSpec
    session: str
    root: Path | None
    deps: list["Job"] = field(default_factory=list)
    status: str = "queued"
    tier: str | None = None
    attempts: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    result: str | None = None
    notes: str | None = None
    error: str | None = None
    written: list[dict] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    backup: dict[str, bytes | None] = field(default_factory=dict)
    verify_output: str | None = None
    skipped_context: list[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    task: asyncio.Task | None = None
    settled: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def label(self) -> str:
        return self.spec.label or self.spec.task[:40]

    def row(self) -> dict:
        return {
            "id": self.id, "session": self.session, "label": self.label, "profile": self.spec.agent,
            "status": self.status, "tier": self.tier, "attempts": self.attempts,
            "tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "cost_usd": round(self.cost, 6),
            "created": self.created, "started": self.started, "finished": self.finished,
            "root": str(self.root) if self.root else None, "verify": self.spec.verify or None,
            "files": self.files, "error": self.error, "spec": self.spec.model_dump(),
        }

    def info(self, with_result: bool = False, full: bool = False) -> dict:
        end = self.finished or time.time()
        data: dict[str, Any] = {
            "job_id": self.id, "label": self.label, "agent": self.spec.agent, "status": self.status,
            "tier": self.tier, "attempts": self.attempts,
            "seconds": round(end - (self.started or self.created), 1),
        }
        if self.skipped_context:
            data["skipped_context"] = self.skipped_context
        if not with_result:
            return data
        if self.error:
            data["error"] = self.error
        if self.spec.apply and not full:
            data["written"] = self.written
            if self.notes:
                data["notes"] = self.notes
        elif self.result is not None:
            data["result"] = self.result
        if self.verify_output and self.status != "done":
            data["verify_output"] = self.verify_output
        data["cost"] = {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "usd": round(self.cost, 5)}
        return data


def _default_llm() -> LLM:
    from callAi import call  # imported lazily: tests inject a fake and need no API key

    return call


class Engine:
    def __init__(self, store: Store, budget: Budget, llm: LLM | None = None, session: str | None = None,
                 max_concurrent: int = config.MAX_CONCURRENT):
        self.store = store
        self.budget = budget
        self.llm = llm or _default_llm()
        self.session = session or uuid.uuid4().hex[:8]
        self.jobs: dict[str, Job] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.verify_locks: dict[Path, asyncio.Lock] = {}

    # ---------- submission ----------

    def submit(self, spec: JobSpec) -> Job:
        return self.submit_many([spec])[0]

    def submit_many(self, specs: list[JobSpec]) -> list[Job]:
        """Validate the whole batch, resolve dependencies, reject cycles, then start every job."""
        labels = [s.label for s in specs if s.label]
        if len(labels) != len(set(labels)):
            raise ValueError("labels must be unique within a batch")
        jobs = []
        for spec in specs:
            needs_root = spec.root or spec.context_files or spec.apply
            root = workspace.get_root(spec.root) if needs_root else None
            if spec.context_files:  # fail at submit on paths outside root; files may still be produced by deps
                workspace.expand(root, spec.context_files)
            jobs.append(Job(id=uuid.uuid4().hex[:8], spec=spec, session=self.session, root=root))
        by_label = {j.spec.label: j for j in jobs if j.spec.label}
        for job in jobs:
            job.deps = [self._resolve(ref, by_label) for ref in job.spec.after]
        self._check_cycles(jobs)
        for job in jobs:
            self.jobs[job.id] = job
            self.store.upsert_job(job.row())
            self.store.add_event(job.id, "submitted", {"after": [d.id for d in job.deps]})
            job.task = asyncio.create_task(self._run(job))
        return jobs

    def _resolve(self, ref: str, batch: dict[str, Job]) -> Job:
        if ref in batch:
            return batch[ref]
        if ref in self.jobs:
            return self.jobs[ref]
        for job in reversed(list(self.jobs.values())):
            if job.spec.label == ref:
                return job
        raise ValueError(f"unknown dependency '{ref}' (not a label in this batch or a job of this session)")

    @staticmethod
    def _check_cycles(jobs: list[Job]) -> None:
        state: dict[str, int] = {}  # 1 = visiting, 2 = done

        def visit(job: Job) -> None:
            if state.get(job.id) == 1:
                raise ValueError(f"dependency cycle through '{job.label}'")
            if state.get(job.id) == 2:
                return
            state[job.id] = 1
            for dep in job.deps:
                visit(dep)
            state[job.id] = 2

        for job in jobs:
            visit(job)

    # ---------- state ----------

    def _set(self, job: Job, status: str, data: dict | None = None) -> None:
        job.status = status
        if status in TERMINAL or status == "awaiting_approval":
            job.finished = time.time()
        self.store.upsert_job(job.row())
        self.store.add_event(job.id, status, data)
        if status in TERMINAL:
            job.settled.set()

    def _rollback(self, job: Job) -> None:
        if job.backup and job.root:
            restored = workspace.rollback(job.root, job.backup)
            self.store.add_event(job.id, "rolled_back", {"paths": restored})
            job.backup = {}
            job.files = []

    # ---------- execution ----------

    async def _run(self, job: Job) -> None:
        try:
            if job.deps:
                self._set(job, "waiting", {"on": [d.id for d in job.deps]})
                await asyncio.gather(*(d.settled.wait() for d in job.deps))
                failed = [f"{d.label}={d.status}" for d in job.deps if d.status != "done"]
                if failed:
                    job.error = "dependency not done: " + ", ".join(failed)
                    self._set(job, "blocked")
                    return
            async with self.semaphore:
                await self._attempts(job)
        except asyncio.CancelledError:
            self._rollback(job)
            self._set(job, "cancelled")
            raise
        except Exception as e:
            job.error = f"{type(e).__name__}: {e}"
            self._rollback(job)
            self._set(job, "failed")

    def _plan(self, job: Job) -> list[str]:
        ladder = list(job.spec.tiers or config.PROFILES[job.spec.agent].ladder)
        n = job.spec.max_attempts or len(ladder)
        return (ladder + [ladder[-1]] * n)[:n]

    def _base_prompt(self, job: Job) -> str:
        patterns = list(job.spec.context_files)
        for dep in job.deps:
            patterns += [f for f in dep.files if f not in patterns]
        files_text = ""
        if patterns:
            files_text, _, job.skipped_context = workspace.read_context(job.root, patterns)
        context = "\n\n".join(p for p in (job.spec.context, files_text) if p) or "(none)"
        return f"<task>\n{job.spec.task}\n</task>\n\n<context>\n{context}\n</context>"

    async def _attempts(self, job: Job) -> None:
        profile = config.PROFILES[job.spec.agent]
        base = self._base_prompt(job)
        feedback = ""
        outcome = "not started"
        for n, tier_name in enumerate(self._plan(job), 1):
            tier = config.TIERS[tier_name]
            prompt = base + feedback
            reserved = worst_case_cost(tier, prompt, profile.system)
            if not self.budget.reserve(reserved):
                job.error = (f"budget exhausted: attempt {n} on {tier.name} needs up to ${reserved:.4f}, "
                             f"${self.budget.remaining_usd:.4f} left of ${self.budget.limit_usd:.2f}")
                self._rollback(job)
                self._set(job, "over_budget")
                return
            job.attempts, job.tier = n, tier.name
            job.started = job.started or time.time()
            self._set(job, "running", {"attempt": n, "tier": tier.name})
            t0 = time.time()
            actual, tokens_in, tokens_out = 0.0, 0, 0
            try:
                async with asyncio.timeout(config.ATTEMPT_TIMEOUT):
                    content, usage = await self.llm(prompt, system=profile.system, model=tier.model,
                                                    thinking=tier.thinking, effort=tier.effort, with_usage=True)
                if usage:
                    tokens_in, tokens_out = usage.prompt_tokens, usage.completion_tokens
                actual = tier.cost(tokens_in, tokens_out)
            except Exception as e:
                outcome = f"error: {type(e).__name__}: {e}"[:300]
                self._attempt_event(job, tier, 0, 0, 0.0, t0, outcome)
                status = getattr(e, "status_code", None)
                if status in FATAL_HTTP:  # no other tier can fix auth, billing or a malformed request
                    job.error = f"provider refused the request (HTTP {status}, {FATAL_HTTP[status]}): {e}"[:500]
                    self._rollback(job)
                    self._set(job, "failed")
                    return
                continue  # timeout, rate limit, 5xx: try the next tier with the same prompt
            finally:
                self.budget.settle(reserved, actual)
            job.tokens_in += tokens_in
            job.tokens_out += tokens_out
            job.cost += actual
            job.result = content
            outcome, feedback = await self._check(job, content)
            self._attempt_event(job, tier, tokens_in, tokens_out, actual, t0, outcome)
            if outcome == "ok":
                if job.spec.gate == "approve":
                    self._set(job, "awaiting_approval")
                else:
                    job.backup = {}
                    self._set(job, "done")
                return
            if outcome == "missing":  # a stronger model cannot supply missing context
                job.error = "worker reported missing context: " + (job.notes or "")
                self._rollback(job)
                self._set(job, "failed")
                return
        job.error = job.error or f"failed after {job.attempts} attempt(s); last outcome: {outcome}"
        self._rollback(job)
        self._set(job, "failed")

    def _attempt_event(self, job: Job, tier: config.Tier, tokens_in: int, tokens_out: int,
                       cost: float, t0: float, outcome: str) -> None:
        self.store.add_event(job.id, "attempt", {
            "tier": tier.name, "model": tier.model, "tokens_in": tokens_in, "tokens_out": tokens_out,
            "cost_usd": round(cost, 6), "seconds": round(time.time() - t0, 2),
            "outcome": outcome.split(":")[0],
        })

    async def _check(self, job: Job, content: str) -> tuple[str, str]:
        """Apply and verify one attempt. Returns (outcome, feedback for the next attempt)."""
        spec = job.spec
        if not spec.apply:
            if content.lstrip().startswith("MISSING:"):
                job.notes = content.strip()
                return "missing", ""
            return "ok", ""

        files, notes = workspace.parse_files(content)
        job.notes = notes or None
        if not files:
            if notes and "MISSING:" in notes:
                return "missing", ""
            return "no_files", _feedback(content, "Your answer contained no '=== FILE: path ===' blocks. "
                                                  "Output every requested file, complete, in the required format.")
        report = workspace.write_files(job.root, files, spec.overwrite, backup=job.backup)
        job.written = report
        job.files = sorted(set(job.files) | {r["path"] for r in report if r["status"] in OK_WRITES})
        self.store.add_event(job.id, "files", {"report": report})
        if not any(r["status"] in OK_WRITES for r in report):
            reasons = "; ".join(f"{r['path']}: {r['status']}" for r in report)
            return "refused", _feedback(content, f"None of your files could be written: {reasons}.")

        if not spec.verify:
            return "ok", ""
        self._set(job, "verifying")
        lock = self.verify_locks.setdefault(job.root, asyncio.Lock())
        async with lock:  # checks share the working tree: run them one at a time per project
            result = await run_check(job.root, spec.verify, config.VERIFY_TIMEOUT)
        job.verify_output = result.output[-2_000:]
        self.store.add_event(job.id, "verify", {"ok": result.ok, "code": result.code, "tail": result.output[-1_500:]})
        if result.ok:
            return "ok", ""
        return "verify_failed", _feedback(content, (
            f"Your files were written to disk and the command `{spec.verify}` failed:\n{result.output}\n\n"
            "Find the root cause and output the COMPLETE corrected files. If a test contradicts the spec in the "
            "context, do not bend the code to it: explain on a line starting with 'MISSING:'."))

    # ---------- control ----------

    def get(self, job_id: str) -> Job:
        if job_id not in self.jobs:
            raise ValueError(f"job '{job_id}' not found in this session")
        return self.jobs[job_id]

    def approve(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status != "awaiting_approval":
            raise ValueError(f"job '{job_id}' is {job.status}, not awaiting_approval")
        job.backup = {}
        self._set(job, "done", {"approved": True})
        return job

    def reject(self, job_id: str, feedback: str = "", retry: bool = False) -> tuple[Job, Job | None]:
        job = self.get(job_id)
        if job.status != "awaiting_approval":
            raise ValueError(f"job '{job_id}' is {job.status}, not awaiting_approval")
        self._rollback(job)
        job.error = f"rejected: {feedback}" if feedback else "rejected"
        self._set(job, "rejected", {"feedback": feedback})
        new = self.retry(job_id, feedback) if retry else None
        return job, new

    def retry(self, job_id: str, feedback: str = "") -> Job:
        """Resubmit a finished job from its stored spec (works for jobs of previous sessions too)."""
        row = self.store.get_job(job_id)
        if not row or not row.get("spec"):
            raise ValueError(f"job '{job_id}' not found")
        if row["status"] not in TERMINAL:
            raise ValueError(f"job '{job_id}' is still {row['status']}")
        spec = JobSpec(**row["spec"])
        extra = f"\n\nFeedback on a previous attempt of this job: {feedback}" if feedback else ""
        label = f"{spec.label}-retry" if spec.label else ""
        # a finished job's files are on disk now: redoing the job must be allowed to replace them
        overwrite = spec.overwrite or row["status"] == "done"
        new = self.submit(spec.model_copy(update={
            "context": spec.context + extra, "after": [], "label": label, "overwrite": overwrite}))
        self.store.add_event(new.id, "retry_of", {"job_id": job_id})
        return new

    async def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status == "awaiting_approval":
            self.reject(job_id, "cancelled")
        elif job.task and not job.task.done():
            job.task.cancel()
            await asyncio.wait({job.task})
        return job

    async def wait_any(self, jobs: list[Job], timeout: float) -> None:
        pending = [j.task for j in jobs if j.task and not j.task.done()]
        if pending and len(pending) == len(jobs):
            await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)


def _feedback(previous: str, problem: str) -> str:
    return (f"\n\n<previous_attempt>\n{previous[-30_000:]}\n</previous_attempt>\n\n"
            f"<problem>\n{problem}\n</problem>")
