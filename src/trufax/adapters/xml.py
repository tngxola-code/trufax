"""XML files of any size: streams one record element at a time, namespaces ignored.

Field ``src`` is a path relative to the record using local names, e.g. ``Address/City``,
``@id`` or ``Owner/@type``.
"""

from __future__ import annotations

import io

from lxml import etree

from ..fetch import FetchError
from ..records import Record
from .base import Adapter


def to_xpath(path: str) -> str:
    """Local-name path to XPath. A leading ``//`` searches all descendants."""
    prefix = ".//" if path.startswith("//") else "./"
    steps = []
    for step in path.strip("/").split("/"):
        if step.startswith("@"):
            steps.append(f"@*[local-name()='{step[1:]}']")
        elif step == "text()":
            steps.append(step)
        else:
            steps.append(f"*[local-name()='{step}']")
    return prefix + "/".join(steps)


def _value(el, path: str) -> str | None:
    found = el.xpath(to_xpath(path))
    if not found:
        return None
    first = found[0]
    if isinstance(first, str):
        return first.strip() or None
    text = " ".join(t.strip() for t in first.itertext() if t.strip())
    return text or None


class XmlAdapter(Adapter):
    def extract(self) -> list[Record]:
        assert self.job.source.xml is not None
        tag = self.job.source.xml.record_tag
        specs = self.job.fields
        paths: dict[str, list[str]] = {
            n: (s.src if isinstance(s.src, list) else [str(s.src if s.src is not None else n)])
            for n, s in specs.items()
            if s.extracted
        }
        records: list[Record] = []
        for url in self.job.source.start_urls:
            if self.full(records):
                break
            try:
                doc = self.fetcher.get(url)
            except FetchError as e:
                self.warnings.append(str(e))
                continue
            n = 0
            for _, el in etree.iterparse(
                io.BytesIO(doc.content), events=("end",), huge_tree=True, resolve_entities=False
            ):
                if etree.QName(el).localname != tag:
                    continue
                n += 1
                raw: dict[str, str | None] = {}
                for name, plist in paths.items():
                    parts = [v for v in (_value(el, p) for p in plist) if v]
                    raw[name] = specs[name].join.join(parts) if parts else None
                context = (
                    " ".join(t.strip() for t in el.itertext() if t.strip()) if self.ai else None
                )
                records.append(self.record(raw, specs, doc, f"record {n}", context=context))
                el.clear()
                while el.getprevious() is not None:
                    del el.getparent()[0]
                if self.full(records):
                    break
            if n == 0:
                self.warnings.append(f"no <{tag}> elements found in {doc.final_url}")
        return records
