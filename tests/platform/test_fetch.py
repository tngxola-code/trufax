import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from trufax.config import FetchSettings
from trufax.fetch import BlockedByRobots, Fetcher, FetchError


class Handler(BaseHTTPRequestHandler):
    hits: ClassVar[dict[str, int]] = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        n = Handler.hits[self.path] = Handler.hits.get(self.path, 0) + 1
        if self.path == "/robots.txt":
            body, code = b"User-agent: *\nDisallow: /private\n", 200
        elif self.path == "/flaky" and n < 3:
            body, code = b"busy", 503
        elif self.path in ("/flaky", "/ok"):
            body, code = b"<p>hello</p>", 200
        else:
            body, code = b"missing", 404
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def settings(**kw):
    return FetchSettings(rate_limit=50, cache=False, **kw)


def test_retries_then_succeeds(server, monkeypatch):
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda s: None)
    with Fetcher(settings(retries=3)) as f:
        r = f.get(server + "/flaky")
    assert r.text == "<p>hello</p>" and Handler.hits["/flaky"] == 3


def test_robots_respected(server):
    with Fetcher(settings()) as f, pytest.raises(BlockedByRobots):
        f.get(server + "/private/page")


def test_404_is_an_error(server):
    with Fetcher(settings()) as f, pytest.raises(FetchError):
        f.get(server + "/nope")


def test_cache(server, tmp_path):
    s = FetchSettings(rate_limit=50, cache=True)
    with Fetcher(s, cache_dir=tmp_path) as f:
        f.get(server + "/ok")
        second = f.get(server + "/ok")
    assert second.from_cache and Handler.hits["/ok"] == 1


def test_local_file(tmp_path):
    p = tmp_path / "a.html"
    p.write_text("x")
    with Fetcher(settings()) as f:
        r = f.get(str(p))
    assert r.content == b"x" and r.final_url.startswith("file://")
