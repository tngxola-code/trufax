"""Run history: every run, the last good snapshot of each tracked job, and the changes
between runs. One SQLite file next to the run folders, so a job's history survives
restarts and can be queried by the CLI and the API.

Only *clean* runs become baselines: a full run that passed every check and read every
source without a warning. A partial run (a page that failed, a check that failed) is
still recorded and still compared, but it never becomes the reference for the next run
and it never reports records as removed.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DB_NAME = "trufax-history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    job          TEXT NOT NULL,
    mode         TEXT NOT NULL,
    status       TEXT NOT NULL,
    clean        INTEGER NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT NOT NULL,
    counts       TEXT NOT NULL,
    changes      TEXT,
    baseline_run TEXT,
    out_dir      TEXT
);
CREATE INDEX IF NOT EXISTS runs_by_job ON runs (job, started_at);
CREATE TABLE IF NOT EXISTS snapshots (
    run_id TEXT NOT NULL,
    key    TEXT NOT NULL,
    hash   TEXT NOT NULL,
    data   TEXT NOT NULL,
    PRIMARY KEY (run_id, key)
);
CREATE TABLE IF NOT EXISTS changes (
    run_id TEXT NOT NULL,
    key    TEXT NOT NULL,
    kind   TEXT NOT NULL,
    fields TEXT NOT NULL,
    before TEXT,
    after  TEXT
);
CREATE INDEX IF NOT EXISTS changes_by_run ON changes (run_id);
CREATE TABLE IF NOT EXISTS schedule_state (
    job       TEXT PRIMARY KEY,
    last_fire REAL NOT NULL
);
"""


@dataclass
class Snapshot:
    run_id: str
    records: dict[str, tuple[str, dict[str, Any]]]  # key -> (hash, data)


class History:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)

    @classmethod
    def at(cls, output_root: Path) -> History:
        return cls(output_root / DB_NAME)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commits on success, rolls back on error
                yield conn
        finally:
            conn.close()

    # -- runs ----------------------------------------------------------------
    def latest_baseline(self, job: str) -> Snapshot | None:
        with self._db() as db:
            row = db.execute(
                "SELECT run_id FROM runs WHERE job = ? AND clean = 1 AND mode = 'full' "
                "ORDER BY rowid DESC LIMIT 1",
                (job,),
            ).fetchone()
            if row is None:
                return None
            rows = db.execute(
                "SELECT key, hash, data FROM snapshots WHERE run_id = ?", (row["run_id"],)
            ).fetchall()
        return Snapshot(
            run_id=row["run_id"],
            records={r["key"]: (r["hash"], json.loads(r["data"])) for r in rows},
        )

    def record_run(
        self,
        *,
        run_id: str,
        job: str,
        mode: str,
        status: str,
        clean: bool,
        started_at: str,
        finished_at: str,
        counts: dict[str, int],
        out_dir: str,
        changes: dict[str, Any] | None = None,
        baseline_run: str | None = None,
        snapshot: list[tuple[str, str, dict[str, Any]]] | None = None,
        change_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    job,
                    mode,
                    status,
                    int(clean),
                    started_at,
                    finished_at,
                    json.dumps(counts),
                    json.dumps(changes) if changes is not None else None,
                    baseline_run,
                    out_dir,
                ),
            )
            if snapshot:
                db.executemany(
                    "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
                    [(run_id, k, h, json.dumps(d, default=str)) for k, h, d in snapshot],
                )
            if change_rows:
                db.executemany(
                    "INSERT INTO changes VALUES (?,?,?,?,?,?)",
                    [
                        (
                            run_id,
                            c["key"],
                            c["kind"],
                            json.dumps(c["fields"]),
                            json.dumps(c["before"], default=str) if c["before"] else None,
                            json.dumps(c["after"], default=str) if c["after"] else None,
                        )
                        for c in change_rows
                    ],
                )

    def runs(self, job: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM runs WHERE job = ? ORDER BY rowid DESC LIMIT ?",
                (job, limit),
            ).fetchall()
        return [_run_dict(r) for r in rows]

    def run(self, run_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return _run_dict(row) if row else None

    def latest_tracked_run(self, job: str) -> str | None:
        with self._db() as db:
            row = db.execute(
                "SELECT run_id FROM runs WHERE job = ? AND changes IS NOT NULL "
                "ORDER BY rowid DESC LIMIT 1",
                (job,),
            ).fetchone()
        return row["run_id"] if row else None

    def changes_for(self, run_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT key, kind, fields, before, after FROM changes WHERE run_id = ? "
                "ORDER BY CASE kind WHEN 'changed' THEN 0 WHEN 'new' THEN 1 ELSE 2 END, key",
                (run_id,),
            ).fetchall()
        return [
            {
                "key": json.loads(r["key"]),
                "kind": r["kind"],
                "fields": json.loads(r["fields"]),
                "before": json.loads(r["before"]) if r["before"] else None,
                "after": json.loads(r["after"]) if r["after"] else None,
            }
            for r in rows
        ]

    # -- schedule ------------------------------------------------------------
    def last_fire(self, job: str) -> float | None:
        with self._db() as db:
            row = db.execute(
                "SELECT last_fire FROM schedule_state WHERE job = ?", (job,)
            ).fetchone()
        return row["last_fire"] if row else None

    def set_last_fire(self, job: str, when: float) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO schedule_state VALUES (?, ?)", (job, when))

    def claim_slot(self, job: str, fire: float) -> bool:
        """Atomically take a scheduled time for a job. True only for the one caller that
        moves last_fire forward; overlapping schedulers get False and skip the run."""
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")  # one writer at a time across processes
            row = conn.execute(
                "SELECT last_fire FROM schedule_state WHERE job = ?", (job,)
            ).fetchone()
            if row is not None and fire <= row[0]:
                conn.execute("ROLLBACK")
                return False
            conn.execute("INSERT OR REPLACE INTO schedule_state VALUES (?, ?)", (job, fire))
            conn.execute("COMMIT")
            return True
        finally:
            conn.close()


def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["clean"] = bool(d["clean"])
    d["counts"] = json.loads(d["counts"])
    d["changes"] = json.loads(d["changes"]) if d["changes"] else None
    return d
