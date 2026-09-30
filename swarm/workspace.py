"""Reading context from disk and writing files produced by subagents.

Everything stays confined inside `root` (the project folder) and files that
look like secrets are never read or written: the content read is sent
to an external API.
"""
import fnmatch
import re
from pathlib import Path

MAX_CONTEXT_BYTES = 1_500_000  # ~400k tokens: wide margin below DeepSeek's million

SECRET_PATTERNS = [
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "id_rsa*", "id_ed25519*",
    "credentials*", "*secret*", ".npmrc", ".pypirc", ".netrc", "*.kdbx",
]
SECRET_ALLOWED = [".env.example", ".env.sample", ".env.template"]
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target"}

FILE_HEADER = re.compile(r"^=== FILE: (.+?) ===[ \t]*$", re.MULTILINE)


def is_secret(path: Path) -> bool:
    name = path.name.lower()
    if name in SECRET_ALLOWED:
        return False
    return any(fnmatch.fnmatch(name, p) for p in SECRET_PATTERNS)


def get_root(root: str) -> Path:
    if not root:
        raise ValueError("'root' is required: the absolute path of the project folder")
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"root is not a folder: {root}")
    return path


def inside(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path outside the project: {path}")
    return resolved


def expand(root: Path, patterns: list[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        p = Path(pattern)
        rel = p.relative_to(root) if p.is_absolute() and p.resolve().is_relative_to(root) else p
        if any(ch in str(rel) for ch in "*?["):
            matches = sorted(m for m in root.glob(str(rel).replace("\\", "/")) if m.is_file())
        else:
            matches = [root / rel]
        for m in matches:
            if any(part in SKIP_DIRS for part in m.relative_to(root).parts[:-1]):
                continue
            m = inside(root, m)
            if m not in found:
                found.append(m)
    return found


def read_context(root: Path, patterns: list[str]) -> tuple[str, list[str], list[str]]:
    """Return (text blocks, included files, skipped files with reason)."""
    blocks, included, skipped = [], [], []
    total = 0
    for path in expand(root, patterns):
        rel = path.relative_to(root).as_posix()
        if is_secret(path):
            skipped.append(f"{rel} (secret)")
            continue
        if not path.is_file():
            raise ValueError(f"file not found: {rel}")
        data = path.read_bytes()
        if b"\x00" in data[:4096]:
            skipped.append(f"{rel} (binary)")
            continue
        total += len(data)
        if total > MAX_CONTEXT_BYTES:
            raise ValueError(f"context too large (> {MAX_CONTEXT_BYTES // 1000} KB): split the job")
        text = data.decode("utf-8", errors="replace")
        blocks.append(f"=== FILE: {rel} ===\n```\n{text}\n```")
        included.append(rel)
    return "\n\n".join(blocks), included, skipped


def parse_files(output: str) -> tuple[dict[str, str], str]:
    """Extract the `=== FILE: path ===` blocks from the output. Return (files, remaining text)."""
    headers = list(FILE_HEADER.finditer(output))
    files: dict[str, str] = {}
    for i, h in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(output)
        body = output[h.end():end].strip("\n")
        lines = body.split("\n")
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
            # the closing fence is the last fence in the block: the content may contain other ```
            for j in range(len(lines) - 1, -1, -1):
                if lines[j].strip().startswith("```"):
                    lines = lines[:j]
                    break
        files[h.group(1).strip()] = "\n".join(lines).rstrip() + "\n"
    notes = output[:headers[0].start()] if headers else output
    return files, notes.strip()


def write_files(
    root: Path,
    files: dict[str, str],
    overwrite: bool,
    backup: dict[str, bytes | None] | None = None,
) -> list[dict]:
    """Write files under root. With `backup`, the original content of every touched path is recorded
    once (None = did not exist) so `rollback` can restore the tree, and paths already in `backup`
    (written by the same job) may be rewritten even without `overwrite`."""
    report = []
    for rel, content in files.items():
        try:
            path = inside(root, root / rel)
        except ValueError as e:
            report.append({"path": rel, "status": f"refused: {e}"})
            continue
        if is_secret(path):
            report.append({"path": rel, "status": "refused: looks like a secret file"})
            continue
        key = path.relative_to(root).as_posix()
        own = backup is not None and key in backup
        if path.exists() and not overwrite and not own:
            report.append({"path": rel, "status": "skipped: already exists (use overwrite=true)"})
            continue
        existed = path.exists()
        if backup is not None and key not in backup:
            backup[key] = path.read_bytes() if existed else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
        report.append({
            "path": key,
            "status": "overwritten" if existed else "created",
            "lines": content.count("\n"),
        })
    return report


def rollback(root: Path, backup: dict[str, bytes | None]) -> list[str]:
    """Restore every path recorded in `backup`: rewrite originals, delete files that did not exist."""
    restored = []
    for rel, original in backup.items():
        path = inside(root, root / rel)
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
        restored.append(rel)
    return restored
