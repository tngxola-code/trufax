"""Webhook alerts: tell a client when a run failed, needs review, or found changes.

The webhook URL comes from an environment variable named in the job (``alerts.
webhook_url_env``), so it never sits in a job file. Delivery failures are logged and
never fail the run.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .changes import ChangeSet
from .config import JobConfig
from .fetch import FetchError, expand_env
from .report import Manifest

log = logging.getLogger(__name__)

MAX_CHANGES_IN_PAYLOAD = 50


def _url(job: JobConfig) -> str | None:
    assert job.alerts is not None
    try:
        return expand_env("${env:" + job.alerts.webhook_url_env + "}")
    except FetchError as e:
        log.warning("alerts for %s not sent: %s", job.job, e)
        return None


def _post(job: JobConfig, payload: dict[str, Any]) -> bool:
    url = _url(job)
    if not url:
        return False
    try:
        httpx.post(url, json=payload, timeout=15).raise_for_status()
        return True
    except httpx.HTTPError as e:
        log.warning("alert webhook for %s failed: %s", job.job, type(e).__name__)
        return False


def _base(job: JobConfig, event: str) -> dict[str, Any]:
    return {"event": event, "job": job.job, "client": job.client, "platform": "trufax"}


def notify_run(
    job: JobConfig, manifest: Manifest, changes: ChangeSet | None, report: str
) -> list[str]:
    """Send the alerts a finished run calls for. Returns the events sent."""
    cfg = job.alerts
    if cfg is None or manifest.mode != "full":
        return []
    sent = []
    if manifest.status != "PASSED" and "review" in cfg.on:
        payload = _base(job, "review") | {
            "run_id": manifest.run_id,
            "counts": manifest.counts,
            "failed_checks": [c["name"] for c in manifest.checks if not c["passed"]],
            "warnings": manifest.warnings[:20],
            "report": report,
        }
        if _post(job, payload):
            sent.append("review")
    if (
        changes is not None
        and changes.baseline_run is not None
        and "changes" in cfg.on
        and changes.total >= cfg.min_changes
    ):
        rows = changes.rows()
        payload = _base(job, "changes") | {
            "run_id": manifest.run_id,
            "status": manifest.status,
            "changes": changes.counts,
            "items": [{k: v for k, v in c.items() if k != "values"} for c in rows][
                :MAX_CHANGES_IN_PAYLOAD
            ],
            "more": max(0, len(rows) - MAX_CHANGES_IN_PAYLOAD),
            "report": report,
        }
        if _post(job, payload):
            sent.append("changes")
    return sent


def notify_failure(job: JobConfig, error: BaseException) -> bool:
    cfg = job.alerts
    if cfg is None or "failure" not in cfg.on:
        return False
    return _post(job, _base(job, "failure") | {"error": f"{type(error).__name__}: {error}"})
