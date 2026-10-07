"""Fetching: polite HTTP (rate limit, retries, robots.txt, cache), local files, optional browser.

Every fetch is recorded with its SHA-256 so each record can be traced to the exact bytes
it came from.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from urllib.parse import urlparse
from urllib.request import url2pathname
from urllib.robotparser import RobotFileParser

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .config import FetchSettings

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    pass


ENV_REF = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


_ENV_PREFIX: str | None = None


def restrict_env(prefix: str | None) -> None:
    """Only allow ``${env:...}`` names with this prefix. The HTTP API sets this so a job
    submitted over the network cannot read the server's other environment variables
    (its own API key, cloud credentials) and send them to a site it chooses."""
    global _ENV_PREFIX
    _ENV_PREFIX = prefix


def expand_env(value: str, secrets: set[str] | None = None) -> str:
    """Replace ``${env:NAME}`` with the environment variable's value, so tokens and keys
    never sit in job files. Values substituted this way are recorded as secrets and
    redacted from URLs and messages written to outputs."""

    def substitute(m: re.Match[str]) -> str:
        name = m.group(1)
        if _ENV_PREFIX and not name.startswith(_ENV_PREFIX):
            raise FetchError(
                f"${{env:{name}}} is not allowed here; use a name starting with {_ENV_PREFIX}"
            )
        val = os.environ.get(name)
        if val is None:
            raise FetchError(f"environment variable {name} is not set")
        if secrets is not None and val:
            secrets.add(val)
        return val

    return ENV_REF.sub(substitute, value)


class BlockedByRobots(FetchError):
    pass


@dataclass
class Fetched:
    url: str
    final_url: str
    status: int
    content: bytes
    content_type: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    from_cache: bool = False

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def is_local(url: str) -> bool:
    scheme = urlparse(url).scheme
    return scheme in ("", "file") or (len(scheme) == 1)  # "C:" style Windows paths


def local_path(url: str) -> Path:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return Path(url2pathname(parsed.path))
    return Path(url)


class _RateLimiter:
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, _RetryStatus)


class _RetryStatus(FetchError):
    pass


class Fetcher:
    """HTTP fetcher with politeness built in. Use as a context manager."""

    def __init__(self, settings: FetchSettings, cache_dir: Path | None = None):
        self.s = settings
        self.cache_dir = cache_dir if settings.cache else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._limiter = _RateLimiter(settings.rate_limit)
        self._robots: dict[str, RobotFileParser | None] = {}
        self._client: httpx.Client | None = None
        self.log: list[Fetched] = []
        self.secrets: set[str] = set()
        self.headers = {k: expand_env(v, self.secrets) for k, v in settings.headers.items()}
        self.proxy = expand_env(settings.proxy, self.secrets) if settings.proxy else None

    def redact(self, text: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, "***")
        return text

    def __enter__(self) -> Self:
        self._client = httpx.Client(
            timeout=self.s.timeout,
            follow_redirects=True,
            headers={"User-Agent": self.s.user_agent, **self.headers},
            proxy=self.proxy,
        )
        return self

    def __exit__(self, *exc) -> None:
        if self._client:
            self._client.close()

    # -- public -----------------------------------------------------------
    def get(self, url: str) -> Fetched:
        try:
            result = self._read_local(url) if is_local(url) else self._get_remote(url)
        except FetchError as e:
            raise type(e)(self.redact(str(e))) from None
        result.url, result.final_url = self.redact(result.url), self.redact(result.final_url)
        self.log.append(result)
        return result

    # -- internals --------------------------------------------------------
    def _read_local(self, url: str) -> Fetched:
        path = local_path(url)
        if not path.is_file():
            raise FetchError(f"file not found: {path}")
        uri = path.resolve().as_uri()
        return Fetched(url=uri, final_url=uri, status=200, content=path.read_bytes())

    def _cache_file(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / hashlib.sha256(url.encode()).hexdigest()

    def _get_remote(self, url: str) -> Fetched:
        if self.s.respect_robots and not self._allowed(url):
            raise BlockedByRobots(f"robots.txt disallows {url}")
        cached = self._cache_file(url)
        if cached and cached.exists():
            return Fetched(
                url=url, final_url=url, status=200, content=cached.read_bytes(), from_cache=True
            )

        client = self._client
        assert client is not None, "use the fetcher as a context manager"

        @retry(
            retry=retry_if_exception(_retryable),
            stop=stop_after_attempt(self.s.retries + 1),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            reraise=True,
        )
        def attempt() -> httpx.Response:
            self._limiter.wait()
            resp = client.get(url)
            if resp.status_code in RETRY_STATUS:
                raise _RetryStatus(f"HTTP {resp.status_code} for {url}")
            return resp

        try:
            resp = attempt()
        except (httpx.HTTPError, _RetryStatus) as e:
            raise FetchError(f"failed to fetch {url}: {e}") from e
        if resp.status_code >= 400:
            raise FetchError(f"HTTP {resp.status_code} for {url}")
        result = Fetched(
            url=url,
            final_url=str(resp.url),
            status=resp.status_code,
            content=resp.content,
            content_type=resp.headers.get("content-type", ""),
        )
        if cached:
            cached.write_bytes(resp.content)
        return result

    def _allowed(self, url: str) -> bool:
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            assert self._client is not None, "use the fetcher as a context manager"
            parser: RobotFileParser | None = RobotFileParser()
            try:
                resp = self._client.get(root + "/robots.txt")
                if resp.status_code >= 400:
                    parser = None  # no robots file: everything allowed
                else:
                    assert parser is not None
                    parser.parse(resp.text.splitlines())
            except httpx.HTTPError:
                parser = None
            self._robots[root] = parser
        found = self._robots[root]
        return found is None or found.can_fetch(self.s.user_agent, url)


class BrowserFetcher(Fetcher):
    """Renders JavaScript-heavy pages with Playwright (pip install 'trufax[browser]')."""

    def __enter__(self) -> Self:
        super().__enter__()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover - depends on optional extra
            raise FetchError(
                "browser engine needs Playwright: pip install 'trufax[browser]' "
                "&& playwright install chromium"
            ) from e
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            proxy={"server": self.proxy} if self.proxy else None
        )
        self._page = self._browser.new_page(
            user_agent=self.s.user_agent, extra_http_headers=self.headers
        )
        return self

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._pw.stop()
        super().__exit__(*exc)

    def _get_remote(self, url: str) -> Fetched:
        if self.s.respect_robots and not self._allowed(url):
            raise BlockedByRobots(f"robots.txt disallows {url}")
        self._limiter.wait()
        resp = self._page.goto(url, timeout=self.s.timeout * 1000, wait_until="networkidle")
        if self.s.wait_for:
            self._page.wait_for_selector(self.s.wait_for, timeout=self.s.timeout * 1000)
        status = resp.status if resp else 0
        if status >= 400:
            raise FetchError(f"HTTP {status} for {url}")
        return Fetched(
            url=url,
            final_url=self._page.url,
            status=status,
            content=self._page.content().encode("utf-8"),
            content_type="text/html",
        )


def make_fetcher(settings: FetchSettings, cache_dir: Path | None = None) -> Fetcher:
    cls = BrowserFetcher if settings.engine == "browser" else Fetcher
    return cls(settings, cache_dir)
