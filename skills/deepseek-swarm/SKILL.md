---
name: deepseek-swarm
description: Playbook for delegating bounded, well-specified, token-heavy work to cheap parallel DeepSeek V4.1 Flash workers via the `subagents` MCP (spawn / spawn_many / wait_any / get_result / ask / stats). Use proactively on any large or multi-part task - implementing several files or functions from a clear spec, writing tests, boilerplate/CRUD/schemas/mock data, repetitive edits across files, first-pass code review, summarizing or extracting from long logs/docs/code, READMEs/docs/translations. Also when the user says "delega", "usa i subagenti", "swarm", "risparmia token", "in parallelo". Keep architecture, debugging, decisions and final verification local.
---

# DeepSeek Swarm

You are the architect and the verifier. DeepSeek V4.1 Flash workers are fast (~200 tok/s), about 20x cheaper per task than you, have a 1M token context and run 8 at a time in parallel. They do NOT see the repo, the terminal or this conversation: only `task` + `context` (+ the files the server reads for them).

## Where they are strong, and where they are not

Benchmarks and user reports agree: strong on isolated, well-specified code (HumanEval ~79, DeepSWE ~74), bulk text, long-context reading, security review (Cyber Gym 88). Weak on logical consistency across many steps, state tracking, multi-file debugging, novel problems, terminal/agentic work and visual/SVG. Typical failure: **plausible code or tests that are subtly wrong**. So: delegate the typing, keep the thinking, always verify by running things.

| Agent | Use it for | Effort |
|---|---|---|
| `implement` | one file/function/component with interfaces already defined | high |
| `tests` | tests for existing code + spec | high |
| `review` | first-pass bug/security hunt (findings need your check) | max |
| `bulk` | boilerplate, CRUD, schemas, types, fixtures, seed/mock data, conversions, same edit on many files | low |
| `digest` | summarize/extract from long material (logs, docs, big files, whole folders) | off |
| `write` | README, docs, docstrings, UI copy, translations | off |

**Never delegate:** architecture and contracts, ambiguous requirements, debugging, anything needing to run code, fact "research" (no web: it hallucinates), destructive actions, tiny edits you would finish faster yourself. Secrets never go in `context` (the server already refuses to read or write `.env`, keys, credentials).

## Decision rule

Delegate when ALL are true:
1. The unit is bounded and verifiable without redoing it (run it, test it, skim it).
2. Everything it needs is in files you can point to plus a short spec.
3. The output is long (code, tests, docs, data) or there are several independent units.

## The cheap way to call it (this is where the savings come from)

Your output tokens are the expensive ones. Never paste code into `context` and never re-type worker output with Write.

- `root`: absolute path of the project (the current working directory).
- `context_files`: paths or globs relative to root (`src/models/*.ts`, `SPEC.md`). The server reads them.
- `context`: only the short part that is not in files: the exact contract to respect, conventions, the pattern to follow.
- `apply=true`: the server writes the produced files under root and returns only `{path, status, lines}`. Add `overwrite=true` when the job is meant to modify existing files.
- `label`: short name to recognize the job.

```
spawn_many(jobs_spec=[
  {agent:"implement", label:"users api", root:"C:/proj", apply:true,
   task:"Implement src/api/users.ts exporting listUsers and createUser as specified in SPEC.md §API",
   context_files:["SPEC.md","src/types.ts","src/db.ts"]},
  {agent:"tests", label:"users tests", root:"C:/proj", apply:true,
   task:"Write tests/users.test.ts (vitest) for src/api/users.ts",
   context_files:["SPEC.md","src/types.ts"]},
])
```

Rules for good jobs: one file (or one tight group) per job; contracts in a file (e.g. `SPEC.md`, `types.ts`) that every job reads, so parallel workers stay consistent; the task names output paths explicitly. If a job fails with "worker reported missing context", add what's missing and `retry` it with feedback.

### Let the server verify and repair (use it whenever a check exists)

- `verify`: a single command run in `root` after the files are written, e.g.
  `"python -m pytest -q tests/test_users.py"`, `"npx tsc --noEmit"`, `"ruff check src/users.py"`. Keep it scoped
  to the job's own files: checks run one at a time per project. On failure the output is fed back and the job
  escalates up its ladder (implement: flash-low → flash-high → pro-high, set from eval data). If every tier fails, **all its writes
  are rolled back**, so a failed job never leaves broken files behind. No shell: one allowlisted program.
- `after: ["label", ...]`: build a DAG in one `spawn_many`. A dependent waits, then gets its dependencies'
  written files as context automatically. A failed dependency makes dependents `blocked`.
- `gate: "approve"`: the job stops at `awaiting_approval` after passing. `approve(id)` keeps the files,
  `reject(id, feedback, retry=true)` rolls back and resubmits. Use it where a human must sign off.
- Budget: every attempt reserves its worst-case cost before calling a model and is refused (`over_budget`) if it
  doesn't fit. `stats` shows the session budget; `set_budget` changes it only if the user asks.
- `trace(id)` shows every attempt (tier, tokens, cost, verify output); `retry(id, feedback)` resubmits any
  finished job, also from previous sessions; `dashboard` writes an HTML report.

Worker-written tests can be wrong too: if a job keeps failing on a test, read the test before blaming the code.

## Workflow

1. **Plan locally.** Split into independent units; write the shared contracts to a file first.
2. **Fan out.** One `spawn_many` with every independent job. Jobs that depend on others' output go in a later wave.
3. **Keep working.** While they run, do what you kept: core logic, integration, config.
4. **Collect.** `wait_any(ids, wait_seconds=60)`, handle the finished ones, call again with the `pending` ids. Never poll in a tight loop. `get_result(id, full=true)` shows the raw output if needed.
5. **Verify the integration.** Jobs with `verify` already checked themselves; you still run the whole
   typecheck/test/build once per wave and read diffs of critical files (`git diff`), not everything.
6. **Fix.** Small issues: fix yourself. A failed job: read `trace`, then `retry` with feedback once, or do it yourself.

`ask` = synchronous, only for one short job you need right now. `list_jobs`, `cancel` as needed. `stats` shows jobs, success rate, escalations, cost and the budget.

## Report

At the end, tell the user in one or two lines what was delegated (jobs per agent, files written, DeepSeek cost from `stats`) and what you had to fix.
