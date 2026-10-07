"""Runs a job: extract -> validate -> export -> manifest + proof report."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .adapters import ADAPTERS
from .config import JobConfig
from .export import write_outputs
from .fetch import make_fetcher
from .report import Manifest, make_manifest, render_report
from .validate import Outcome, completeness, validate

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    out_dir: Path
    manifest: Manifest
    outcome: Outcome

    @property
    def report(self) -> Path:
        return self.out_dir / "proof-report.html"


def new_run_id(sample: bool = False) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:6]}" + ("-sample" if sample else "")


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
    root = Path(out_root or job.output.dir)
    if not root.is_absolute() and base_dir is not None:
        root = base_dir / root
    out_dir = root / job.job / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    adapter_cls = ADAPTERS[job.source.type]
    with make_fetcher(job.source.fetch, cache_dir=root / ".cache") as fetcher:
        adapter = adapter_cls(job, fetcher, limit=limit)
        records = adapter.extract()
        fetches = fetcher.log

    outcome = validate(records, job.validation, extra_checks=adapter.checks)
    fields = job.output_fields
    outputs = write_outputs(out_dir, fields, outcome.valid, outcome.rejected, job.output)
    manifest = make_manifest(
        run_id, job, mode, started, datetime.now(UTC), outcome, fetches, adapter.warnings, outputs
    )
    manifest.outputs += ["manifest.json", "proof-report.html"]
    manifest.write(out_dir / "manifest.json")
    html = render_report(
        manifest,
        fields,
        completeness(outcome.records, fields),
        outcome.valid,
        outcome.rejected,
        job.description,
    )
    (out_dir / "proof-report.html").write_text(html, encoding="utf-8")
    log.info("run %s: %s", run_id, outcome.counts)
    return RunResult(out_dir=out_dir, manifest=manifest, outcome=outcome)
