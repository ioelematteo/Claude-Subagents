"""Durable SQLite store for swarm jobs and their event trace."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

JOB_COLUMNS = [
    "id", "session", "label", "profile", "status", "tier", "attempts",
    "tokens_in", "tokens_out", "cost_usd", "created", "started", "finished",
    "root", "verify", "files", "error", "spec",
]

TERMINAL = {"done", "failed", "blocked", "rejected", "cancelled", "interrupted", "over_budget"}

_JSON_COLUMNS = ("files", "spec")

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        session TEXT,
        label TEXT,
        profile TEXT,
        status TEXT,
        tier TEXT,
        attempts INTEGER,
        tokens_in INTEGER,
        tokens_out INTEGER,
        cost_usd REAL,
        created REAL,
        started REAL,
        finished REAL,
        root TEXT,
        verify TEXT,
        files TEXT,
        error TEXT,
        spec TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT,
        ts REAL,
        kind TEXT,
        data TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_job_id ON events(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session)",
)


class Store:
    """Synchronous SQLite-backed store for jobs and events."""

    def __init__(self, path: str | Path) -> None:
        self._lock = threading.Lock()
        target = str(path)
        if target != ":memory:":
            Path(target).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(target, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        if target != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        for statement in _SCHEMA:
            self._db.execute(statement)
        self._db.commit()

    # -- internal helpers -------------------------------------------------

    @staticmethod
    def _encode(key: str, value: object) -> object:
        """JSON-encode list/dict columns, passing everything else through."""
        if key in _JSON_COLUMNS:
            if value is None:
                return None
            return json.dumps(value)
        return value

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict:
        """Convert a raw row to a dict, decoding the JSON columns."""
        data = dict(row)
        for key in _JSON_COLUMNS:
            raw = data.get(key)
            if raw is None:
                data[key] = None
            else:
                try:
                    data[key] = json.loads(raw)
                except (TypeError, ValueError):
                    data[key] = None
        return data

    @staticmethod
    def _load_json(raw: object) -> dict:
        """Decode a stored JSON object column, defaulting to an empty dict."""
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _select_jobs(self, session: str | None) -> list[dict]:
        """Raw job rows (decoded) filtered by session, unordered."""
        if session is None:
            rows = self._db.execute("SELECT * FROM jobs").fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM jobs WHERE session = ?", (session,)
            ).fetchall()
        return [self._decode_row(r) for r in rows]

    # -- jobs -------------------------------------------------------------

    def upsert_job(self, row: dict) -> None:
        """Insert or replace a job. `row` may contain any subset of JOB_COLUMNS plus `id` (required);
        missing columns keep their previous value on update (use INSERT ... ON CONFLICT(id) DO UPDATE
        only for the provided columns). `files` (list) and `spec` (dict) are JSON-encoded here."""
        if not isinstance(row, dict):
            raise ValueError("row must be a dict")
        unknown = [key for key in row if key not in JOB_COLUMNS]
        if unknown:
            raise ValueError(f"unknown job column(s): {', '.join(sorted(map(str, unknown)))}")
        if row.get("id") is None:
            raise ValueError("row must contain an 'id'")
        cols = [c for c in JOB_COLUMNS if c in row]
        values = [self._encode(c, row[c]) for c in cols]
        placeholders = ", ".join("?" for _ in cols)
        set_clause = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id")
        if set_clause:
            sql = (
                f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
            )
        else:
            sql = (
                f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO NOTHING"
            )
        with self._lock:
            self._db.execute(sql, values)
            self._db.commit()

    def get_job(self, job_id: str) -> dict | None:
        """Row as dict with `files` decoded to list and `spec` decoded to dict (None stays None)."""
        row = self._db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._decode_row(row)

    def list_jobs(self, session: str | None = None, limit: int = 500) -> list[dict]:
        """Newest first (by created). Same decoding as get_job."""
        if session is None:
            rows = self._db.execute(
                "SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM jobs WHERE session = ? ORDER BY created DESC LIMIT ?",
                (session, limit),
            ).fetchall()
        return [self._decode_row(r) for r in rows]

    # -- events -----------------------------------------------------------

    def add_event(self, job_id: str, kind: str, data: dict | None = None) -> None:
        """ts = time.time(). data stored as JSON ('{}' when None)."""
        payload = json.dumps(data if data is not None else {})
        with self._lock:
            self._db.execute(
                "INSERT INTO events (job_id, ts, kind, data) VALUES (?, ?, ?, ?)",
                (job_id, time.time(), kind, payload),
            )
            self._db.commit()

    def events(self, job_id: str) -> list[dict]:
        """Oldest first: [{"ts": float, "kind": str, "data": dict}]."""
        rows = self._db.execute(
            "SELECT ts, kind, data FROM events WHERE job_id = ? ORDER BY id ASC",
            (job_id,),
        ).fetchall()
        return [
            {"ts": r["ts"], "kind": r["kind"], "data": self._load_json(r["data"])}
            for r in rows
        ]

    def attempts(self, session: str | None = None) -> list[dict]:
        """All events with kind == "attempt" (optionally only for jobs of `session`), oldest first, each as
        {"job_id", "ts", **data}. data keys: tier, model, tokens_in, tokens_out, cost_usd, seconds, outcome."""
        if session is None:
            rows = self._db.execute(
                "SELECT job_id, ts, data FROM events WHERE kind = 'attempt' ORDER BY id ASC"
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT e.job_id AS job_id, e.ts AS ts, e.data AS data "
                "FROM events e JOIN jobs j ON j.id = e.job_id "
                "WHERE e.kind = 'attempt' AND j.session = ? ORDER BY e.id ASC",
                (session,),
            ).fetchall()
        result: list[dict] = []
        for r in rows:
            entry = {"job_id": r["job_id"], "ts": r["ts"]}
            entry.update(self._load_json(r["data"]))
            result.append(entry)
        return result

    # -- aggregates -------------------------------------------------------

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
        jobs = self._select_jobs(session)

        by_status: dict = {}
        succeeded = 0
        first_try = 0
        escalated = 0
        terminal_count = 0
        tokens_in = 0
        tokens_out = 0
        cost_total = 0.0
        files_written = 0
        done_seconds: list[float] = []
        by_profile: dict = {}

        for job in jobs:
            status = job.get("status")
            by_status[status] = by_status.get(status, 0) + 1

            tokens_in += job.get("tokens_in") or 0
            tokens_out += job.get("tokens_out") or 0
            job_cost = job.get("cost_usd") or 0.0
            cost_total += job_cost

            if status in TERMINAL:
                terminal_count += 1

            profile = job.get("profile")
            bucket = by_profile.setdefault(
                profile, {"jobs": 0, "succeeded": 0, "cost_usd": 0.0}
            )
            bucket["jobs"] += 1
            bucket["cost_usd"] += job_cost

            if status == "done":
                succeeded += 1
                bucket["succeeded"] += 1
                attempts = job.get("attempts") or 0
                if attempts == 1:
                    first_try += 1
                elif attempts > 1:
                    escalated += 1
                files = job.get("files")
                if isinstance(files, list):
                    files_written += len(files)
                started = job.get("started")
                finished = job.get("finished")
                if started is not None and finished is not None:
                    done_seconds.append(finished - started)

        for bucket in by_profile.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 5)

        by_tier: dict = {}
        for attempt in self.attempts(session=session):
            tier = attempt.get("tier")
            bucket = by_tier.setdefault(
                tier, {"calls": 0, "passed": 0, "cost_usd": 0.0}
            )
            bucket["calls"] += 1
            if attempt.get("outcome") == "ok":
                bucket["passed"] += 1
            bucket["cost_usd"] += attempt.get("cost_usd") or 0.0
        for bucket in by_tier.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 5)

        cost_total = round(cost_total, 5)
        success_rate = (succeeded / terminal_count) if terminal_count else 0.0
        cost_per_success = (cost_total / succeeded) if succeeded else None
        if cost_per_success is not None:
            cost_per_success = round(cost_per_success, 5)
        avg_seconds = (sum(done_seconds) / len(done_seconds)) if done_seconds else None

        return {
            "jobs": len(jobs),
            "by_status": dict(by_status),
            "succeeded": succeeded,
            "first_try": first_try,
            "escalated": escalated,
            "success_rate": success_rate,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_total,
            "cost_per_success": cost_per_success,
            "avg_seconds": avg_seconds,
            "files_written": files_written,
            "by_profile": by_profile,
            "by_tier": by_tier,
        }

    # -- lifecycle --------------------------------------------------------

    def mark_interrupted(self) -> int:
        """Set status 'interrupted' and finished=now on every non-terminal job; add an event
        kind 'interrupted' for each; return how many."""
        placeholders = ", ".join("?" for _ in TERMINAL)
        now = time.time()
        with self._lock:
            rows = self._db.execute(
                f"SELECT id FROM jobs WHERE status IS NULL OR status NOT IN ({placeholders})",
                tuple(sorted(TERMINAL)),
            ).fetchall()
            ids = [r["id"] for r in rows]
            for job_id in ids:
                self._db.execute(
                    "UPDATE jobs SET status = 'interrupted', finished = ? WHERE id = ?",
                    (now, job_id),
                )
                self._db.execute(
                    "INSERT INTO events (job_id, ts, kind, data) VALUES (?, ?, ?, ?)",
                    (job_id, now, "interrupted", "{}"),
                )
            self._db.commit()
        return len(ids)

    def close(self) -> None:
        """Close the underlying connection."""
        with self._lock:
            self._db.close()
