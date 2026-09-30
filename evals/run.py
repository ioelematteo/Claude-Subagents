"""Offline eval: output quality x cost x latency per model tier, measured with hidden tests.

Every task in evals/tasks/ is solved by each tier in a fresh folder, with one attempt and no feedback
(pass@1). The worker never sees the hidden tests; they are copied in only afterwards and executed.
With --ladder, each task is also run through the profile's full escalation ladder with the hidden
tests as the `verify` command, to measure what self-repair with test feedback buys and what it costs.

    uv run python evals/run.py                     # all tiers, all tasks
    uv run python evals/run.py --tiers flash-high,pro-high --ladder
"""
import argparse
import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swarm import config
from swarm.budget import Budget
from swarm.engine import Engine, Job, JobSpec
from swarm.store import Store
from swarm.verify import run_check

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE / "tasks"
RUNS_DIR = HERE / ".runs"
PYTEST = "python -m pytest -q -p no:cacheprovider test_hidden.py"


def load_tasks(names: list[str] | None) -> list[dict]:
    tasks = []
    for d in sorted(p for p in TASKS_DIR.iterdir() if p.is_dir()):
        if names and d.name not in names:
            continue
        spec = json.loads((d / "task.json").read_text(encoding="utf-8"))
        tasks.append({"name": d.name, "dir": d, **spec})
    return tasks


def task_test_count(task: dict) -> int:
    """Number of hidden tests, from the files themselves (a run that produced nothing still fails all of them)."""
    return len(re.findall(r"^\s*(?:async\s+)?def test_", (task["dir"] / "test_hidden.py").read_text(encoding="utf-8"),
                          re.MULTILINE))


def count_tests(output: str) -> tuple[int, int]:
    passed = sum(int(n) for n in re.findall(r"(\d+) passed", output))
    failed = sum(int(n) for n in re.findall(r"(\d+) (?:failed|error)", output))
    return passed, passed + failed


async def score(job: Job, task: dict, workdir: Path) -> dict:
    await job.settled.wait()
    shutil.copy(task["dir"] / "test_hidden.py", workdir / "test_hidden.py")
    passed, total = 0, task_test_count(task)
    ok = False
    if job.status == "done":
        result = await run_check(workdir, PYTEST, config.VERIFY_TIMEOUT)
        passed, ran = count_tests(result.output)
        total = max(total, ran)  # parametrized tests expand beyond the number of test functions
        ok = result.ok
    return {
        "task": task["name"], "status": job.status, "pass": ok, "tests_passed": passed, "tests_total": total,
        "attempts": job.attempts, "final_tier": job.tier, "cost_usd": round(job.cost, 6),
        "seconds": round((job.finished or time.time()) - (job.started or job.created), 2),
    }


def submit(engine: Engine, task: dict, workdir: Path, tiers: list[str] | None, verify: str = "") -> Job:
    workdir.mkdir(parents=True)
    if verify:  # ladder mode: hidden tests are the verification, present on disk but never in the prompt
        shutil.copy(task["dir"] / "test_hidden.py", workdir / "test_hidden.py")
    return engine.submit(JobSpec(
        agent=task["profile"], task=task["task"], context=task["context"], root=str(workdir),
        apply=True, overwrite=True, tiers=tiers, max_attempts=1 if tiers else 0, verify=verify,
        label=f"{task['name']}@{tiers[0] if tiers else 'ladder'}",
    ))


def aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    passes = [r for r in rows if r["pass"]]
    cost = sum(r["cost_usd"] for r in rows)
    tests_passed = sum(r["tests_passed"] for r in rows)
    tests_total = sum(r["tests_total"] for r in rows) or 1
    return {
        "runs": n, "pass": len(passes), "escalated": sum(r["attempts"] > 1 for r in rows), "pass_rate": round(len(passes) / n, 3) if n else 0.0,
        "test_pass_rate": round(tests_passed / tests_total, 3),
        "avg_cost_usd": round(cost / n, 5) if n else 0.0,
        "cost_per_pass_usd": round(cost / len(passes), 5) if passes else None,
        "avg_seconds": round(sum(r["seconds"] for r in rows) / n, 1) if n else 0.0,
        "avg_attempts": round(sum(r["attempts"] for r in rows) / n, 2) if n else 0.0,
    }


