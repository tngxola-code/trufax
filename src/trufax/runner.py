"""Runs a job: extract -> validate -> compare with history -> export -> manifest, proof
report and alerts."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .adapters import ADAPTERS
from .alerts import notify_run
from .changes import ChangeSet, change_table, detect
from .config import JobConfig
from .export import write_csv, write_outputs
from .fetch import make_fetcher
from .history import History
from .report import Manifest, make_manifest, render_report
from .validate import Check, Outcome, completeness, validate

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    out_dir: Path
    manifest: Manifest
    outcome: Outcome
    changes: ChangeSet | None = None
    alerts_sent: list[str] = field(default_factory=list)

    @property
    def report(self) -> Path:
        return self.out_dir / "proof-report.html"


def new_run_id(sample: bool = False) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:6]}" + ("-sample" if sample else "")


def output_root(job: JobConfig, base_dir: Path | None = None, out_root: Path | None = None) -> Path:
    root = Path(out_root or job.output.dir)
    if not root.is_absolute() and base_dir is not None:
        root = base_dir / root
    return root


def run_job(
    job: JobConfig,
    base_dir: Path | None = None,
    limit: int | None = None,
    out_root: Path | None = None,
    run_id: str | None = None,
) -> RunResult:
    started = datetime.now(UTC)
    mode = "sample" if limit else "full"
    run_id = run_id or new_run_id(sample=bool(limit))
    root = output_root(job, base_dir, out_root)
    out_dir = root / job.job / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    tracking = job.tracked and mode == "full"

    # A tracked job must see the site as it is now: cached pages are only reused when
    # the job sets cache_ttl itself.
    max_age = 0.0 if tracking and job.source.fetch.cache_ttl is None else None
    adapter_cls = ADAPTERS[job.source.type]
    with make_fetcher(job.source.fetch, cache_dir=root / ".cache", max_age=max_age) as fetcher:
        adapter = adapter_cls(job, fetcher, limit=limit)
        records = adapter.extract()
        fetches = fetcher.log

    source_check = Check(
        "Every source read without warnings",
        not adapter.warnings,
        "all pages and files read"
        if not adapter.warnings
        else f"{len(adapter.warnings)} warning(s); data may be incomplete",
    )
    outcome = validate(records, job.validation, extra_checks=[*adapter.checks, source_check])
    fields = job.output_fields
    outputs = write_outputs(out_dir, fields, outcome.valid, outcome.rejected, job.output)

    history = History.at(root)
    cs: ChangeSet | None = None
    snapshot = None
    if tracking:
        clean = outcome.passed and outcome.counts["valid"] > 0
        cs, snapshot = detect(
            outcome.valid, fields, job.validation.key, history.latest_baseline(job.job), clean
        )
        if not clean:
            snapshot = None  # a partial run never becomes the reference for the next one
        outcome.checks.append(Check("Change detection", True, cs.summary()))
        if cs.baseline_run is not None and cs.total:
            rows, columns = change_table(cs, fields)
            write_csv(out_dir / "changes.csv", rows, columns)
            outputs.append(out_dir / "changes.csv")
    elif job.changes.enabled and mode == "full":
        outcome.checks.append(
            Check("Change detection", True, "skipped: records have no key to match on")
        )

    finished = datetime.now(UTC)
    manifest = make_manifest(
        run_id, job, mode, started, finished, outcome, fetches, adapter.warnings, outputs
    )
    manifest.changes = cs.counts if cs else None
    manifest.outputs += ["manifest.json", "proof-report.html"]
    manifest.write(out_dir / "manifest.json")
    html = render_report(
        manifest,
        fields,
        completeness(outcome.records, fields),
        outcome.valid,
        outcome.rejected,
        job.description,
        change_rows=cs.rows() if cs else None,
    )
    (out_dir / "proof-report.html").write_text(html, encoding="utf-8")

    history.record_run(
        run_id=run_id,
        job=job.job,
        mode=mode,
        status=manifest.status,
        clean=snapshot is not None,
        started_at=manifest.started_at,
        finished_at=manifest.finished_at,
        counts=outcome.counts,
        out_dir=str(out_dir),
        changes=cs.counts if cs else None,
        baseline_run=cs.baseline_run if cs else None,
        snapshot=snapshot,
        change_rows=cs.rows() if cs else None,
    )
    sent = notify_run(job, manifest, cs, str(out_dir / "proof-report.html"))
    log.info("run %s: %s", run_id, outcome.counts)
    return RunResult(
        out_dir=out_dir, manifest=manifest, outcome=outcome, changes=cs, alerts_sent=sent
    )
