"""Static HTML dashboard generated from the swarm job store.

Usage::

    python -m swarm.dashboard [--db PATH] [--out PATH] [--session ID]

Renders one self-contained HTML document (inline CSS, one Chart.js script tag,
all data embedded as a JSON literal) and prints the path of the written file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
from pathlib import Path
from typing import Any

from swarm.config import DB_PATH
from swarm.store import TERMINAL, Store

RECENT_LIMIT = 50
DEFAULT_OUT = Path(DB_PATH).parent / "dashboard.html"
CHART_JS = "https://cdn.jsdelivr.net/npm/chart.js@4"
FALLBACK_COLOR = "#6b7280"

_JOB_HEADERS = (
    "id", "label", "profile", "status", "tier",
    "attempts", "cost", "seconds", "created",
)

# Status -> pill CSS class (one accent-driven palette, see :root in _CSS).
STATUS_CLASS = {
    "done": "ok",
    "failed": "bad",
    "over_budget": "bad",
    "blocked": "muted",
    "rejected": "muted",
    "cancelled": "muted",
    "interrupted": "muted",
    "running": "run",
    "verifying": "run",
    "waiting": "run",
    "queued": "run",
    "awaiting_approval": "warn",
}

# Status -> chart color (doughnut slices).
STATUS_COLOR = {
    "done": "#16a34a",
    "failed": "#dc2626",
    "over_budget": "#dc2626",
    "blocked": "#6b7280",
    "rejected": "#6b7280",
    "cancelled": "#6b7280",
    "interrupted": "#6b7280",
    "running": "#2563eb",
    "verifying": "#2563eb",
    "waiting": "#2563eb",
    "queued": "#2563eb",
    "awaiting_approval": "#d97706",
}


# --------------------------------------------------------------------------
# formatting helpers
# --------------------------------------------------------------------------

def _esc(value: Any) -> str:
    """Escape any value for safe insertion as HTML text."""
    if value is None:
        return "—"
    return html.escape(str(value), quote=True)


def _key(value: Any) -> str:
    """Label for a possibly-missing grouping key."""
    return "unknown" if value is None else str(value)


def _fmt_money(value: Any) -> str:
    """Dollar amount with four decimals, or an em dash when unknown."""
    if value is None:
        return "—"
    try:
        return f"${float(value):,.4f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_seconds(value: Any) -> str:
    """Duration in seconds (compact), or an em dash when unknown."""
    if value is None:
        return "—"
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "—"
    if seconds < 0:
        return "—"
    if seconds < 60:
        return f"{seconds:,.1f}s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {rest:04.1f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes:02d}m"


def _fmt_pct(value: Any) -> str:
    """Fraction rendered as a percentage, or an em dash when unknown."""
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:,.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_time(value: Any) -> str:
    """Epoch seconds as a local timestamp, or an em dash when unknown."""
    if value is None:
        return "—"
    try:
        return dt.datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def _fmt_offset(seconds: float) -> str:
    """Signed offset from the start of a job trace."""
    if seconds < 0:
        seconds = 0.0
    if seconds < 60:
        return f"+{seconds:.1f}s"
    minutes, rest = divmod(seconds, 60)
    return f"+{int(minutes)}m{rest:04.1f}s"


def _job_seconds(job: dict) -> float | None:
    """Duration of a finished job, or None when not finished."""
    started = job.get("started")
    finished = job.get("finished")
    if started is None or finished is None:
        return None
    try:
        return float(finished) - float(started)
    except (TypeError, ValueError):
        return None


def _status_pill(status: Any) -> str:
    """Colored status pill."""
    text = _key(status)
    cls = STATUS_CLASS.get(text, "muted")
    return f'<span class="pill {cls}">{_esc(text)}</span>'


def _card(label: str, value: Any, hint: str = "") -> str:
    """One KPI card."""
    hint_html = f'<div class="hint">{_esc(hint)}</div>' if hint else ""
    return (
        '<div class="card">'
        f'<div class="k">{_esc(label)}</div>'
        f'<div class="v">{_esc(value)}</div>'
        f"{hint_html}"
        "</div>"
    )


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def _render_trace(store: Store, job_id: str) -> str:
    """Event trace block for a single job."""
    events = store.events(job_id)
    if not events:
        return '<div class="trace"><p class="hint">No events recorded.</p></div>'

    try:
        base = float(events[0].get("ts") or 0.0)
    except (TypeError, ValueError):
        base = 0.0

    rows = []
    for event in events:
        try:
            offset = float(event.get("ts") or 0.0) - base
        except (TypeError, ValueError):
            offset = 0.0
        data = event.get("data") or {}
        try:
            raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            raw = "{}"
        if len(raw) > 240:
            raw = raw[:237] + "..."
        rows.append(
            "<tr>"
            f'<td class="off">{_esc(_fmt_offset(offset))}</td>'
            f'<td class="kind">{_esc(event.get("kind"))}</td>'
            f'<td class="data">{_esc(raw)}</td>'
            "</tr>"
        )

    return (
        '<div class="trace"><table class="events">'
        "<thead><tr><th>offset</th><th>kind</th><th>data</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


def _render_jobs(store: Store, jobs: list[dict]) -> str:
    """Recent-jobs list; each row expands to its event trace."""
    head = (
        '<div class="job-head">'
        + "".join(f"<span>{_esc(name)}</span>" for name in _JOB_HEADERS)
        + "</div>"
    )
    items = []
    for job in jobs:
        job_id = job.get("id")
        row = (
            '<summary class="job-summary">'
            f'<span class="mono" data-label="id">{_esc(job_id)}</span>'
            f'<span class="label" data-label="label">{_esc(job.get("label"))}</span>'
            f'<span data-label="profile">{_esc(job.get("profile"))}</span>'
            f'<span data-label="status">{_status_pill(job.get("status"))}</span>'
            f'<span data-label="tier">{_esc(job.get("tier"))}</span>'
            f'<span data-label="attempts">{_esc(job.get("attempts"))}</span>'
            f'<span data-label="cost">{_esc(_fmt_money(job.get("cost_usd")))}</span>'
            f'<span data-label="seconds">{_esc(_fmt_seconds(_job_seconds(job)))}</span>'
            f'<span data-label="created">{_esc(_fmt_time(job.get("created")))}</span>'
            "</summary>"
        )
        trace = _render_trace(store, "" if job_id is None else str(job_id))
        items.append(f'<details class="job">{row}{trace}</details>')
    return head + "".join(items)


def _render_charts() -> str:
    """The three chart panels."""
    panels = (
        ("Cost by profile", "chart-profile"),
        ("Attempts by tier", "chart-tier"),
        ("Jobs by status", "chart-status"),
    )
    return '<section class="charts">' + "".join(
        f'<div class="panel"><h2>{_esc(title)}</h2>'
        f'<div class="canvas"><canvas id="{_esc(canvas_id)}"></canvas></div></div>'
        for title, canvas_id in panels
    ) + "</section>"


def _render_script(chart_data: dict) -> str:
    """Inline Chart.js bootstrap with the embedded data literal."""
    payload = (
        json.dumps(chart_data, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return (
        "<script>\n"
        "(function () {\n"
        f"  const DATA = {payload};\n"
        "  if (typeof Chart === 'undefined') { return; }\n"
        "  const css = getComputedStyle(document.body);\n"
        "  const read = (name, fallback) => {\n"
        "    const value = (css.getPropertyValue(name) || '').trim();\n"
        "    return value || fallback;\n"
        "  };\n"
        "  const fg = read('--fg', '#1b1f24');\n"
        "  const muted = read('--muted', '#6b7280');\n"
        "  const grid = read('--border', '#e3e6ea');\n"
        "  const accent = read('--accent', '#2563eb');\n"
        "  Chart.defaults.color = muted;\n"
        "  Chart.defaults.font.size = 11;\n"
        "  Chart.defaults.font.family = \"-apple-system, BlinkMacSystemFont, 'Segoe UI', \"\n"
        "    + \"Roboto, Helvetica, Arial, sans-serif\";\n"
        "  const axis = () => ({\n"
        "    ticks: { color: muted, maxRotation: 0, autoSkipPadding: 8 },\n"
        "    grid: { color: grid },\n"
        "    beginAtZero: true\n"
        "  });\n"
        "  const el = (id) => document.getElementById(id);\n"
        "  if (el('chart-profile')) {\n"
        "    new Chart(el('chart-profile'), {\n"
        "      type: 'bar',\n"
        "      data: {\n"
        "        labels: DATA.profile.labels,\n"
        "        datasets: [{ label: 'Cost (USD)', data: DATA.profile.costs,\n"
        "          backgroundColor: accent, borderRadius: 4, maxBarThickness: 42 }]\n"
        "      },\n"
        "      options: {\n"
        "        responsive: true, maintainAspectRatio: false,\n"
        "        plugins: {\n"
        "          legend: { display: false },\n"
        "          tooltip: { callbacks: { label: (c) => '$' + Number(c.parsed.y).toFixed(4) } }\n"
        "        },\n"
        "        scales: { x: axis(), y: axis() }\n"
        "      }\n"
        "    });\n"
        "  }\n"
        "  if (el('chart-tier')) {\n"
        "    new Chart(el('chart-tier'), {\n"
        "      type: 'bar',\n"
        "      data: {\n"
        "        labels: DATA.tier.labels,\n"
        "        datasets: [\n"
        "          { label: 'passed', data: DATA.tier.passed, backgroundColor: '#16a34a',\n"
        "            borderRadius: 3, maxBarThickness: 42 },\n"
        "          { label: 'failed', data: DATA.tier.failed, backgroundColor: '#dc2626',\n"
        "            borderRadius: 3, maxBarThickness: 42 }\n"
        "        ]\n"
        "      },\n"
        "      options: {\n"
        "        responsive: true, maintainAspectRatio: false,\n"
        "        plugins: { legend: { display: true, position: 'bottom',\n"
        "          labels: { color: muted, boxWidth: 10, boxHeight: 10, usePointStyle: true } } },\n"
        "        scales: { x: Object.assign(axis(), { stacked: true }),\n"
        "          y: Object.assign(axis(), { stacked: true }) }\n"
        "      }\n"
        "    });\n"
        "  }\n"
        "  if (el('chart-status')) {\n"
        "    new Chart(el('chart-status'), {\n"
        "      type: 'doughnut',\n"
        "      data: {\n"
        "        labels: DATA.status.labels,\n"
        "        datasets: [{ data: DATA.status.counts, backgroundColor: DATA.status.colors,\n"
        "          borderWidth: 1, borderColor: 'transparent' }]\n"
        "      },\n"
        "      options: {\n"
        "        responsive: true, maintainAspectRatio: false, cutout: '58%',\n"
        "        plugins: { legend: { display: true, position: 'bottom',\n"
        "          labels: { color: muted, boxWidth: 10, boxHeight: 10, usePointStyle: true } } }\n"
        "      }\n"
        "    });\n"
        "  }\n"
        "})();\n"
        "</script>\n"
    )


def _chart_data(summary: dict) -> dict:
    """Shape the summary aggregates for the three charts."""
    profile_items = sorted(
        summary["by_profile"].items(),
        key=lambda kv: (-float(kv[1].get("cost_usd") or 0.0), _key(kv[0])),
    )
    tier_items = sorted(summary["by_tier"].items(), key=lambda kv: _key(kv[0]))
    status_items = sorted(
        summary["by_status"].items(),
        key=lambda kv: (-int(kv[1]), _key(kv[0])),
    )
    return {
        "profile": {
            "labels": [_key(k) for k, _ in profile_items],
            "costs": [round(float(v.get("cost_usd") or 0.0), 5) for _, v in profile_items],
        },
        "tier": {
            "labels": [_key(k) for k, _ in tier_items],
            "passed": [int(v.get("passed") or 0) for _, v in tier_items],
            "failed": [max(int(v.get("calls") or 0) - int(v.get("passed") or 0), 0)
                       for _, v in tier_items],
        },
        "status": {
            "labels": [_key(k) for k, _ in status_items],
            "counts": [int(v) for _, v in status_items],
            "colors": [STATUS_COLOR.get(_key(k), FALLBACK_COLOR) for k, _ in status_items],
        },
    }


# --------------------------------------------------------------------------
# document
# --------------------------------------------------------------------------

_CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#f5f6f8;--panel:#ffffff;--panel-2:#fafbfc;--fg:#1b1f24;--muted:#6b7280;
  --border:#e3e6ea;--accent:#2563eb;
  --ok-bg:#dcfce7;--ok-fg:#166534;--bad-bg:#fee2e2;--bad-fg:#991b1b;
  --warn-bg:#fef3c7;--warn-fg:#92400e;--run-bg:#dbeafe;--run-fg:#1e40af;
  --gray-bg:#e5e7eb;--gray-fg:#374151;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#0f1115;--panel:#171a1f;--panel-2:#1c2026;--fg:#e6e8eb;--muted:#9aa3ae;
    --border:#2a2f37;--accent:#60a5fa;
    --ok-bg:#123524;--ok-fg:#86efac;--bad-bg:#3b1518;--bad-fg:#fca5a5;
    --warn-bg:#3a2c0c;--warn-fg:#fcd34d;--run-bg:#12233f;--run-fg:#93c5fd;
    --gray-bg:#262b33;--gray-fg:#cbd5e1;
  }
}
body{margin:0;background:var(--bg);color:var(--fg);line-height:1.45;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 56px}
header.top{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;
  justify-content:space-between;padding:2px 0 16px;border-bottom:1px solid var(--border);
  margin-bottom:22px}
h1{font-size:1.45rem;margin:0;letter-spacing:-.01em;font-weight:650}
h1 .dot{display:inline-block;width:9px;height:9px;border-radius:50%;
  background:var(--accent);margin-right:9px;vertical-align:middle}
.scope{color:var(--muted);font-size:.83rem}
.scope .chip{background:var(--panel);border:1px solid var(--border);border-radius:999px;
  padding:1px 9px;font-family:var(--mono);font-size:.78rem}
h2{font-size:.92rem;margin:0 0 12px;font-weight:650;letter-spacing:.01em}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:12px;
  margin-bottom:22px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  padding:12px 14px}
.card .k{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em}
.card .v{font-size:1.32rem;font-weight:650;margin-top:4px;font-variant-numeric:tabular-nums}
.card .hint{color:var(--muted);font-size:.74rem;margin-top:2px}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px;
  margin-bottom:22px}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px}
.canvas{position:relative;height:242px}
.empty{color:var(--muted);text-align:center;padding:40px 16px}
.jobs{--cols:1.1fr 1.9fr 1fr 1.1fr .9fr .6fr .9fr .8fr 1.3fr;
  background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px}
.job-head{display:grid;grid-template-columns:var(--cols);gap:10px;padding:0 8px 8px;
  color:var(--muted);font-size:.71rem;text-transform:uppercase;letter-spacing:.06em;
  border-bottom:1px solid var(--border)}
details.job{border-bottom:1px solid var(--border)}
details.job:last-child{border-bottom:none}
summary.job-summary{display:grid;grid-template-columns:var(--cols);gap:10px;padding:9px 8px;
  align-items:center;cursor:pointer;font-size:.85rem;list-style:none}
summary.job-summary::-webkit-details-marker{display:none}
summary.job-summary:hover{background:var(--panel-2)}
details[open] > summary.job-summary{background:var(--panel-2);
  box-shadow:inset 3px 0 0 var(--accent)}
.mono{font-family:var(--mono);font-size:.79rem;overflow-wrap:anywhere}
.label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.trace{padding:4px 8px 14px;overflow-x:auto}
table.events{width:100%;border-collapse:collapse;font-size:.78rem}
table.events th{text-align:left;color:var(--muted);font-weight:600;font-size:.69rem;
  text-transform:uppercase;letter-spacing:.06em;padding:4px 8px;
  border-bottom:1px solid var(--border)}
table.events td{padding:4px 8px;vertical-align:top;border-bottom:1px solid var(--border)}
table.events tr:last-child td{border-bottom:none}
table.events td.off{white-space:nowrap;color:var(--muted);font-family:var(--mono)}
table.events td.kind{white-space:nowrap;font-weight:600}
table.events td.data{font-family:var(--mono);color:var(--muted);word-break:break-word}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:.72rem;
  font-weight:650;background:var(--gray-bg);color:var(--gray-fg);white-space:nowrap}
.pill.ok{background:var(--ok-bg);color:var(--ok-fg)}
.pill.bad{background:var(--bad-bg);color:var(--bad-fg)}
.pill.warn{background:var(--warn-bg);color:var(--warn-fg)}
.pill.run{background:var(--run-bg);color:var(--run-fg)}
.pill.muted{background:var(--gray-bg);color:var(--gray-fg)}
.hint{color:var(--muted);font-size:.78rem}
@media (max-width:900px){
  .job-head{display:none}
  summary.job-summary{grid-template-columns:1fr 1fr;gap:4px 12px;padding:10px 8px}
  summary.job-summary > span::before{content:attr(data-label) ": ";color:var(--muted)}
  .label{white-space:normal}
  .canvas{height:210px}
}
"""


