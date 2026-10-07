"""PDF documents: tables (pdfplumber) or line-by-line regex over the text layer.

Total rows printed in the document are used as reconciliation checks instead of being
exported: the data rows above each total must add up to it.
"""

from __future__ import annotations

import io
import re
from decimal import Decimal

import pdfplumber

from ..config import FieldSpec, TotalCheck
from ..fetch import Fetched, FetchError
from ..records import Record
from ..validate import Check
from .base import Adapter


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


def _norm(cell) -> str:
    return re.sub(r"\s+", " ", str(cell or "")).strip()


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
            rows = self._rows(doc)
            records.extend(self._to_records(rows, doc, records))
        return records

    # -- reading ------------------------------------------------------------
    def _rows(self, doc: Fetched) -> list[tuple[dict[str, str | None], str, str]]:
        cfg = self.job.source.pdf
        assert cfg is not None  # set by SourceConfig for pdf sources
        specs = self.job.fields
        out: list[tuple[dict[str, str | None], str, str]] = []
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
                        [_norm(c) for c in row] for row in raw_table if any(row)
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
                        raw = {
                            n: self._cell(row, headers, s, n)
                            for n, s in specs.items()
                            if s.extracted
                        }
                        out.append((raw, f"page {pno + 1} table {tno} row {rno}", line))
        if not out:
            self.warnings.append(f"no rows extracted from {doc.final_url}")
        return out

    @staticmethod
    def _cell(row: list[str], headers: list[str], spec: FieldSpec, name: str) -> str | None:
        src = spec.src if spec.src is not None else name
        if isinstance(src, list):
            raise ValueError(  # noqa: TRY004 - a config error, reported like the others
                f"field '{name}': pdf fields read one column, not a list"
            )
        if isinstance(src, int):
            idx: int | None = src
        else:
            wanted = _norm(src).lower()
            idx = next((i for i, h in enumerate(headers) if h.lower() == wanted), None)
        if idx is None:
            raise ValueError(f"column '{src}' not found; table headers are {headers}")
        return row[idx] if idx < len(row) else None

    # -- records and totals -------------------------------------------------
    def _to_records(self, rows, doc: Fetched, so_far: list[Record]) -> list[Record]:
        assert self.job.source.pdf is not None
        totals = self.job.source.pdf.totals
        specs = self.job.fields
        running = {id(t): {f: Decimal(0) for f in t.sum_fields} for t in totals}
        out: list[Record] = []
        for raw, locator, line in rows:
            rec = self.record(raw, specs, doc, locator, context=line if self.ai else None)
            total = self._matching_total(totals, raw)
            if total is not None:
                self._check_total(total, rec, running[id(total)], locator)
                running[id(total)] = {f: Decimal(0) for f in total.sum_fields}
                continue
            for t in totals:
                for f in t.sum_fields:
                    v = rec.data.get(f)
                    if isinstance(v, (int, Decimal)):
                        running[id(t)][f] += Decimal(v)
            # in a sample run, keep reading so totals still reconcile; just don't emit
            if len(so_far) + len(out) < (self.limit or 10**12):
                out.append(rec)
        return out

    @staticmethod
    def _matching_total(totals: list[TotalCheck], raw: dict) -> TotalCheck | None:
        for t in totals:
            label = raw.get(t.label_field) or ""
            if re.search(t.label_regex, str(label)):
                return t
        return None

    def _check_total(self, t: TotalCheck, rec: Record, sums: dict, locator: str) -> None:
        label = rec.data.get(t.label_field)
        for f in t.sum_fields:
            printed = rec.data.get(f)
            if not isinstance(printed, (int, Decimal)):
                self.checks.append(
                    Check(
                        f"'{label}' {f} at {locator}",
                        False,
                        f"printed total not numeric: {printed!r}",
                    )
                )
                continue
            diff = abs(Decimal(printed) - sums[f])
            self.checks.append(
                Check(
                    f"'{label}' {f} matches its rows ({locator})",
                    diff <= Decimal(str(t.tolerance)),
                    f"printed {printed}, rows sum to {sums[f]}, difference {diff}",
                )
            )
