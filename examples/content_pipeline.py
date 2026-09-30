#!/usr/bin/env python3
"""Stage 2-3 of a content engine, driven as a library by the swarm.

Pipeline: strategy.md -> assembly-ready scripts -> packaging.md -> compliance review.
A human approves the strategy (hard gate) before any script is written, and every model call is
charged against a hard cost budget. Media rendering and publishing are out of scope: the output
folder is meant to be handed to a production/render step.

Usage:
    uv run python examples/content_pipeline.py --niche "home espresso" --videos 3 --budget 0.10
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swarm import config
from swarm.budget import Budget
from swarm.engine import Engine, Job, JobSpec
from swarm.store import Store

APPROVE_PROMPT = "Approve? [y = yes / anything else = feedback] "


def strategy_task(niche: str, videos: int) -> str:
    plural = "s" if videos != 1 else ""
    return (
        f"Write the content strategy for a short-form vertical video channel about: {niche}.\n"
        "Output exactly one file: strategy.md\n"
        "The file must contain:\n"
        "- the 3 content pillars of the channel;\n"
        "- the target viewer;\n"
        "- the tone of voice;\n"
        f"- exactly {videos} numbered video topic{plural}, ranked by expected ROI (1 = highest); for each "
        "topic one line of rationale covering demand, competition and RPM potential, each one explicitly "
        "labeled 'Assumption:'.\n"
        "No invented statistics, prices, view counts or sources: only qualitative assumptions.\n"
        "A human reviews this file before the next stage, so it must be complete on its own."
    )


def script_task(index: int, videos: int) -> str:
    return (
        f"This is video {index} of {videos}. Write the shooting script for topic {index} of strategy.md "
        "(in the context). Output exactly one file: "
        f"scripts/0{index}.md\n"
        "It is a 45-60 second vertical 9:16 short for a social channel. Structure it as:\n"
        "- HOOK: what is said and shown in the first 2 seconds;\n"
        "- 4-6 BEATS, each with a voiceover line, the on-screen text, and a B-roll/visual suggestion;\n"
        "- CTA;\n"
        "- Estimated runtime in seconds (must be 45-60).\n"
        "Write speakable lines in short sentences; no directions other than the visuals. No invented facts."
    )


def packaging_task(videos: int) -> str:
    return (
        f"Write packaging.md for the {videos} scripts of this channel. The context holds strategy.md and "
        "the scripts (scripts/*.md). Output exactly one file: packaging.md\n"
        "For every script, one section titled with its file path, containing:\n"
        "- 5 title options;\n"
        "- 3 thumbnail texts;\n"
        "- 3 alternative hooks;\n"
        "- 8 hashtags;\n"
        "- a 2-sentence description;\n"
        "- one line stating whether AI-generated content disclosure is required for this video (yes/no + why).\n"
        "No invented statistics or platform claims."
    )


COMPLIANCE_TASK = (
    "Review the channel content in the context (strategy.md, scripts/*.md, packaging.md). "
    "Do not write files; answer in plain text with exactly three sections:\n"
    "1. CLAIMS NEEDING A SOURCE - the claim quoted, the file it is in, and the source it needs.\n"
    "2. ADVICE NEEDING A DISCLAIMER - the statement and the disclaimer required.\n"
    "3. REUSED/INAUTHENTIC CONTENT AND MISLEADING TITLE RISKS - the risk, the file, and the fix.\n"
    "If a section has no findings, write 'none' after the heading."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan and package short-form video content with a swarm.")
    parser.add_argument("--niche", required=True, help="channel niche, e.g. 'home espresso'")
    parser.add_argument("--videos", type=int, default=3, help="number of video topics/scripts (default 3)")
    parser.add_argument("--budget", type=float, default=0.10, help="hard cost ceiling in USD (default 0.10)")
    parser.add_argument("--out", type=Path, default=Path("examples/out"), help="output folder")
    parser.add_argument("--auto-approve", action="store_true", help="skip the human approval gate")
    args = parser.parse_args(argv)
    if args.videos < 1:
        parser.error("--videos must be >= 1")
    if args.budget <= 0:
        parser.error("--budget must be > 0")
    return args


async def run_strategy(engine: Engine, spec: JobSpec, strategy_md: Path, auto_approve: bool) -> Job:
    """Submit the strategy job and drive the human gate until it is approved (or abort)."""
    job = engine.submit(spec)
    while True:
        await job.task
        if job.status == "done":
            return job
        if job.status != "awaiting_approval":
            print(f"strategy job {job.id} ended as '{job.status}': {job.error or '(no error info)'}",
                  file=sys.stderr)
            raise SystemExit(1)
        if strategy_md.exists():
            lines = strategy_md.read_text(encoding="utf-8").splitlines()
            print("\n" + "\n".join(lines[:40]))
            if len(lines) > 40:
                print(f"... ({len(lines) - 40} more lines in {strategy_md})")
        else:
            print(f"(no {strategy_md} was written)", file=sys.stderr)
        if auto_approve:
            print("--auto-approve: approving strategy.md without asking.")
            engine.approve(job.id)
            return job
        answer = (await asyncio.to_thread(input, APPROVE_PROMPT)).strip()
        if answer.lower() == "y":
            engine.approve(job.id)
            return job
        _, new_job = engine.reject(job.id, answer or "no feedback given", retry=True)
        assert new_job is not None, "reject(retry=True) must return a new job"
        job = new_job


def print_report(rows: list[Job], written: list[str], out_dir: Path, status: dict[str, Any]) -> None:
    print()
    print(f"{'label':<12} {'profile':<9} {'status':<18} {'tier':<12} {'att':>3} {'cost $':>9}")
    print("-" * 68)
    for job in rows:
        print(f"{job.label:<12} {job.spec.agent:<9} {job.status:<18} {job.tier or '-':<12} "
              f"{job.attempts:>3} {job.cost:>9.4f}")
    print("-" * 68)
    print(f"total cost:    ${status['spent_usd']:.4f} of ${status['limit_usd']:.4f} budget "
          f"(${status['remaining_usd']:.4f} remaining, ${status['reserved_usd']:.4f} reserved)")
    print(f"files written: {len(written)}")
    for path in written:
        print(f"  {path}")
    print(f"output folder: {out_dir}")
    for job in rows:
        if job.status != "done":
            print(f"  ! {job.label}: {job.status}: {job.error or ''}", file=sys.stderr)


async def main(args: argparse.Namespace) -> int:
    out_dir = args.out.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    strategy_md = out_dir / "strategy.md"

    store = Store(config.DB_PATH)
    engine = Engine(store, Budget(args.budget))
    print(f"niche: {args.niche!r} | videos: {args.videos} | budget: ${args.budget:.2f} | out: {out_dir}")

    strategy = await run_strategy(
        engine,
        JobSpec(
            agent="write",
            task=strategy_task(args.niche, args.videos),
            root=str(out_dir),
            apply=True,
            overwrite=True,
            gate="approve",
            label="strategy",
        ),
        strategy_md,
        args.auto_approve,
    )
    print(f"strategy approved ({strategy.id}).")

    script_labels = [f"script-{i}" for i in range(1, args.videos + 1)]
    specs: list[JobSpec] = [
        JobSpec(
            agent="write",
            task=script_task(i, args.videos),
            after=[strategy.id],
            root=str(out_dir),
            apply=True,
            overwrite=True,
            label=f"script-{i}",
        )
        for i in range(1, args.videos + 1)
    ]
    specs.append(JobSpec(
        agent="bulk",
        task=packaging_task(args.videos),
        after=script_labels,  # the scripts arrive as dependency context; the strategy is added explicitly
        context_files=["strategy.md"],
        root=str(out_dir),
        apply=True,
        overwrite=True,
        label="packaging",
    ))
    specs.append(JobSpec(
        agent="review",
        task=COMPLIANCE_TASK,
        after=["packaging"],
        root=str(out_dir),
        context_files=["strategy.md", "scripts/*.md", "packaging.md"],
        label="compliance",
    ))

    batch = engine.submit_many(specs)
    await asyncio.gather(*(job.settled.wait() for job in batch))

    rows = [strategy, *batch]
    compliance = next(job for job in batch if job.label == "compliance")
    written = sorted({path for job in rows for path in job.files})
    if compliance.status == "done" and compliance.result:
        (out_dir / "review.md").write_text(compliance.result, encoding="utf-8")
        written = sorted({*written, "review.md"})
    elif compliance.status != "done":
        print(f"compliance job {compliance.id} ended as '{compliance.status}': "
              f"{compliance.error or '(no error info)'} - review.md not written", file=sys.stderr)

    print_report(rows, written, out_dir, engine.budget.status())
    return 0 if all(job.status == "done" for job in rows) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
