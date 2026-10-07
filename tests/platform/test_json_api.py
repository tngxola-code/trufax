"""JSON API source against a local fake API: every pagination style, auth from the
environment, and secrets kept out of everything the run writes."""

import json
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

import pytest

from trufax.adapters.json_api import MISSING, as_text, get_path, with_params
from trufax.config import parse_job
from trufax.fetch import FetchError
from trufax.runner import run_job

ITEMS = [
    {"id": f"P-{i}", "title": f"Item {i}", "price": {"amount": str(10 * i)}} for i in range(1, 6)
]


class FakeApi(BaseHTTPRequestHandler):
    seen: ClassVar[list[str]] = []

    def log_message(self, *a):
        pass

    def send(self, code: int, body: object) -> None:
        out = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        FakeApi.seen.append(self.path)
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/robots.txt":
            return self.send(404, {})
        if url.path == "/secure" and self.headers.get("Authorization") != "Bearer s3cret":
            return self.send(401, {"error": "unauthorized"})
        if url.path == "/keyed" and q.get("api_key") != "k3y":
            return self.send(403, {"error": "bad key"})
        if url.path in ("/paged", "/secure", "/keyed"):
            page, size = int(q.get("page", 1)), int(q.get("per_page", 2))
            return self.send(200, {"data": ITEMS[(page - 1) * size : page * size]})
        if url.path == "/offset":
            off, size = int(q["offset"]), int(q["limit"])
            return self.send(200, ITEMS[off : off + size])
        if url.path == "/cursor":
            pos = int(q.get("cursor", "0"))
            nxt = str(pos + 2) if pos + 2 < len(ITEMS) else None
            return self.send(200, {"items": ITEMS[pos : pos + 2], "meta": {"next": nxt}})
        if url.path == "/linked":
            n = int(q.get("n", 1))
            nxt = f"/linked?n={n + 1}" if n < 3 else None
            return self.send(200, {"items": ITEMS[(n - 1) * 2 : n * 2], "next": nxt})
        return self.send(404, {})


@pytest.fixture(scope="module")
def api():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def job(tmp_path, url: str, json_block: str, fetch: str = "") -> object:
    return parse_job(
        f"""
job: api-test
source:
  type: json
  start_urls: ["{url}"]
  fetch: {{ rate_limit: 100, cache: false {fetch} }}
  json:
{json_block}
  fields:
    sku: id
    name: title
    price: {{ src: price.amount, type: decimal }}
validation: {{ key: [sku] }}
output: {{ formats: [csv, json] }}
""",
        tmp_path,
    )


def run(tmp_path, j):
    return run_job(j, out_root=tmp_path / "out")


def skus(res) -> list[str]:
    return [r.data["sku"] for r in res.outcome.valid]


def test_page_pagination_stops_on_short_page(tmp_path, api):
    block = "    records: data\n    pagination: {type: page, size_param: per_page, size: 2}"
    res = run(tmp_path, job(tmp_path, f"{api}/paged", block))
    assert skus(res) == ["P-1", "P-2", "P-3", "P-4", "P-5"]
    assert res.outcome.valid[2].provenance.locator == "page 2 record 1"
    assert res.outcome.valid[0].data["price"] == Decimal(10)
    assert not any("page=4" in p for p in FakeApi.seen)  # page 3 had one item: stop


def test_offset_pagination(tmp_path, api):
    block = "    pagination: {type: offset, param: offset, size_param: limit, size: 2}"
    assert skus(run(tmp_path, job(tmp_path, f"{api}/offset", block)))[-1] == "P-5"


def test_cursor_pagination(tmp_path, api):
    block = (
        "    records: items\n    pagination: {type: cursor, param: cursor, cursor_path: meta.next}"
    )
    assert len(skus(run(tmp_path, job(tmp_path, f"{api}/cursor", block)))) == 5


def test_next_url_pagination(tmp_path, api):
    block = "    records: items\n    pagination: {type: next_url, next_url_path: next}"
    assert len(skus(run(tmp_path, job(tmp_path, f"{api}/linked", block)))) == 5


def test_sample_limit_stops_paging(tmp_path, api):
    block = "    records: data\n    pagination: {type: page, size_param: per_page, size: 2}"
    res = run_job(job(tmp_path, f"{api}/paged", block), out_root=tmp_path / "o", limit=3)
    assert len(res.outcome.records) == 3


def test_bearer_token_from_environment(tmp_path, api, monkeypatch):
    block = "    records: data\n    pagination: {type: page, size_param: per_page, size: 5}"
    fetch = ', headers: {Authorization: "Bearer ${env:FAKE_TOKEN}"}'
    j = job(tmp_path, f"{api}/secure", block, fetch)
    monkeypatch.delenv("FAKE_TOKEN", raising=False)
    with pytest.raises(FetchError, match="FAKE_TOKEN is not set"):
        run(tmp_path, j)
    monkeypatch.setenv("FAKE_TOKEN", "wrong")
    denied = run(tmp_path, j)
    assert denied.manifest.status == "REVIEW" and "401" in denied.manifest.warnings[0]
    monkeypatch.setenv("FAKE_TOKEN", "s3cret")
    assert len(skus(run(tmp_path, j))) == 5


def test_query_key_is_redacted_from_outputs(tmp_path, api, monkeypatch):
    monkeypatch.setenv("FAKE_KEY", "k3y")
    block = (
        "    records: data\n"
        '    params: {api_key: "${env:FAKE_KEY}"}\n'
        "    pagination: {type: page, size_param: per_page, size: 5}"
    )
    res = run(tmp_path, job(tmp_path, f"{api}/keyed", block))
    assert len(res.outcome.valid) == 5
    assert "api_key=***" in res.outcome.valid[0].provenance.source_url
    for f in res.out_dir.iterdir():
        assert "k3y" not in f.read_text(encoding="utf-8", errors="ignore"), f.name


def test_missing_records_path_is_a_warning(tmp_path, api):
    res = run(tmp_path, job(tmp_path, f"{api}/paged", "    records: nope"))
    assert res.manifest.status == "REVIEW"
    assert "no 'nope' in the response" in res.manifest.warnings[0]


def test_paths_and_values():
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}, "t": ["x", "y"], "f": False}
    assert get_path(data, "a.b.1.c") == 2
    assert get_path(data, "a.b.-1.c") == 2
    assert get_path(data, "a.z") is MISSING
    assert get_path(data, "") is data
    assert as_text(get_path(data, "t")) == "x; y"
    assert as_text(get_path(data, "f")) == "false"
    assert as_text(get_path(data, "a.b.0")) == '{"c": 1}'
    assert as_text(MISSING) is None
    assert with_params("https://x.io/a?b=1", {"c": 2}) == "https://x.io/a?b=1&c=2"
    assert with_params("/local/file.json", {"c": 2}) == "/local/file.json"


def test_offline_example(examples, tmp_path):
    from trufax.config import load_job

    res = run_job(load_job(examples / "api" / "products.yaml"), out_root=tmp_path)
    assert res.outcome.counts == {"extracted": 4, "valid": 3, "invalid": 1, "duplicate": 0}
    gloves = next(r for r in res.outcome.valid if r.data["sku"] == "PPE-0410")
    assert gloves.data["in_stock"] is False and gloves.data["brand"] is None
    assert gloves.provenance.locator == "page 2 record 1"
    bad = res.outcome.rejected[0]
    assert "rating: 7.5 above maximum" in bad.errors[0]
