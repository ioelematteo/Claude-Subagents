"""MCP entrypoint: a thin layer exposing the swarm engine to Claude Code."""
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from swarm import config
from swarm.budget import Budget
from swarm.engine import Engine, JobSpec, ProfileName
from swarm.store import Store

INSTRUCTIONS = """\
You have a swarm of cheap, fast DeepSeek workers (Flash ~20x cheaper than you, escalating to V4 Pro only
when needed; 1M context; 8 in parallel). Use them BY DEFAULT to cut your own token usage, without being
asked, whenever work is bounded and verifiable: implementing files from a clear spec, tests, boilerplate/
CRUD/schemas/mock data, repetitive edits, first-pass review, summarizing long material, docs/translations.
Keep for yourself: architecture, contracts, debugging, decisions, final verification.

Cheapest path: never paste code into `context`. Pass `root` (absolute project path) + `context_files`
(the server reads them) and `apply=true` (the server writes files transactionally and returns a short
report). Add `verify` (e.g. "python -m pytest -q tests/test_x.py") so a failing job repairs itself: the
error is fed back and the job escalates up its ladder (e.g. flash-low -> flash-high -> pro); if all fail, its writes are
rolled back. Use `after` to chain jobs (a dependency's files become context), `gate="approve"` for a
human checkpoint. A per-session cost budget is enforced before every call (see `stats`).

Flow: plan + write contracts to a file -> spawn_many -> keep working on the hard parts -> wait_any ->
verify the integration yourself. Load the `deepseek-swarm` skill for the playbook and `build-project`
for a whole project. Workers see ONLY task + context; secrets are never readable by the server.
"""

mcp = FastMCP("subagents", instructions=INSTRUCTIONS)


def make_spec(**fields) -> JobSpec:
    """Build a JobSpec, turning validation errors into messages the model can act on."""
    try:
        return JobSpec(**fields)
    except ValidationError as e:
        raise ToolError("; ".join(err["msg"] for err in e.errors())) from None

store = Store(config.DB_PATH)
store.mark_interrupted()  # jobs left running by a previous process can never finish now
engine = Engine(store, Budget(config.DEFAULT_BUDGET_USD))


@mcp.tool
async def spawn(
    agent: ProfileName,
    task: str,
    context: str = "",
    context_files: list[str] | None = None,
    root: str = "",
    apply: bool = False,
    overwrite: bool = False,
    label: str = "",
    after: list[str] | None = None,
    verify: str = "",
    max_attempts: int = 0,
    gate: str = "auto",
) -> dict:
    """
        Start one DeepSeek worker in the background and return its job_id immediately.
        Profiles: implement (one file/unit from given interfaces), tests, review (bug/security
        first pass), bulk (boilerplate, CRUD, schemas, mock data, repetitive edits), digest
        (summarize/extract long material), write (docs, READMEs, scripts, translations).
        Save tokens: code via context_files + root, apply=true to let the server write files,
        verify="<test command>" for self-repair with model escalation and rollback on failure.
    """
    spec = make_spec(agent=agent, task=task, context=context, context_files=context_files or [], root=root,
                   apply=apply, overwrite=overwrite, label=label, after=after or [], verify=verify,
                   max_attempts=max_attempts, gate=gate)
    return engine.submit(spec).info()


@mcp.tool
async def spawn_many(jobs_spec: list[JobSpec]) -> list[dict]:
    """
        Start a batch of workers with one call (same fields as spawn). Use `label` + `after` to build
        a DAG: dependents wait, and receive their dependencies' written files as context. The whole
        batch is validated (paths, verify commands, cycles) before anything starts.
    """
    return [job.info() for job in engine.submit_many(jobs_spec)]


@mcp.tool
async def get_result(job_id: str, wait_seconds: float = 0, full: bool = False) -> dict:
    """
        Status and result of a job. With wait_seconds > 0, waits at most that long (the job is NOT
        cancelled when the wait expires). Jobs with apply=true report the files written; full=true
        returns the raw model output instead.
    """
    job = engine.get(job_id)
    if wait_seconds > 0:
        await engine.wait_any([job], wait_seconds)
    return job.info(with_result=True, full=full)


@mcp.tool
async def wait_any(job_ids: list[str], wait_seconds: float = 60) -> dict:
    """
        Wait (at most wait_seconds) until AT LEAST ONE of the jobs finishes. Returns the finished
        ones with results and the pending ones: call again with the pending ids.
    """
    jobs = [engine.get(i) for i in job_ids]
    await engine.wait_any(jobs, wait_seconds)
    done = [j for j in jobs if j.task.done()]
    return {
        "finished": [j.info(with_result=True) for j in done],
        "pending": [j.info() for j in jobs if not j.task.done()],
    }


@mcp.tool
async def list_jobs() -> list[dict]:
    """Jobs of this session with profile, status, tier, attempts and duration (no results)."""
    return [j.info() for j in engine.jobs.values()]


@mcp.tool
async def approve(job_id: str) -> dict:
    """Accept a job waiting at its approval gate: its files stay and dependents can start."""
    return engine.approve(job_id).info(with_result=True)


@mcp.tool
async def reject(job_id: str, feedback: str = "", retry: bool = False) -> dict:
    """Reject a job at its approval gate: its writes are rolled back. With retry=true it is resubmitted with the feedback."""
    job, new = engine.reject(job_id, feedback, retry)
    return {"rejected": job.info(), "retry": new.info() if new else None}


@mcp.tool
async def retry(job_id: str, feedback: str = "") -> dict:
    """Resubmit a finished job from its stored spec, optionally with feedback. Works for jobs of previous sessions."""
    return engine.retry(job_id, feedback).info()


@mcp.tool
async def cancel(job_id: str) -> dict:
    """Cancel a queued, waiting or running job (its writes are rolled back)."""
    return (await engine.cancel(job_id)).info()


@mcp.tool
async def trace(job_id: str) -> list[dict]:
    """Full event trace of a job (attempts, tiers, costs, files, verification output). Works across sessions."""
    return store.events(job_id)


@mcp.tool
async def stats() -> dict:
    """Delegated work and its measured cost/quality: this session, all time, and the session budget."""
    return {"session": store.summary(engine.session), "all_time": store.summary(), "budget": engine.budget.status()}


@mcp.tool
async def set_budget(limit_usd: float) -> dict:
    """Change this session's cost ceiling (USD). Attempts that could exceed it are refused before calling a model."""
    engine.budget.limit_usd = limit_usd
    return engine.budget.status()


@mcp.tool
async def dashboard(session_only: bool = False) -> str:
    """Generate the HTML dashboard (KPIs, cost by profile, pass rate by tier, job traces) and return its path."""
    from swarm.dashboard import render

    out = config.DB_PATH.parent / "dashboard.html"
    out.write_text(render(store, engine.session if session_only else None), encoding="utf-8")
    return str(out)


@mcp.tool
async def ask(
    agent: ProfileName,
    task: str,
    context: str = "",
    context_files: list[str] | None = None,
    root: str = "",
    apply: bool = False,
    overwrite: bool = False,
    verify: str = "",
) -> dict:
    """Like spawn but WAITS for the result. Only for a single short job you need right now."""
    spec = make_spec(agent=agent, task=task, context=context, context_files=context_files or [], root=root,
                   apply=apply, overwrite=overwrite, verify=verify)
    job = engine.submit(spec)
    await job.task
    return job.info(with_result=True)


if __name__ == "__main__":
    mcp.run()
