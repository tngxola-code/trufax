import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from trufax.cli import main
from trufax.config import load_job
from trufax.scaffold import export_client_repo, new_job


@pytest.mark.parametrize("kind", ["html", "pdf", "xml", "json", "spreadsheet"])
def test_templates_are_valid(tmp_path, kind):
    path = new_job(f"my-{kind}", kind, tmp_path)
    assert load_job(path).source.type == kind


def test_check_command(examples, capsys):
    assert main(["check", str(examples / "budget" / "budget.yaml")]) == 0
    assert "OK" in capsys.readouterr().out


def test_bad_job_file_exits_cleanly(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("job: Bad Name\nsource: {type: html, start_urls: [x], fields: {}}\n")
    with pytest.raises(SystemExit) as e:
        main(["check", str(bad)])
    assert e.value.code == 2


def test_client_repo_runs_on_its_own(examples, tmp_path):
    out = export_client_repo(examples / "budget" / "budget.yaml", tmp_path / "client")
    assert (out / "jobs" / "data" / "general-fund-revenue.pdf").exists()
    job = yaml.safe_load((out / "jobs" / "example-budget-revenue.yaml").read_text())
    assert job["source"]["start_urls"] == ["data/general-fund-revenue.pdf"]
    assert (out / ".git").exists() and "## Run it" in (out / "README.md").read_text()

    # run the exported copy of the engine, not the installed one
    env = {**os.environ, "PYTHONPATH": str(out / "src")}
    code = (
        "import sys; from trufax.cli import main; import trufax; "
        f"assert trufax.__file__.startswith({str(out)!r}); "
        "sys.exit(main(['run', 'jobs/example-budget-revenue.yaml']))"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=out, env=env, capture_output=True, text=True, check=False
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "status PASSED" in r.stdout
    assert any(Path(out / "output" / "example-budget-revenue").iterdir())
