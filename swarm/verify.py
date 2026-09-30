"""Run a job's verification command (tests, typecheck, lint) inside the project root."""
import asyncio
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from swarm.config import VERIFY_ALLOWLIST

SHELL_METACHARS = set(";&|<>`$\n")
OUTPUT_TAIL = 6_000


@dataclass
class CheckResult:
    ok: bool
    code: int | None
    output: str  # tail of combined stdout/stderr


def parse_command(cmd: str) -> list[str]:
    """Split a command and check it against the allowlist. No shell is ever involved."""
    if not cmd.strip():
        raise ValueError("empty verify command")
    if SHELL_METACHARS & set(cmd):
        raise ValueError("verify command must be a single program invocation (no ; & | < > ` $)")
    args = [a.strip('"') for a in shlex.split(cmd, posix=os.name != "nt")]
    exe = Path(args[0]).name.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        exe = exe.removesuffix(suffix)
    if exe not in VERIFY_ALLOWLIST:
        raise ValueError(f"'{args[0]}' is not an allowed verify program. Allowed: {sorted(VERIFY_ALLOWLIST)}")
    resolved = shutil.which(args[0])
    if not resolved and exe in {"python", "python3", "py"}:
        resolved = sys.executable  # the interpreter running the server
    if not resolved:
        raise ValueError(f"'{args[0]}' not found on PATH")
    return [resolved, *args[1:]]


async def run_check(root: Path, cmd: str, timeout: float) -> CheckResult:
    args = parse_command(cmd)
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=root, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return CheckResult(False, None, f"verify timed out after {timeout}s")
    text = out.decode("utf-8", errors="replace")
    return CheckResult(proc.returncode == 0, proc.returncode, text[-OUTPUT_TAIL:])
