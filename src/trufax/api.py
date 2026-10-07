"""Headless HTTP API. Everything the CLI does, over HTTP, for any UI, service or agent.

Run it with ``trufax serve`` (needs ``pip install 'trufax[api]'``). State lives in
``TRUFAX_HOME``:

    jobs/     job files saved through the API
    data/     local source files jobs may read (nothing outside it)
    output/   one folder per run: data files, manifest.json, proof-report.html

Set ``TRUFAX_API_KEY`` to require ``Authorization: Bearer <key>`` (or ``X-API-Key``)
on every endpoint except ``/health``.

Jobs run through the API may only reference secrets named ``TRUFAX_SECRET_*`` in
``${env:...}``, so a submitted job cannot read the server's other variables.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import ValidationError

from . import __version__
from .config import UnsafePath, parse_job
from .fetch import restrict_env
from .packs import PackError, available_packs, get_pack
from .runner import new_run_id, run_job

log = logging.getLogger(__name__)

SECRET_PREFIX = "TRUFAX_SECRET_"
JOB_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}(-sample)?$")


@dataclass
class RunState:
    run_id: str
    job: str
    status: str = "queued"  # queued, running, passed, review, failed
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    error: str | None = None
    out_dir: Path | None = None


class Store:
    def __init__(self, home: Path, max_parallel: int = 2):
        self.home = home.resolve()
        for sub in ("jobs", "data", "output"):
            (self.home / sub).mkdir(parents=True, exist_ok=True)
        self.runs: dict[str, RunState] = {}
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(max_parallel)

    @property
    def data(self) -> Path:
        return self.home / "data"

    def job_path(self, name: str) -> Path:
        if not JOB_NAME.match(name):
            raise HTTPException(400, "job names use lowercase letters, digits, '-' and '_'")
        return self.home / "jobs" / f"{name}.yaml"

    def load_job(self, name: str):
        path = self.job_path(name)
        if not path.exists():
            raise HTTPException(404, f"job '{name}' not found")
        return parse_job(
            path.read_text(encoding="utf-8"), self.data, local_root=self.data, name=name
        )

    def run_dir(self, run_id: str) -> Path | None:
        if not RUN_ID.match(run_id):
            raise HTTPException(400, "malformed run id")
        state = self.runs.get(run_id)
        if state and state.out_dir:
            return state.out_dir
        found = list((self.home / "output").glob(f"*/{run_id}/manifest.json"))
        return found[0].parent if found else None


def _check_key(request: Request) -> None:
    expected = os.environ.get("TRUFAX_API_KEY")
    if not expected:
        return
    auth = request.headers.get("authorization", "")
    given = auth[7:] if auth.lower().startswith("bearer ") else request.headers.get("x-api-key", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "missing or invalid API key")


def create_app(home: Path | None = None) -> FastAPI:
    restrict_env(SECRET_PREFIX)
    store = Store(
        Path(home or os.environ.get("TRUFAX_HOME", "trufax-home")),
        int(os.environ.get("TRUFAX_MAX_RUNS", "2")),
    )
    if not os.environ.get("TRUFAX_API_KEY"):
        log.warning("TRUFAX_API_KEY is not set: the API is open to anyone who can reach it")

    app = FastAPI(
        title="Trufax",
        version=__version__,
        description="Headless, config-driven data extraction with proof.",
    )
    app.state.store = store
    auth = [Depends(_check_key)]

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    # -- packs ------------------------------------------------------------------
    @app.get("/v1/packs", dependencies=auth)
    def list_packs() -> list[dict[str, Any]]:
        return [
            {
                "pack": p.pack,
                "version": p.version,
                "description": p.description,
                "entities": list(p.entities),
            }
            for p in available_packs().values()
        ]

    @app.get("/v1/packs/{name}", dependencies=auth)
    def show_pack(name: str) -> dict[str, Any]:
        try:
            return get_pack(name).model_dump()
        except PackError as e:
            raise HTTPException(404, str(e)) from e

    # -- jobs -------------------------------------------------------------------
    @app.get("/v1/jobs", dependencies=auth)
    def list_jobs() -> list[str]:
        return sorted(p.stem for p in (store.home / "jobs").glob("*.yaml"))

    @app.put("/v1/jobs/{name}", dependencies=auth)
    async def save_job(name: str, request: Request) -> dict[str, Any]:
        path = store.job_path(name)
        text = (await request.body()).decode("utf-8")
        try:
            job = parse_job(text, store.data, local_root=store.data, name=name)
        except (ValidationError, ValueError) as e:  # UnsafePath and PackError included
            raise HTTPException(422, str(e)) from e
        if job.job != name:
            raise HTTPException(422, f"the file says job: {job.job}, but the URL says {name}")
        path.write_text(text, encoding="utf-8")
        return {
            "job": name,
            "source": job.source.type,
            "pack": job.pack,
            "entity": job.entity,
            "fields": job.output_fields,
        }

    @app.get("/v1/jobs/{name}", dependencies=auth)
    def get_job(name: str) -> PlainTextResponse:
        path = store.job_path(name)
        if not path.exists():
            raise HTTPException(404, f"job '{name}' not found")
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/yaml")

    @app.delete("/v1/jobs/{name}", dependencies=auth, status_code=204)
    def delete_job(name: str) -> None:
        path = store.job_path(name)
        if not path.exists():
            raise HTTPException(404, f"job '{name}' not found")
        path.unlink()

    # -- runs -------------------------------------------------------------------
    def execute(state: RunState, limit: int | None) -> None:
        with store.slots:
            state.status = "running"
            try:
                job = store.load_job(state.job)
                result = run_job(
                    job, out_root=store.home / "output", limit=limit, run_id=state.run_id
                )
                state.out_dir = result.out_dir
                state.status = "passed" if result.manifest.status == "PASSED" else "review"
            except Exception as e:  # reported on the run, never crashes the server
                log.exception("run %s failed", state.run_id)
                state.status, state.error = "failed", f"{type(e).__name__}: {e}"

    def describe(state: RunState) -> dict[str, Any]:
        out: dict[str, Any] = {
            "run_id": state.run_id,
            "job": state.job,
            "status": state.status,
            "created_at": state.created_at,
            "error": state.error,
            "links": {"self": f"/v1/runs/{state.run_id}"},
        }
        if state.out_dir and (state.out_dir / "manifest.json").exists():
            out["manifest"] = json.loads((state.out_dir / "manifest.json").read_text())
            out["links"]["report"] = f"/v1/runs/{state.run_id}/report"
            out["links"]["data"] = f"/v1/runs/{state.run_id}/data"
        return out

    @app.post("/v1/jobs/{name}/runs", dependencies=auth, status_code=202)
    def start_run(name: str, limit: int | None = None, wait: bool = False) -> dict[str, Any]:
        try:
            store.load_job(name)  # fail fast on a missing or broken job
        except (ValidationError, ValueError) as e:
            raise HTTPException(422, str(e)) from e
        state = RunState(run_id=new_run_id(sample=bool(limit)), job=name)
        with store.lock:
            store.runs[state.run_id] = state
        if wait:
            execute(state, limit)
        else:
            threading.Thread(target=execute, args=(state, limit), daemon=True).start()
        return describe(state)

    @app.get("/v1/runs", dependencies=auth)
    def list_runs(job: str | None = None) -> list[dict[str, Any]]:
        seen = {s.run_id: describe(s) for s in store.runs.values()}
        for m in (store.home / "output").glob("*/*/manifest.json"):
            rid = m.parent.name
            if rid not in seen:
                data = json.loads(m.read_text())
                seen[rid] = {
                    "run_id": rid,
                    "job": data["job"],
                    "status": "passed" if data["status"] == "PASSED" else "review",
                    "created_at": data["started_at"],
                    "error": None,
                    "links": {"self": f"/v1/runs/{rid}"},
                }
        runs = [r for r in seen.values() if job is None or r["job"] == job]
        return sorted(runs, key=lambda r: r["run_id"], reverse=True)

    @app.get("/v1/runs/{run_id}", dependencies=auth)
    def get_run(run_id: str) -> dict[str, Any]:
        state = store.runs.get(run_id)
        if state is None:
            folder = store.run_dir(run_id)
            if folder is None:
                raise HTTPException(404, "run not found")
            data = json.loads((folder / "manifest.json").read_text())
            state = RunState(
                run_id=run_id,
                job=data["job"],
                out_dir=folder,
                status="passed" if data["status"] == "PASSED" else "review",
            )
        return describe(state)

    def finished_dir(run_id: str) -> Path:
        folder = store.run_dir(run_id)
        if folder is None:
            raise HTTPException(404, "run not found or not finished")
        return folder

    @app.get("/v1/runs/{run_id}/report", dependencies=auth)
    def get_report(run_id: str) -> HTMLResponse:
        path = finished_dir(run_id) / "proof-report.html"
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @app.get("/v1/runs/{run_id}/data", dependencies=auth)
    def get_data(run_id: str, format: str = "json", rejected: bool = False) -> FileResponse:
        names = {"json": "data.json", "csv": "data.csv", "xlsx": "data.xlsx"}
        if format not in names:
            raise HTTPException(400, "format must be json, csv or xlsx")
        name = "rejected.csv" if rejected else names[format]
        path = finished_dir(run_id) / name
        if not path.exists():
            raise HTTPException(
                404, f"{name} was not produced by this run (check the job's output.formats)"
            )
        return FileResponse(path, filename=f"{run_id}-{name}")

    return app


def main(host: str = "127.0.0.1", port: int = 8000, home: str | None = None) -> None:
    import uvicorn  # optional extra

    uvicorn.run(create_app(Path(home) if home else None), host=host, port=port)


__all__ = ["UnsafePath", "create_app", "main"]
