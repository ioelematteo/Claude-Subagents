"""Claude Code hooks that remind Claude to delegate to DeepSeek subagents.

- UserPromptSubmit: if the request looks big or multi-part, adds a short
  reminder to the turn context.
- PostToolUse on Write/Edit: counts the lines Claude writes itself; if there
  are many and the session has not delegated anything yet, it points that out.
- PostToolUse on the spawn tools: marks the session as "delegating".

Standard library only: it runs on every prompt and every write, so it must be fast.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

LINES_THRESHOLD = 250
LONG_PROMPT = 600
STATE_DIR = Path(tempfile.gettempdir()) / "claude-swarm"

BIG_WORK = re.compile(
    r"\b(implementa|crea|costruisci|genera|sviluppa|riscrivi|refactor\w*|migra|converti|traduci|riassumi|"
    r"documenta|test|progetto|app|api|crud|componenti|endpoint|implement|create|build|generate|rewrite|"
    r"migrate|convert|translate|summari[sz]e|document|project|components)\b",
    re.IGNORECASE,
)
LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.MULTILINE)

PROMPT_NUDGE = (
    "[deepseek-swarm] This request looks big or multi-part. Before doing it all yourself: plan and define "
    "contracts, then delegate the bounded parts (implement/tests/bulk/digest/write) with "
    "mcp__subagents__spawn_many using root + context_files + apply=true, and keep the hard parts and "
    "verification for yourself. Skip this if the work is small, ambiguous or mostly debugging."
)


def state_path(session_id: str) -> Path:
    STATE_DIR.mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "unknown")
    return STATE_DIR / f"{safe}.json"


def load(session_id: str) -> dict:
    try:
        return json.loads(state_path(session_id).read_text())
    except (OSError, ValueError):
        return {"lines": 0, "delegated": False, "next_nudge": LINES_THRESHOLD}


def save(session_id: str, state: dict):
    state_path(session_id).write_text(json.dumps(state))


def on_prompt(event: dict):
    prompt = event.get("prompt", "")
    if prompt.lstrip().startswith("/"):
        return
    many_items = len(LIST_ITEM.findall(prompt)) >= 3
    if len(prompt) >= LONG_PROMPT or many_items or (len(prompt) >= 120 and len(BIG_WORK.findall(prompt)) >= 2):
        print(PROMPT_NUDGE)


def on_tool(event: dict):
    session = event.get("session_id", "")
    tool = event.get("tool_name", "")
    state = load(session)

    if tool.startswith("mcp__subagents__"):
        state["delegated"] = True
        save(session, state)
        return

    tool_input = event.get("tool_input") or {}
    text = tool_input.get("content") or tool_input.get("file_text") or tool_input.get("new_string") or ""
    for edit in tool_input.get("edits") or []:
        text += edit.get("new_string", "")
    state["lines"] += text.count("\n") + (1 if text else 0)

    if not state["delegated"] and state["lines"] >= state["next_nudge"]:
        state["next_nudge"] = state["lines"] * 2
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"[deepseek-swarm] You have written ~{state['lines']} lines yourself this session and delegated "
                "nothing. If more files/tests/boilerplate/docs remain, delegate them with "
                "mcp__subagents__spawn_many (root + context_files + apply=true) and verify, instead of typing "
                "them out."
            ),
        }}))
    save(session, state)


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    name = event.get("hook_event_name")
    if name == "UserPromptSubmit":
        on_prompt(event)
    elif name == "PostToolUse":
        on_tool(event)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # a broken hook must never block Claude
        print(f"nudge hook error: {e}", file=sys.stderr)
