"""Change detection, history, scheduling and alerts, run against a real local HTTP site so
the page cache is exercised. Includes regression tests for the problems found in the
earlier recurring-runs prototype."""

import functools
import http.server
import json
import threading
from datetime import datetime
from typing import ClassVar

import pytest
import yaml

from trufax.cli import main
from trufax.config import JobConfig
from trufax.history import History
from trufax.runner import run_job
from trufax.schedule import load_scheduled, run_due

PAGE_1 = """<html><body>
<article class="p"><h3>Drill</h3><span class="sku">D-1</span><span class="price">R 1,249.00</span></article>
<article class="p"><h3>Tape</h3><span class="sku">T-2</span><span class="price">R 189.50</span></article>
<a class="next" href="page-2.html">next</a></body></html>"""
PAGE_2 = """<html><body>
<article class="p"><h3>Gloves</h3><span class="sku">G-3</span><span class="price">R 64.99</span></article>
</body></html>"""


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "page-1.html").write_text(PAGE_1)
    (root / "page-2.html").write_text(PAGE_2)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None  # type: ignore[attr-defined]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True).start()
    yield root, f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def make_job(base: str, **extra) -> JobConfig:
    data = {
        "job": "shop",
        "source": {
            "type": "html",
            "start_urls": [f"{base}/page-1.html"],
            "fetch": {"rate_limit": 100, "respect_robots": False},
            "html": {"item_selector": "article.p", "next_page": "a.next::attr(href)"},
            "fields": {
                "name": "h3::text",
                "sku": "span.sku::text",
                "price": {
                    "src": "span.price::text",
                    "type": "decimal",
                    "transforms": ["strip_currency"],
                },
            },
        },
        "validation": {"key": ["sku"]},
        "output": {"formats": ["csv"]},
    }
    data.update(extra)
    return JobConfig.model_validate(data)


def test_first_run_is_baseline_then_changes_are_found(site, tmp_path):
    root, base = site
    out = tmp_path / "out"
    first = run_job(make_job(base), out_root=out)
    assert first.changes.baseline_run is None
    assert first.manifest.changes["since_run"] is None
    assert not (first.out_dir / "changes.csv").exists()

    (root / "page-1.html").write_text(PAGE_1.replace("R 1,249.00", "R 999.00"))
    (root / "page-2.html").write_text(PAGE_2.replace("Gloves", "Gloves Pro").replace("G-3", "G-4"))
    second = run_job(make_job(base), out_root=out)
    cs = second.changes
    assert cs.baseline_run == first.manifest.run_id
    assert [c["fields"] for c in cs.changed] == [["price"]]
    assert cs.changed[0]["before"] == {"price": 1249} and cs.changed[0]["after"] == {"price": 999}
    assert [c["values"]["sku"] for c in cs.new] == ["G-4"]
    assert [c["before"]["sku"] for c in cs.removed] == ["G-3"]
    assert cs.unchanged == 1

    csv = (second.out_dir / "changes.csv").read_text(encoding="utf-8-sig").splitlines()
    assert csv[0].startswith("_change,_changed_fields,_previous_values,name,sku,price")
    assert "changed,price,price=1249,Drill,D-1,999" in csv[1]
    html = second.report.read_text()
    assert "Changes since last run" in html and "1249 &rarr; 999" in html


def test_regression_cache_never_hides_changes_on_tracked_jobs(site, tmp_path):
    """Prototype bug: cached pages never expired, so a recurring run saw no changes."""
    root, base = site
    out = tmp_path / "out"
    run_job(make_job(base), out_root=out)
    (root / "page-1.html").write_text(PAGE_1.replace("R 189.50", "R 199.00"))
    second = run_job(make_job(base), out_root=out)
    assert len(second.changes.changed) == 1
    assert not any(s["from_cache"] for s in second.manifest.sources)


def test_untracked_jobs_still_use_the_cache(site, tmp_path):
    _, base = site
    out = tmp_path / "out"
    job = make_job(base, changes={"enabled": False})
    run_job(job, out_root=out)
    again = run_job(job, out_root=out)
    assert all(s["from_cache"] for s in again.manifest.sources)


def test_explicit_cache_ttl_is_respected(site, tmp_path):
    _, base = site
    src = make_job(base).source.model_dump()
    src["fetch"]["cache_ttl"] = 3600
    out = tmp_path / "out"
    run_job(make_job(base, source=src), out_root=out)
    again = run_job(make_job(base, source=src), out_root=out)
    assert all(s["from_cache"] for s in again.manifest.sources)


def test_regression_partial_run_reports_no_removals_and_is_not_a_baseline(site, tmp_path):
    """Prototype bug: a page that failed made its records look removed, then new."""
    root, base = site
    out = tmp_path / "out"
    first = run_job(make_job(base), out_root=out)
    saved = (root / "page-2.html").read_text()
    (root / "page-2.html").unlink()

    partial = run_job(make_job(base), out_root=out)
    assert partial.manifest.status == "REVIEW"
    failed = [c["name"] for c in partial.manifest.checks if not c["passed"]]
    assert failed == ["Every source read without warnings"]
    assert partial.changes.removals_checked is False and partial.changes.removed == []
    assert partial.manifest.changes["removed"] is None

    (root / "page-2.html").write_text(saved)
    healthy = run_job(make_job(base), out_root=out)
    assert healthy.changes.baseline_run == first.manifest.run_id  # partial run skipped
    assert healthy.changes.counts["new"] == 0 and healthy.changes.counts["removed"] == 0

    runs = History.at(out).runs("shop")
    assert [r["clean"] for r in runs] == [True, False, True]


