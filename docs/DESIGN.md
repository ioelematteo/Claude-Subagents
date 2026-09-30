# Design: swarm engine v2

Python 3.13, stdlib + `fastmcp`, `openai`, `pydantic`. Package `swarm/`, MCP entrypoint `server.py`.
Style: type hints everywhere, small functions, English docstrings, no external deps beyond the above.

## Module map

| Module | Responsibility |
|---|---|
| `swarm/config.py` | Tiers (model + thinking + effort + prices), profiles (system prompt + escalation ladder), limits |
| `swarm/workspace.py` | Read context files, parse `=== FILE:` blocks, transactional writes with rollback, sandboxed to root |
| `swarm/store.py` | Durable SQLite store: jobs + event trace |
| `swarm/budget.py` | Cost ceiling with pre-flight reservation |
| `swarm/verify.py` | Run an allowlisted check command in the project root |
| `swarm/engine.py` | Job DAG, concurrency, escalation ladder, verify-and-repair loop, approval gates |
| `swarm/dashboard.py` | Static HTML dashboard generated from the store |
| `server.py` | Thin MCP layer over the engine |
| `evals/` | Offline eval harness: pass rate x cost x latency per tier |

## Job lifecycle

```
queued ─▶ waiting (deps) ─▶ running ─▶ verifying ─┬─▶ done
   │            │               │  ▲        │      └─▶ awaiting_approval ─▶ done | rejected
   │            └─▶ blocked     │  └── fail: escalate to next tier, feed back the error
   └─▶ over_budget              └─▶ failed (ladder exhausted → rollback)      cancelled, interrupted
```

Terminal statuses: `done`, `failed`, `blocked`, `rejected`, `cancelled`, `interrupted`, `over_budget`.
`interrupted` = the process died while the job was not terminal (set at next startup).

## Contract: `swarm/store.py`

SQLite via stdlib `sqlite3`, one connection opened with `check_same_thread=False`, WAL journal mode when
the path is a file, `row_factory = sqlite3.Row`. The path may be `":memory:"`. Parent dir is created.
All methods are synchronous (called from the event loop; writes are tiny).

```python
JOB_COLUMNS = [
    "id", "session", "label", "profile", "status", "tier", "attempts",
    "tokens_in", "tokens_out", "cost_usd", "created", "started", "finished",
    "root", "verify", "files", "error", "spec",
]
# types: id/session/label/profile/status/tier/root/verify/error TEXT; attempts/tokens_in/tokens_out INTEGER;
# cost_usd/created/started/finished REAL; files TEXT (JSON list of relative paths); spec TEXT (JSON object).
# Table `jobs` (id PRIMARY KEY), table `events` (id INTEGER PK AUTOINCREMENT, job_id TEXT, ts REAL,
# kind TEXT, data TEXT JSON). Index on events(job_id) and jobs(session).

TERMINAL = {"done", "failed", "blocked", "rejected", "cancelled", "interrupted", "over_budget"}

class Store:
    def __init__(self, path: str | Path) -> None: ...
    def upsert_job(self, row: dict) -> None:
        """Insert or replace a job. `row` may contain any subset of JOB_COLUMNS plus `id` (required);
        missing columns keep their previous value on update (use INSERT ... ON CONFLICT(id) DO UPDATE
        only for the provided columns). `files` (list) and `spec` (dict) are JSON-encoded here."""
    def get_job(self, job_id: str) -> dict | None:
        """Row as dict with `files` decoded to list and `spec` decoded to dict (None stays None)."""
    def list_jobs(self, session: str | None = None, limit: int = 500) -> list[dict]:
        """Newest first (by created). Same decoding as get_job."""
    def add_event(self, job_id: str, kind: str, data: dict | None = None) -> None:
        """ts = time.time(). data stored as JSON ('{}' when None)."""
    def events(self, job_id: str) -> list[dict]:
        """Oldest first: [{"ts": float, "kind": str, "data": dict}]."""
    def attempts(self, session: str | None = None) -> list[dict]:
        """All events with kind == "attempt" (optionally only for jobs of `session`), oldest first, each as
        {"job_id", "ts", **data}. data keys: tier, model, tokens_in, tokens_out, cost_usd, seconds, outcome."""
    def summary(self, session: str | None = None) -> dict:
        """Aggregates over jobs (optionally of one session):
        {
          "jobs": int, "by_status": {status: count},
          "succeeded": int,                    # status == "done"
          "first_try": int,                    # done with attempts == 1
          "escalated": int,                    # done with attempts > 1
          "success_rate": float,               # succeeded / terminal jobs, 0.0 if none
          "tokens_in": int, "tokens_out": int, "cost_usd": float (rounded 5),
          "cost_per_success": float | None,    # cost_usd / succeeded
          "avg_seconds": float | None,         # mean(finished - started) over done jobs
          "files_written": int,                # total len(files) over done jobs
          "by_profile": {profile: {"jobs", "succeeded", "cost_usd"}},
          "by_tier": {tier: {"calls", "passed", "cost_usd"}}   # from attempts(); passed = outcome == "ok"
        }"""
    def mark_interrupted(self) -> int:
        """Set status 'interrupted' and finished=now on every non-terminal job; add an event
        kind 'interrupted' for each; return how many."""
    def close(self) -> None: ...
```

## Contract: `swarm/dashboard.py`

`python -m swarm.dashboard [--db PATH] [--out PATH] [--session ID]` → writes one self-contained HTML file
(default `data/dashboard.html`) and prints its path. Uses only `Store` (above) + stdlib (`html`, `json`,
`argparse`). Charts: Chart.js 4 from `https://cdn.jsdelivr.net/npm/chart.js@4` (one script tag); all data is
embedded as a JSON literal. Expose `def render(store: Store, session: str | None = None) -> str` and `main()`.

Content, top to bottom:
1. Header "Swarm dashboard" + generated-at timestamp + scope (all time or session id).
2. KPI cards: jobs, success rate %, first-try %, escalated, total cost $, cost per success $, avg seconds, files written.
3. Charts: cost by profile (bar), attempts by tier stacked passed/failed (bar), jobs by status (doughnut).
4. Table of the 50 most recent jobs: id, label, profile, status (colored pill), tier, attempts, cost, seconds, created.
   Each row expands (`<details>`) to its event trace from `store.events(id)`: time offset, kind, compact data.
Styling: inline CSS, system font, light and dark via `prefers-color-scheme`, responsive grid, no other deps.
All text inserted into HTML must be escaped.

## Contract: eval tasks (`evals/tasks/<name>/`)

Each task is a small, self-contained Python problem with hidden tests the worker never sees.
```
evals/tasks/<name>/task.json     {"profile": "implement", "task": "...imperative, names the output file...",
                                   "context": "...spec: signature, behavior, edge cases, errors...",
                                   "output": "solution.py"}
evals/tasks/<name>/reference.py  a correct reference implementation (module name = output file)
evals/tasks/<name>/test_hidden.py  pytest tests importing from the output module (e.g. `from solution import f`)
```
The spec in `context` must fully determine the behavior the hidden tests check (no surprises).
Hidden tests: 8-15 focused tests, deterministic, no network, no sleeping (inject clocks as parameters).
