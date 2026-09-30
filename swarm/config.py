"""Models, worker profiles and limits. Everything tunable lives here (env overrides where it matters)."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("SWARM_DB", ROOT_DIR / "data" / "swarm.db"))

MAX_CONCURRENT = int(os.getenv("SWARM_MAX_CONCURRENT", "8"))
ATTEMPT_TIMEOUT = float(os.getenv("SWARM_ATTEMPT_TIMEOUT", "300"))
DEFAULT_BUDGET_USD = float(os.getenv("SWARM_BUDGET_USD", "1.00"))
VERIFY_TIMEOUT = float(os.getenv("SWARM_VERIFY_TIMEOUT", "180"))


@dataclass(frozen=True)
class Tier:
    """A concrete way to call a model. Profiles escalate through tiers."""
    name: str
    model: str
    thinking: bool
    effort: str | None
    price_in: float    # USD per million input tokens
    price_out: float   # USD per million output tokens (reasoning tokens are billed as output)
    reserve_out: int   # output tokens reserved against the budget before the call starts

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.price_in + tokens_out * self.price_out) / 1_000_000


FLASH_IN = float(os.getenv("PRICE_FLASH_IN", "0.30"))
FLASH_OUT = float(os.getenv("PRICE_FLASH_OUT", "1.20"))
PRO_IN = float(os.getenv("PRICE_PRO_IN", "1.32"))
PRO_OUT = float(os.getenv("PRICE_PRO_OUT", "3.96"))

TIERS: dict[str, Tier] = {t.name: t for t in [
    Tier("flash-fast", "deepseek-flash", False, None, FLASH_IN, FLASH_OUT, 4_000),
    Tier("flash-low", "deepseek-flash", True, "low", FLASH_IN, FLASH_OUT, 8_000),
    Tier("flash-high", "deepseek-flash", True, "high", FLASH_IN, FLASH_OUT, 16_000),
    Tier("flash-max", "deepseek-flash", True, "max", FLASH_IN, FLASH_OUT, 32_000),
    Tier("pro-high", "deepseek-v4-pro", True, "high", PRO_IN, PRO_OUT, 16_000),
]}

RULES = (
    " You receive a TASK and a CONTEXT. The CONTEXT is all you know: never invent APIs, files, "
    "names or facts that are not in it. If something essential is missing, say so in one line "
    "starting with 'MISSING:' instead of guessing. Be concise: no preamble, no closing remarks."
)

FILE_FORMAT = (
    " When you output files, always output the COMPLETE file content, using exactly this format for each one, "
    "with nothing between files:\n=== FILE: relative/path.ext ===\n```lang\n<full file content>\n```"
)


@dataclass(frozen=True)
class Profile:
    """A narrowly scoped worker: what it is for, how it is prompted, and how it escalates."""
    name: str
    system: str
    ladder: tuple[str, ...]  # tier names, cheapest first; the next one is used only after a failure


PROFILES: dict[str, Profile] = {p.name: p for p in [
    Profile(
        "implement",
        "You are a senior software engineer. Implement exactly the specified unit (function, module, "
        "component, endpoint) respecting the given interfaces, names and signatures. Complete code, "
        "no placeholders, no TODOs, handle edge cases." + RULES + FILE_FORMAT,
        # evals/RESULTS.md: flash-low had the best pass@1 at the lowest cost; flash-max bought nothing over
        # flash-high, so escalation skips it and goes straight to the stronger model.
        ("flash-low", "flash-high", "pro-high"),
    ),
    Profile(
        "tests",
        "You are a test engineer. Write thorough automated tests for the given code and spec: happy path, "
        "edge cases, error cases. Use the framework specified in the context. Tests must be runnable "
        "as-is and must only assert behavior the spec or code actually defines." + RULES + FILE_FORMAT,
        ("flash-high", "pro-high"),
    ),
    Profile(
        "review",
        "You are a meticulous code reviewer. Find real defects in the given code: bugs, unhandled edge "
        "cases, security issues, spec violations. For each: location, problem, concrete failing "
        "scenario, fix. No style nitpicks. If you find nothing solid, say 'NO ISSUES'." + RULES,
        ("flash-max", "pro-high"),
    ),
    Profile(
        "bulk",
        "You perform mechanical, repetitive transformations and generation: boilerplate, CRUD, schemas, "
        "types, fixtures, mock/seed data, format conversions, applying the same change to many "
        "files. Follow the given pattern exactly and be consistent." + RULES + FILE_FORMAT,
        ("flash-low", "flash-high"),
    ),
    Profile(
        "digest",
        "You read long material (code, logs, docs, transcripts) and summarize or extract exactly what "
        "is asked. Stay faithful: keep names, numbers, paths and line references; add nothing." + RULES,
        ("flash-fast", "flash-low"),
    ),
    Profile(
        "write",
        "You write clear prose: READMEs, docs, docstrings, UI copy, scripts, emails, translations. Match the "
        "requested tone, language and length. If asked to produce a file, use the file format." + RULES + FILE_FORMAT,
        ("flash-fast", "flash-high"),
    ),
]}

# Executables a job's `verify` command may start. The allowlist stops the orchestrator's tool call from
# being an arbitrary shell; it is NOT a sandbox: verifying means executing worker-written code.
VERIFY_ALLOWLIST = {
    "python", "python3", "py", "pytest", "uv", "ruff", "mypy", "pyright",
    "node", "npm", "npx", "pnpm", "yarn", "bun", "deno", "tsc", "eslint", "jest", "vitest",
    "cargo", "go", "dotnet", "mvn", "gradle",
}