def render(store: Store, session: str | None = None) -> str:
    """Render the complete dashboard document for the given (optional) session."""
    summary = store.summary(session=session)
    jobs = store.list_jobs(session=session, limit=RECENT_LIMIT)

    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scope = "all time" if session is None else f"session {session}"

    succeeded = int(summary.get("succeeded") or 0)
    first_try = int(summary.get("first_try") or 0)
    escalated = int(summary.get("escalated") or 0)
    terminal_count = sum(
        int(count) for status, count in summary["by_status"].items() if status in TERMINAL
    )
    first_try_rate = (first_try / succeeded) if succeeded else None

    cards = "".join([
        _card("Jobs", summary["jobs"]),
        _card("Success rate", _fmt_pct(summary["success_rate"]),
              f"{succeeded} of {terminal_count} terminal"),
        _card("First try", _fmt_pct(first_try_rate), f"{first_try} of {succeeded} done"),
        _card("Escalated", escalated, "done after more than one attempt"),
        _card("Total cost", _fmt_money(summary["cost_usd"]),
              f"{summary['tokens_in']} in / {summary['tokens_out']} out tokens"),
        _card("Cost per success", _fmt_money(summary["cost_per_success"]), "total cost / done"),
        _card("Avg seconds", _fmt_seconds(summary["avg_seconds"]), "over done jobs"),
        _card("Files written", summary["files_written"], "over done jobs"),
    ])

    if jobs:
        body = (
            _render_charts()
            + f'<section class="jobs">{_render_jobs(store, jobs)}</section>'
        )
        script = _render_script(_chart_data(summary))
    else:
        note = "No jobs yet" if session is None else f"No jobs yet in session {session}"
        body = f'<div class="panel empty">{_esc(note)}</div>'
        script = ""

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Swarm dashboard</title>\n"
        f'<script src="{_esc(CHART_JS)}"></script>\n'
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="wrap">\n'
        '<header class="top">\n'
        '<h1><span class="dot"></span>Swarm dashboard</h1>\n'
        f'<div class="scope">Generated {_esc(generated)} · '
        f'<span class="chip">{_esc(scope)}</span></div>\n'
        "</header>\n"
        f'<section class="kpis">{cards}</section>\n'
        f"{body}\n"
        "</div>\n"
        f"{script}"
        "</body>\n"
        "</html>\n"
    )


def main() -> None:
    """CLI entrypoint: render the dashboard and print the written path."""
    parser = argparse.ArgumentParser(
        prog="python -m swarm.dashboard",
        description="Render a static HTML dashboard from the swarm store.",
    )
    parser.add_argument("--db", default=str(DB_PATH), help="path to the SQLite store")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output HTML path")
    parser.add_argument("--session", default=None, help="restrict to one session id")
    args = parser.parse_args()

    store = Store(args.db)
    try:
        document = render(store, session=args.session)
    finally:
        store.close()

    out = Path(args.out).expanduser()
    if out.parent != Path(""):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
