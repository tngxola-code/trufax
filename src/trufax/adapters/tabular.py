"""Shared logic for row-and-column sources (PDF tables, spreadsheets).

Rows are matched to fields by column header (case-insensitive) or position. Printed
total rows are not exported: they become reconciliation checks, and the data rows above
each one must add up to it.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING

from ..config import FieldSpec, TotalCheck
from ..validate import Check

if TYPE_CHECKING:
    from ..fetch import Fetched
    from ..records import Record
    from .base import Adapter

# (raw values by field, locator, the row's text for model extraction)
Row = tuple[dict[str, str | None], str, str]


def norm_cell(cell: object) -> str:
    return re.sub(r"\s+", " ", str(cell if cell is not None else "")).strip()


def column_value(row: list[str], headers: list[str], spec: FieldSpec, name: str) -> str | None:
    """The cell for a field: ``src`` is a header name, a 0-based column index, or (when
    omitted) the field's own name."""
    src = spec.src if spec.src is not None else name
    if isinstance(src, list):
        raise ValueError(  # noqa: TRY004 - a config error, reported like the others
            f"field '{name}': table fields read one column, not a list"
        )
    if isinstance(src, int):
        idx: int | None = src
    else:
        wanted = norm_cell(src).lower()
        idx = next((i for i, h in enumerate(headers) if h.lower() == wanted), None)
    if idx is None:
        raise ValueError(f"column '{src}' not found; headers are {headers}")
    value = row[idx] if idx < len(row) else None
    return value or None


def row_values(row: list[str], headers: list[str], specs: dict[str, FieldSpec]) -> dict:
    return {n: column_value(row, headers, s, n) for n, s in specs.items() if s.extracted}


def records_with_totals(
    adapter: Adapter,
    rows: list[Row],
    doc: Fetched,
    totals: list[TotalCheck],
    already: int,
) -> list[Record]:
    """Build records, turning total rows into checks. In a sample run every row is still
    read so totals reconcile; only the emitted records are capped."""
    specs = adapter.job.fields
    running = {id(t): {f: Decimal(0) for f in t.sum_fields} for t in totals}
    cap = adapter.limit if adapter.limit is not None else 10**12
    out: list[Record] = []
    for raw, locator, line in rows:
        rec = adapter.record(raw, specs, doc, locator, context=line if adapter.ai else None)
        total = _matching_total(totals, raw)
        if total is not None:
            adapter.checks.extend(_check_total(total, rec, running[id(total)], locator))
            running[id(total)] = {f: Decimal(0) for f in total.sum_fields}
            continue
        for t in totals:
            for f in t.sum_fields:
                v = rec.data.get(f)
                if isinstance(v, (int, Decimal)):
                    running[id(t)][f] += Decimal(v)
        if already + len(out) < cap:
            out.append(rec)
    return out


def _matching_total(totals: list[TotalCheck], raw: dict) -> TotalCheck | None:
    for t in totals:
        label = raw.get(t.label_field) or ""
        if re.search(t.label_regex, str(label)):
            return t
    return None


def _check_total(t: TotalCheck, rec: Record, sums: dict, locator: str) -> list[Check]:
    label = rec.data.get(t.label_field)
    checks = []
    for f in t.sum_fields:
        printed = rec.data.get(f)
        if not isinstance(printed, (int, Decimal)):
            checks.append(
                Check(
                    f"'{label}' {f} at {locator}", False, f"printed total not numeric: {printed!r}"
                )
            )
            continue
        diff = abs(Decimal(printed) - sums[f])
        checks.append(
            Check(
                f"'{label}' {f} matches its rows ({locator})",
                diff <= Decimal(str(t.tolerance)),
                f"printed {printed}, rows sum to {sums[f]}, difference {diff}",
            )
        )
    return checks
