"""Recurring runs for jobs with a ``schedule:`` cron expression (UTC).

``trufax schedule --once`` runs whatever is due and exits, for a system cron entry or
timer (every minute is fine). Without ``--once`` it keeps running and checks every
``--interval`` seconds. Either way, the time of the last run per job is kept in the
history database, so a job runs once per scheduled time no matter how often the
scheduler is called or restarted. A job seen for the first time runs at once and
records the baseline.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from croniter import croniter
from pydantic import ValidationError

from .alerts import notify_failure
from .config import JobConfig, load_job
from .history import History
from .runner import output_root, run_job

log = logging.getLogger(__name__)


@dataclass
class Scheduled:
    path: Path
    job: JobConfig


def load_scheduled(jobs_dir: Path) -> tuple[list[Scheduled], list[str]]:
    found: list[Scheduled] = []
    problems: list[str] = []
    for path in sorted(jobs_dir.glob("*.yaml")):
        try:
            job = load_job(path)
        except (ValidationError, ValueError, OSError) as e:
            problems.append(f"{path.name}: {e}")
            continue
        if job.schedule:
            found.append(Scheduled(path, job))
    return found, problems


def last_fire_time(expression: str, now: datetime) -> float:
    return float(croniter(expression, now).get_prev(datetime).timestamp())


def run_due(entries: list[Scheduled], base_dir: Path, now: datetime | None = None) -> list[str]:
    """Run each job whose scheduled time has passed since its last run. Returns the
    names of the jobs that ran."""
    now = now or datetime.now(UTC)
    ran = []
    for entry in entries:
        job = entry.job
        assert job.schedule
        history = History.at(output_root(job, base_dir))
        fire = last_fire_time(job.schedule, now)
        # Claim the slot before running, atomically: a crash or a slow run is never
        # retried every minute, and two overlapping schedulers never both run it.
        if not history.claim_slot(job.job, fire):
            continue
        ran.append(job.job)
        try:
            result = run_job(job, base_dir=base_dir)
            print(f"{job.job}: run {result.manifest.run_id} {result.manifest.status}")
        except Exception as e:  # one failing job must not stop the others
            log.exception("scheduled run of %s failed", job.job)
            print(f"{job.job}: failed: {type(e).__name__}: {e}")
            notify_failure(job, e)
    return ran


def serve(jobs_dir: Path, base_dir: Path, once: bool = False, interval: int = 30) -> int:
    entries, problems = load_scheduled(jobs_dir)
    for p in problems:
        print(f"skipped {p}")
    if not entries:
        print(f"no jobs with a schedule in {jobs_dir}")
        return 0 if not problems else 2
    if once:
        run_due(entries, base_dir)
        return 0
    print(", ".join(f"{e.job.job} [{e.job.schedule}]" for e in entries))
    while True:  # pragma: no cover - long-running loop
        run_due(entries, base_dir)
        time.sleep(interval)