def markdown(results: dict) -> str:
    lines = [
        "# Eval results", "",
        (f"{results['tasks']} tasks with hidden tests x {results['repeat']} repetitions, run {results['date']}. "
         "Tier rows = pass@1 (one attempt, no feedback). Ladder = the profile's escalation ladder with the hidden "
         "tests as `verify`, so a failing attempt gets the test output and escalates to the next tier."), "",
        "| Config | Pass | Hidden tests passed | Avg cost / run | Cost / passing run | Avg latency | Escalated |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, agg in results["summary"].items():
        cpp = f"${agg['cost_per_pass_usd']:.4f}" if agg["cost_per_pass_usd"] is not None else "n/a"
        lines.append(f"| {name} | {agg['pass']}/{agg['runs']} ({agg['pass_rate']:.0%}) | {agg['test_pass_rate']:.1%} | "
                     f"${agg['avg_cost_usd']:.4f} | {cpp} | {agg['avg_seconds']}s | {agg['escalated']} |")
    configs = list(results["summary"])
    lines += ["", "| Task | " + " | ".join(configs) + " |", "|---|" + "---|" * len(configs)]
    for task in sorted({r["task"] for r in results["rows"]}):
        cells = []
        for c in configs:
            runs = [r for r in results["rows"] if r["config"] == c and r["task"] == task]
            ok = sum(r["pass"] for r in runs)
            cells.append(("✅" if ok == len(runs) else "⚠️" if ok else "❌") + f" {ok}/{len(runs)}")
        lines.append(f"| {task} | " + " | ".join(cells) + " |")
    lines += ["", f"Total eval cost: ${results['total_cost_usd']:.4f}", ""]
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tiers", default="flash-fast,flash-low,flash-high,flash-max,pro-high")
    parser.add_argument("--tasks", default="", help="comma-separated task names (default: all)")
    parser.add_argument("--ladder", action="store_true", help="also run each task through the escalation ladder")
    parser.add_argument("--repeat", type=int, default=1, help="repetitions per task and config")
    parser.add_argument("--tag", default="", help="write RESULTS-<tag>.md / results/<tag>.json instead of latest")
    parser.add_argument("--budget", type=float, default=2.0)
    args = parser.parse_args()

    tiers = [t for t in args.tiers.split(",") if t]
    tasks = load_tasks([t for t in args.tasks.split(",") if t] or None)
    run_dir = RUNS_DIR / time.strftime("%Y%m%d-%H%M%S")
    engine = Engine(Store(":memory:"), Budget(args.budget))

    pending: list[tuple[str, asyncio.Task]] = []
    for rep in range(args.repeat):
        for task in tasks:
            for tier in tiers:
                workdir = run_dir / f"r{rep}" / tier / task["name"]
                job = submit(engine, task, workdir, [tier])
                pending.append((tier, asyncio.create_task(score(job, task, workdir))))
            if args.ladder:
                workdir = run_dir / f"r{rep}" / "ladder" / task["name"]
                job = submit(engine, task, workdir, None, verify=PYTEST)
                pending.append(("ladder", asyncio.create_task(score(job, task, workdir))))

    print(f"running {len(pending)} jobs ({len(tasks)} tasks x {len(tiers) + args.ladder} configs "
          f"x {args.repeat} repetitions)...")
    rows = []
    for config_name, t in pending:
        row = {"config": config_name, **await t}
        rows.append(row)
        mark = "PASS" if row["pass"] else "fail"
        print(f"  {config_name:<11} {row['task']:<16} {mark}  {row['tests_passed']}/{row['tests_total']}  "
              f"${row['cost_usd']:.4f}  {row['seconds']}s  x{row['attempts']}")

    order = tiers + (["ladder"] if args.ladder else [])
    results = {
        "date": time.strftime("%Y-%m-%d"), "tasks": len(tasks), "repeat": args.repeat, "rows": rows,
        "summary": {c: aggregate([r for r in rows if r["config"] == c]) for c in order},
        "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 5),
    }
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    suffix = f"-{args.tag}" if args.tag else ""
    (out / f"{args.tag or 'latest'}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (HERE / f"RESULTS{suffix}.md").write_text(markdown(results), encoding="utf-8")
    print(markdown(results))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
