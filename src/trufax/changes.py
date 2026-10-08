"""Change detection: what is new, changed or removed since the last clean run.

Records are matched on the job's key fields and compared on their declared fields only,
so a record that merely moved to another page or row is not a change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .export import _plain
from .history import Snapshot
from .records import Record


def record_key(data: dict[str, Any], key_fields: list[str]) -> str:
    return json.dumps([_plain(data.get(f)) for f in key_fields], default=str)


def key_label(key: str | list) -> str:
    """'["DRL-1001"]' -> 'DRL-1001'; multi-field keys are joined with ' / '."""
    parts = json.loads(key) if isinstance(key, str) else key
    return " / ".join(str(p) for p in parts)


def plain(data: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {f: _plain(data.get(f)) for f in fields}


def fingerprint(values: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class ChangeSet:
    baseline_run: str | None
    removals_checked: bool  # False on a partial run: missing records may just be unread
    new: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    unchanged: int = 0

    @property
    def counts(self) -> dict[str, Any]:
        return {
            "new": len(self.new),
            "changed": len(self.changed),
            "removed": len(self.removed) if self.removals_checked else None,
            "unchanged": self.unchanged,
            "since_run": self.baseline_run,
        }

    @property
    def total(self) -> int:
        return len(self.new) + len(self.changed) + len(self.removed)

    def rows(self) -> list[dict[str, Any]]:
        return self.changed + self.new + self.removed

    def summary(self) -> str:
        if self.baseline_run is None:
            return f"baseline recorded ({self.unchanged + len(self.new)} records)"
        removed = (
            f"{len(self.removed)} removed"
            if self.removals_checked
            else "removals not checked (partial run)"
        )
        return (
            f"{len(self.new)} new, {len(self.changed)} changed, {removed}, "
            f"{self.unchanged} unchanged since run {self.baseline_run}"
        )


def detect(
    records: list[Record],
    fields: list[str],
    key_fields: list[str],
    baseline: Snapshot | None,
    clean: bool,
) -> tuple[ChangeSet, list[tuple[str, str, dict[str, Any]]]]:
    """Compare valid records with the baseline. Returns the change set and this run's
    snapshot rows (key, hash, values)."""
    snapshot: list[tuple[str, str, dict[str, Any]]] = []
    cs = ChangeSet(baseline_run=baseline.run_id if baseline else None, removals_checked=clean)
    previous = dict(baseline.records) if baseline else {}
    for rec in records:
        key = record_key(rec.data, key_fields)
        values = plain(rec.data, fields)
        digest = fingerprint(values)
        snapshot.append((key, digest, values))
        if baseline is None:
            cs.unchanged += 1  # first run: nothing to compare with
            continue
        old = previous.pop(key, None)
        if old is None:
            cs.new.append(
                {
                    "key": key,
                    "kind": "new",
                    "fields": [],
                    "before": None,
                    "after": values,
                    "values": values,
                }
            )
        elif old[0] == digest:
            cs.unchanged += 1
        else:
            before = old[1]
            diff = [f for f in fields if before.get(f) != values.get(f)]
            cs.changed.append(
                {
                    "key": key,
                    "kind": "changed",
                    "fields": diff,
                    "before": {f: before.get(f) for f in diff},
                    "after": {f: values.get(f) for f in diff},
                    "values": values,
                }
            )
    if baseline is not None and clean:
        cs.removed = [
            {
                "key": k,
                "kind": "removed",
                "fields": [],
                "before": data,
                "after": None,
                "values": data,
            }
            for k, (_, data) in sorted(previous.items())
        ]
    return cs, snapshot


def change_table(cs: ChangeSet, fields: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows for changes.csv: the record's current values (last known values for removed
    records), what changed, and the previous values of the fields that changed."""
    columns = ["_change", "_changed_fields", "_previous_values", *fields]
    out = []
    for c in cs.rows():
        previous = ""
        if c["kind"] == "changed":
            previous = "; ".join(f"{k}={v}" for k, v in c["before"].items())
        out.append(
            {
                "_change": c["kind"],
                "_changed_fields": "; ".join(c["fields"]),
                "_previous_values": previous,
                **c["values"],
            }
        )
    return out, columns
