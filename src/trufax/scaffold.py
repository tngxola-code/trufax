"""New job files, and standalone client repositories.

Every delivered engagement becomes a repository the client owns outright: the engine,
their job file and any local source files, with instructions to run it themselves.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import yaml

from . import __version__
from .config import load_job
from .fetch import is_local, local_path


def new_job(name: str, kind: str, dest_dir: Path) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
        raise ValueError("job name: lowercase letters, digits, '-' and '_' only")
    template = resources.files("trufax").joinpath(f"templates/{kind}.yaml").read_text()
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{name}.yaml"
    if path.exists():
        raise FileExistsError(path)
    path.write_text(template.replace("__JOB__", name), encoding="utf-8")
    return path


CLIENT_README = """# {title}

{description}

This repository is yours. It contains everything needed to produce the dataset again,
on your own machine, without any dependency on the person who built it.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
trufax run jobs/{job}.yaml
```

Each run writes a timestamped folder under `output/{job}/` containing:

| File | What it is |
|---|---|
| `data.csv`, `data.xlsx` | The validated records, each with its source URL and location |
| `rejected.csv` | Records that failed validation, with the reason for each |
| `proof-report.html` | One-page summary: counts, checks passed, completeness, sources |
| `manifest.json` | Machine-readable run record, including SHA-256 of every source |

Try a quick sample first with `trufax sample jobs/{job}.yaml --limit 20`.

## Change what is collected

Everything is in `jobs/{job}.yaml`: sources, fields, cleaning rules and validation.
If the website changes its layout, update the selectors there; no code changes needed.
Run `trufax check jobs/{job}.yaml` to validate the file before running.

## Schedule it

Add a scheduled GitHub Actions workflow, a cron entry, or any task scheduler that runs
`trufax run jobs/{job}.yaml`.

Engine: trufax {version}
"""

CI = """name: tests
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {{ python-version: "3.12" }}
      - run: pip install -e .
      - run: trufax check jobs/{job}.yaml
"""


def export_client_repo(
    job_path: Path, out: Path, title: str | None = None, init_git: bool = True
) -> Path:
    job = load_job(job_path)  # validates before we copy anything
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty")
    pkg = Path(str(resources.files("trufax")))
    shutil.copytree(
        pkg, out / "src" / "trufax", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )

    raw = yaml.safe_load(job_path.read_text(encoding="utf-8"))
    jobs_dir = out / "jobs"
    (jobs_dir / "data").mkdir(parents=True)
    rewritten = []
    for url in job.source.start_urls:
        if is_local(url):
            src = local_path(url)
            shutil.copy2(src, jobs_dir / "data" / src.name)
            rewritten.append(f"data/{src.name}")
        else:
            rewritten.append(url)
    raw["source"]["start_urls"] = rewritten
    (jobs_dir / f"{job.job}.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    if not any((jobs_dir / "data").iterdir()):
        (jobs_dir / "data").rmdir()

    (out / "pyproject.toml").write_text(_minimal_pyproject(), encoding="utf-8")

    title = title or (f"{job.client}: {job.job}" if job.client else job.job)
    (out / "README.md").write_text(
        CLIENT_README.format(
            title=title, description=job.description or "", job=job.job, version=__version__
        ),
        encoding="utf-8",
    )
    (out / ".gitignore").write_text("output/\n.venv/\n__pycache__/\n*.egg-info/\n")
    (out / ".github" / "workflows").mkdir(parents=True)
    (out / ".github" / "workflows" / "check.yml").write_text(CI.format(job=job.job))

    if init_git and shutil.which("git"):

        def git(*a):
            subprocess.run(["git", *a], cwd=out, check=True, capture_output=True)

        git("init", "-q", "-b", "main")
        git("add", "-A")
        git(
            "-c",
            "user.name=trufax",
            "-c",
            "user.email=trufax@localhost",
            "commit",
            "-q",
            "-m",
            f"Initial delivery: {job.job}",
        )
    return out


def _minimal_pyproject() -> str:
    return f"""[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "trufax"
version = "{__version__}"
requires-python = ">=3.11"
dependencies = ["httpx>=0.25", "parsel>=1.8", "lxml>=4.9", "pdfplumber>=0.10",
                "pydantic>=2.0", "PyYAML>=6.0", "tenacity>=8.2", "openpyxl>=3.1"]

[project.optional-dependencies]
browser = ["playwright>=1.40"]
sheets = ["gspread>=6.0"]

[project.scripts]
trufax = "trufax.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
trufax = ["templates/*", "domain_packs/*"]
"""
