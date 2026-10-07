"""Web pages: list pages with items, pagination and optional detail pages.

Selectors are CSS by default (parsel syntax, so ``::text`` and ``::attr(href)`` work).
Prefix with ``xpath:`` to use XPath. A selector that matches elements returns their
visible text.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from parsel import Selector, SelectorList

from ..config import FieldSpec
from ..fetch import FetchError
from ..records import Record
from .base import Adapter


def select(node: Selector, query: str, many: bool = False) -> str | None:
    found: SelectorList = (
        node.xpath(query[len("xpath:") :]) if query.startswith("xpath:") else node.css(query)
    )
    values = []
    for item in found:
        if isinstance(item.root, str):
            values.append(item.root)
        else:
            values.append(" ".join(t.strip() for t in item.xpath(".//text()").getall()))
        if not many:
            break
    values = [re.sub(r"\s+", " ", v).strip() for v in values]
    values = [v for v in values if v]
    if not values:
        return None
    return "; ".join(values) if many else values[0]


def visible_text(node: Selector) -> str:
    parts = node.xpath(".//text()[not(ancestor::script) and not(ancestor::style)]").getall()
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _raw(node: Selector, specs: dict[str, FieldSpec]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name, spec in specs.items():
        if not spec.extracted:
            continue  # a fixed value, or filled by the model from the text
        if spec.src is None or isinstance(spec.src, list):
            raise ValueError(f"field '{name}' needs a selector (src) for html sources")
        out[name] = select(node, str(spec.src), spec.many)
    return out


class HtmlAdapter(Adapter):
    def extract(self) -> list[Record]:
        cfg = self.job.source.html
        assert cfg is not None  # set by SourceConfig for html sources
        specs = self.job.fields
        detail_specs = self.job.detail_fields
        all_specs = {**specs, **detail_specs}
        records: list[Record] = []
        visited: set[str] = set()

        for start in self.job.source.start_urls:
            url: str | None = start
            page_no = 0
            while url and url not in visited and page_no < cfg.max_pages:
                if self.full(records):
                    return records
                visited.add(url)
                page_no += 1
                try:
                    page = self.fetcher.get(url)
                except FetchError as e:
                    self.warnings.append(str(e))
                    break
                doc = Selector(text=page.text)
                items = (
                    [doc]
                    if not cfg.item_selector
                    else (
                        doc.xpath(cfg.item_selector[6:])
                        if cfg.item_selector.startswith("xpath:")
                        else doc.css(cfg.item_selector)
                    )
                )
                if cfg.item_selector and not items:
                    self.warnings.append(f"no items matched '{cfg.item_selector}' on {url}")
                for i, item in enumerate(items, start=1):
                    if self.full(records):
                        return records
                    raw = _raw(item, specs)
                    for name, spec in specs.items():  # resolve list-page links now
                        if spec.type == "url" and raw.get(name):
                            raw[name] = urljoin(page.final_url, raw[name])
                    locator = f"page {page_no} item {i}" if cfg.item_selector else f"page {page_no}"
                    fetched, base = page, page.final_url
                    context = visible_text(item) if self.ai else None
                    if cfg.detail:
                        link = select(item, cfg.detail.link)
                        if link:
                            detail_url = urljoin(page.final_url, link)
                            try:
                                fetched = self.fetcher.get(detail_url)
                                detail_doc = Selector(text=fetched.text)
                                raw.update(_raw(detail_doc, detail_specs))
                                if self.ai:
                                    context = f"{context} {visible_text(detail_doc)}"
                                base = fetched.final_url
                                locator += " (detail)"
                            except FetchError as e:
                                self.warnings.append(str(e))
                        else:
                            self.warnings.append(f"{locator}: no detail link found")
                    records.append(self.record(raw, all_specs, fetched, locator, base, context))
                nxt = select(doc, cfg.next_page) if cfg.next_page else None
                url = urljoin(page.final_url, nxt) if nxt else None
        return records
