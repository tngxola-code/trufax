"""PDF documents: tables (pdfplumber) or line-by-line regex over the text layer.

Total rows printed in the document are used as reconciliation checks instead of being
exported: the data rows above each total must add up to it.
"""

from __future__ import annotations

import io
import re

import pdfplumber

from ..fetch import Fetched, FetchError
from ..records import Record
from .base import Adapter
from .tabular import Row, norm_cell, records_with_totals, row_values


def parse_pages(spec: str | None, total: int) -> list[int]:
    """'1-3,5' -> [0, 1, 2, 4] (zero-based), clipped to the document."""
    if not spec:
        return list(range(total))
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a) - 1, min(int(b), total)))
        elif part:
            pages.append(int(part) - 1)
    return [p for p in pages if 0 <= p < total]


class PdfAdapter(Adapter):
    def extract(self) -> list[Record]:
        records: list[Record] = []
        for url in self.job.source.start_urls:
            if self.full(records):
                break
            try:
                doc = self.fetcher.get(url)
            except FetchError as e:
                self.warnings.append(str(e))
                continue
            assert self.job.source.pdf is not None
            totals = self.job.source.pdf.totals
            try:
                rows = self._rows(doc)
            except ValueError as e:  # e.g. a configured column is not in the table
                self.warnings.append(f"{doc.final_url}: {e}")
                continue
            records.extend(records_with_totals(self, rows, doc, totals, len(records)))
        return records

    # -- reading ------------------------------------------------------------
    def _rows(self, doc: Fetched) -> list[Row]:
        cfg = self.job.source.pdf
        assert cfg is not None  # set by SourceConfig for pdf sources
        specs = self.job.fields
        out: list[Row] = []
        skips = [re.compile(p) for p in cfg.skip_rows_matching]
        with pdfplumber.open(io.BytesIO(doc.content)) as pdf:
            headers: list[str] | None = None
            for pno in parse_pages(cfg.pages, len(pdf.pages)):
                page = pdf.pages[pno]
                if cfg.mode == "text":
                    pattern = re.compile(cfg.row_regex or "")
                    for lno, line in enumerate((page.extract_text() or "").splitlines(), 1):
                        m = pattern.search(line)
                        if m and not any(s.search(line) for s in skips):
                            raw = {
                                n: m.groupdict().get(str(s.src or n))
                                for n, s in specs.items()
                                if s.extracted
                            }
                            out.append((raw, f"page {pno + 1} line {lno}", line))
                    continue
                for tno, raw_table in enumerate(page.extract_tables(cfg.table_settings), 1):
                    table: list[list[str]] = [
                        [norm_cell(c) for c in row] for row in raw_table if any(row)
                    ]
                    if not table:
                        continue
                    if headers is None:
                        headers = table[cfg.header_row]
                        table = table[cfg.header_row + 1 :]
                    elif table[0] == headers:  # header repeated on a new page
                        table = table[1:]
                    assert headers is not None
                    for rno, row in enumerate(table, 1):
                        line = " ".join(row)
                        if any(s.search(line) for s in skips):
                            continue
                        raw = row_values(row, headers, specs)
                        out.append((raw, f"page {pno + 1} table {tno} row {rno}", line))
        if not out:
            self.warnings.append(f"no rows extracted from {doc.final_url}")
        return out
