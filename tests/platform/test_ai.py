"""Model extraction against a fake Ollama server: values found in the text are kept,
values the model invents are rejected with a reason."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from trufax.ai import cited
from trufax.config import parse_job
from trufax.runner import run_job

PAGE = """<html><body>
<div class="p"><h2>Drill</h2><p>Cordless drill made by Bosch, 18V.</p><span class="sku">D-1</span>
<span class="price">R 999</span></div>
<div class="p"><h2>Saw</h2><p>Hand saw, 500mm blade.</p><span class="sku">S-2</span>
<span class="price">R 199</span></div>
</body></html>"""


class FakeOllama(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict]] = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.requests.append(body)
        text = body["messages"][-1]["content"]
        # finds the real brand when present, invents one when not
        brand = "Bosch" if "Bosch" in text else "Makita"
        out = json.dumps({"message": {"content": json.dumps({"brand": brand})}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture(scope="module")
def ollama():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def make_job(tmp_path, base_url):
    page = tmp_path / "shop.html"
    page.write_text(PAGE)
    return parse_job(
        f"""
job: ai-test
pack: e-commerce
entity: Product
ai: {{ base_url: "{base_url}", model: test-model }}
source:
  type: html
  start_urls: [{page}]
  html: {{ item_selector: "div.p" }}
  fields:
    name: "h2::text"
    sku: "span.sku::text"
    price: {{ src: "span.price::text", transforms: [strip_currency] }}
    brand: {{ llm: "the manufacturer's brand name" }}
""",
        tmp_path,
    )


def test_model_values_are_kept_only_when_cited(tmp_path, ollama):
    res = run_job(make_job(tmp_path, ollama), out_root=tmp_path / "out")
    o = res.outcome
    drill = next(r for r in o.records if r.data["sku"] == "D-1")
    saw = next(r for r in o.records if r.data["sku"] == "S-2")
    assert drill.status == "VALID" and drill.data["brand"] == "Bosch"
    assert drill.provenance.ai_fields == "brand (ollama:test-model)"
    assert saw.status == "INVALID"
    assert "brand: model value 'Makita' not found in the source text" in saw.errors

    sent = FakeOllama.requests[-1]
    assert sent["model"] == "test-model" and sent["options"]["temperature"] == 0
    assert sent["format"]["properties"]["brand"]["type"] == ["string", "null"]
    assert "_ai_fields" in (res.out_dir / "data.csv").read_text(encoding="utf-8-sig")


def test_model_unreachable_is_reported_not_crashed(tmp_path):
    res = run_job(make_job(tmp_path, "http://127.0.0.1:9"), out_root=tmp_path / "out")
    assert res.outcome.counts["invalid"] == 2
    assert any("model call" in e for r in res.outcome.records for e in r.errors)


def test_citation_ignores_case_and_spacing():
    assert cited("BOSCH  18v", "Cordless drill made by Bosch 18V.")
    assert not cited("Makita", "Cordless drill made by Bosch")
    assert not cited("", "anything")
