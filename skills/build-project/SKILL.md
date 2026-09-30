---
name: build-project
description: Build an entire working project from an idea, end to end, with Opus as architect/integrator and parallel DeepSeek workers (deepseek-swarm skill) writing the bulk of the files. Use when the user says "/build-project", "costruiscimi un progetto", "fammi un'app completa", "genera il progetto intero", or pastes a project brief. Also use with the argument "prompt" to turn a vague idea into a complete, ready-to-run project brief.
---

# Build Project

Goal: from an idea to a project that **installs, runs and passes its tests**, not a pile of plausible files. You own design, contracts, integration and verification; DeepSeek workers own the typing (see the `deepseek-swarm` skill and follow it for every delegation).

## Mode A - "prompt": generate the brief

If invoked with `prompt` (or the user only has a vague idea), produce a brief and stop. Ask at most 3 questions, only for what changes the architecture (e.g. web vs mobile, needs login, needs persistence). Default everything else sensibly. Output this brief, filled in, as a single block the user can paste back:

```
# PROJECT BRIEF
Name:
One-liner: (what it is and for whom, one sentence)
Core features (MVP, max 6, each testable):
Out of scope:
Stack: (language, framework, DB, styling, test framework; prefer boring, popular, well-documented)
Data model: (entities and fields)
Screens / endpoints / commands:
Quality bar: (tests required, lint, typecheck, responsive, accessibility)
Run: (the exact command the user will run to see it working)
Done when: (concrete acceptance checks)
```

## Mode B - build

### Phase 0: brief
If there is no complete brief, run Mode A first and get a quick OK. Pick the stack yourself if the user doesn't care.

### Phase 1: architecture (local, no delegation)
Write `SPEC.md` in the project root with:
- file tree with one line per file describing its responsibility
- **contracts**: every shared type, interface, function signature, API route (method, path, request, response), DB schema, env var names, written as real code
- conventions: naming, error handling, folder structure, styling system
- build order in waves (see Phase 3)

Contracts are what make parallel work consistent. Be precise here: this is the most valuable thing you write.

### Phase 2: skeleton (local)
Scaffold with the official generator when one exists (e.g. `npm create vite@latest`, `uv init`), install dependencies, create config files, shared types and contract files. Make it build/run empty. Commit if it's a git repo.

### Phase 3: waves of parallel workers
Group files into waves by dependency: wave 1 = files depending only on contracts (models, utils, API clients, UI primitives), wave 2 = files using wave 1 (services, pages, routes), wave 3 = tests, seed data, docs.

Prefer one `spawn_many` for all waves, expressing the order with `label` + `after` (the server schedules the DAG and passes each dependency's files as context). Give every job that has a meaningful check a scoped `verify` command so it repairs itself or rolls back. For each wave: one job per file, all with `root` = project path and `apply=true`. Each job gets `context_files` = `SPEC.md` + the contract files + the files it imports (already verified), and a short `context` naming the exact section of SPEC.md it implements. Never paste code: the server reads and writes files. Typical mapping: feature files -> `implement`, CRUD/schemas/fixtures/seed -> `bulk`, test files -> `tests`, README -> `write`.

While a wave runs, write the hard parts yourself: the core algorithm, state management, auth, integration glue, anything with tricky logic.

### Phase 4: integrate and verify (local, non-negotiable)
After every wave: run typecheck, lint, tests and build (the files are already on disk). Read failures, fix small things yourself, respawn a job at most once with the error in context and `overwrite=true`, otherwise rewrite it yourself. Remember worker-written tests can be wrong too. Do not start the next wave on a red build.

At the end: start the app and actually exercise it (run the CLI, hit the endpoints, open the page in the browser pane and click through the main flow). A project is done only when the "Done when" checks in the brief pass.

### Phase 5: polish and hand-off
- `review` jobs on the most critical files, then verify findings yourself
- `write` job for the README (setup, run, test, structure), then check the commands in it really work
- Tell the user: what was built, how to run it, what was delegated vs written by you (use `stats`), known limits and suggested next steps.

## Rules
- Honesty over demo effect: never claim something works without having run it.
- Keep the MVP small and complete rather than big and broken. Suggest extra features as next steps.
- Ask the user only for things that are genuinely theirs to decide (product choices, paid services, API keys: they add those to `.env` themselves).
