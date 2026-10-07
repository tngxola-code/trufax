"""JSON APIs and JSON files: a list of records, paged by page number, offset, cursor or
next link.

Fields address values inside each record with dotted paths (``price.amount``,
``images.0.url``). Tokens and keys go in headers or params as ``${env:NAME}`` so they
never sit in job files, and are redacted from everything the run writes.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from ..config import JsonSettings
from ..fetch import Fetched, FetchError, expand_env, is_local
from ..records import Record
from .base import Adapter

MISSING = object()


def get_path(data: Any, path: str) -> Any:
    """Follow a dotted path through dicts and lists; MISSING when a step is absent."""
    if path in ("", "."):
        return data
    current = data
    for step in path.split("."):
        if isinstance(current, dict) and step in current:
            current = current[step]
        elif isinstance(current, list) and step.lstrip("-").isdigit():
            idx = int(step)
            if -len(current) <= idx < len(current):
                current = current[idx]
            else:
                return MISSING
        else:
            return MISSING
    return current


def as_text(value: Any) -> str | None:
    """Scalar values pass through as text; lists of scalars are joined; objects become
    compact JSON so nothing is silently dropped."""
    if value is MISSING or value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, list) and all(isinstance(v, (str, int, float)) for v in value):
        return "; ".join(str(v) for v in value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def with_params(url: str, params: dict[str, Any]) -> str:
    if not params or is_local(url):
        return url
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({k: str(v) for k, v in params.items()})
    return urlunparse(parts._replace(query=urlencode(query)))


class JsonAdapter(Adapter):
    def extract(self) -> list[Record]:
        cfg = self.job.source.json_api
        assert cfg is not None  # set by SourceConfig for json sources
        params = {k: expand_env(str(v), self.fetcher.secrets) for k, v in cfg.params.items()}
        records: list[Record] = []
        for start in self.job.source.start_urls:
            self._crawl(start, cfg, params, records)
            if self.full(records):
                break
        return records

    def _crawl(self, start: str, cfg: JsonSettings, params: dict, records: list[Record]) -> None:
        pg = cfg.pagination
        specs = self.job.fields
        paths = {n: str(s.src if s.src is not None else n) for n, s in specs.items() if s.extracted}
        url: str | None = start
        cursor: str | None = None
        for page_no in range(1, pg.max_pages + 1):
            if url is None or self.full(records):
                return
            query = dict(params)
            if pg.type == "page":
                query[pg.param] = (1 if pg.start is None else pg.start) + page_no - 1
            elif pg.type == "offset":
                assert pg.size is not None
                query[pg.param] = (pg.start or 0) + (page_no - 1) * pg.size
            elif pg.type == "cursor" and cursor:
                query[pg.param] = cursor
            if pg.size_param and pg.size:
                query[pg.size_param] = pg.size
            try:
                doc = self.fetcher.get(with_params(url, query))
                body = json.loads(doc.content)
            except FetchError as e:
                self.warnings.append(str(e))
                return
            except ValueError:
                self.warnings.append(f"page {page_no}: response is not valid JSON")
                return

            items = get_path(body, cfg.records)
            if items is MISSING:
                self.warnings.append(f"page {page_no}: no '{cfg.records}' in the response")
                return
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list) or not items:
                return  # an empty page ends the crawl
            for i, item in enumerate(items, start=1):
                if self.full(records):
                    return
                records.append(self._record(item, paths, doc, f"page {page_no} record {i}"))

            if pg.type == "none":
                return
            if pg.type == "cursor":
                nxt = as_text(get_path(body, pg.cursor_path or ""))
                if not nxt:
                    return
                cursor = nxt
            elif pg.type == "next_url":
                link = as_text(get_path(body, pg.next_url_path or ""))
                url = urljoin(doc.url, link) if link else None
            elif pg.size and len(items) < pg.size:
                return  # a short page is the last page
        self.warnings.append(f"stopped after max_pages={pg.max_pages}; more pages may exist")

    def _record(self, item: Any, paths: dict[str, str], doc: Fetched, locator: str) -> Record:
        if not isinstance(item, dict):
            item = {"value": item}
        raw = {name: as_text(get_path(item, path)) for name, path in paths.items()}
        context = json.dumps(item, ensure_ascii=False) if self.ai else None
        return self.record(raw, self.job.fields, doc, locator, context=context)