def test_regression_schedule_once_respects_the_cron_expression(site, tmp_path):
    """Prototype bug: --once forgot the last run, so a daily job ran on every call."""
    _, base = site
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    job = make_job(base, schedule="0 6 * * *").model_dump(mode="json", exclude_none=True)
    job["output"]["dir"] = str(tmp_path / "out")
    (jobs / "shop.yaml").write_text(yaml.safe_dump(job))

    def tick(when: str) -> list[str]:
        entries, problems = load_scheduled(jobs)  # each cron call is a fresh process
        assert not problems
        return run_due(entries, tmp_path, now=datetime.fromisoformat(when))

    assert tick("2026-10-08T10:01:00+00:00") == ["shop"]  # first time: run, record baseline
    assert tick("2026-10-08T10:02:00+00:00") == []
    assert tick("2026-10-08T23:59:00+00:00") == []
    assert tick("2026-10-09T06:00:30+00:00") == ["shop"]  # next scheduled time
    assert tick("2026-10-09T06:01:00+00:00") == []


def test_invalid_schedule_is_rejected(site):
    _, base = site
    with pytest.raises(ValueError, match="not a valid cron expression"):
        make_job(base, schedule="every day")


def test_no_key_means_no_change_detection(site, tmp_path):
    _, base = site
    res = run_job(make_job(base, validation={}), out_root=tmp_path / "out")
    assert res.changes is None
    assert any("skipped: records have no key" in c["detail"] for c in res.manifest.checks)


def test_sample_runs_do_not_touch_the_baseline(site, tmp_path):
    _, base = site
    out = tmp_path / "out"
    run_job(make_job(base), out_root=out, limit=1)
    full = run_job(make_job(base), out_root=out)
    assert full.changes.baseline_run is None


class Hook(http.server.BaseHTTPRequestHandler):
    received: ClassVar[list[dict]] = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        Hook.received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()


@pytest.fixture
def webhook(monkeypatch):
    Hook.received.clear()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True).start()
    monkeypatch.setenv("SHOP_WEBHOOK", f"http://127.0.0.1:{srv.server_port}/hook")
    yield Hook.received
    srv.shutdown()


def test_alerts_for_changes_and_review(site, tmp_path, webhook):
    root, base = site
    out = tmp_path / "out"
    alerts = {"webhook_url_env": "SHOP_WEBHOOK"}
    first = run_job(make_job(base, alerts=alerts), out_root=out)
    assert first.alerts_sent == []  # a baseline is not a change

    (root / "page-1.html").write_text(PAGE_1.replace("R 1,249.00", "R 999.00"))
    second = run_job(make_job(base, alerts=alerts), out_root=out)
    assert second.alerts_sent == ["changes"]
    event = webhook[-1]
    assert event["event"] == "changes" and event["changes"]["changed"] == 1
    assert event["items"][0]["after"] == {"price": 999} and "values" not in event["items"][0]

    (root / "page-2.html").unlink()
    third = run_job(make_job(base, alerts=alerts), out_root=out)
    assert third.alerts_sent == ["review"]
    assert webhook[-1]["failed_checks"] == ["Every source read without warnings"]


def test_alert_url_must_be_an_allowed_secret_under_the_api_policy(site, tmp_path, webhook):
    from trufax.fetch import restrict_env

    root, base = site
    restrict_env("TRUFAX_SECRET_")
    out = tmp_path / "out"
    run_job(make_job(base, alerts={"webhook_url_env": "SHOP_WEBHOOK"}), out_root=out)
    (root / "page-1.html").write_text(PAGE_1.replace("R 1,249.00", "R 999.00"))
    res = run_job(make_job(base, alerts={"webhook_url_env": "SHOP_WEBHOOK"}), out_root=out)
    assert res.alerts_sent == [] and webhook == []


def test_history_and_changes_commands(site, tmp_path, capsys, monkeypatch):
    root, base = site
    job = make_job(base).model_dump(mode="json", exclude_none=True)
    job["output"]["dir"] = str(tmp_path / "out")
    path = tmp_path / "shop.yaml"
    path.write_text(yaml.safe_dump(job))
    monkeypatch.chdir(tmp_path)
    assert main(["run", str(path)]) == 0
    (root / "page-1.html").write_text(PAGE_1.replace("R 1,249.00", "R 999.00"))
    assert main(["run", str(path)]) == 0
    capsys.readouterr()

    assert main(["history", str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2 and "+0 ~1 -0" in lines[0] and "baseline" in lines[1]

    assert main(["changes", str(path)]) == 0
    out = capsys.readouterr().out
    assert "0 new, 1 changed, 0 removed" in out and "price: 1249 -> 999" in out


def test_api_history_and_changes(site, tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from trufax.api import create_app

    root, base = site
    monkeypatch.delenv("TRUFAX_API_KEY", raising=False)
    client = TestClient(create_app(tmp_path / "home"))
    job = make_job(base).model_dump(mode="json", exclude_none=True)
    assert client.put("/v1/jobs/shop", content=yaml.safe_dump(job)).status_code == 200
    assert client.get("/v1/jobs/shop/changes").status_code == 404
    client.post("/v1/jobs/shop/runs?wait=true")
    (root / "page-1.html").write_text(PAGE_1.replace("R 1,249.00", "R 999.00"))
    run = client.post("/v1/jobs/shop/runs?wait=true").json()

    body = client.get("/v1/jobs/shop/changes").json()
    assert body["run_id"] == run["run_id"] and body["summary"]["changed"] == 1
    assert body["changes"][0]["after"] == {"price": 999}
    hist = client.get("/v1/jobs/shop/history").json()
    assert len(hist) == 2 and "out_dir" not in hist[0]
    assert client.get("/v1/jobs/shop/changes?run=nope").status_code == 404
