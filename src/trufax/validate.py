"""Validation, de-duplication and reconciliation: what makes the output trustworthy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .config import ValidationConfig
from .records import DUPLICATE, INVALID, VALID, Record


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Outcome:
    records: list[Record]
    counts: dict[str, int]
    checks: list[Check] = field(default_factory=list)

    @property
    def valid(self) -> list[Record]:
        return [r for r in self.records if r.status == VALID]

    @property
    def rejected(self) -> list[Record]:
        return [r for r in self.records if r.status != VALID]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _check_rules(rec: Record, cfg: ValidationConfig) -> None:
    for name in cfg.required:
        if rec.data.get(name) in (None, ""):
            rec.errors.append(f"{name}: required but missing")
    for rule in cfg.rules:
        v = rec.data.get(rule.field)
        if v is None:
            continue
        n = _num(v)
        if rule.min is not None and n is not None and n < Decimal(str(rule.min)):
            rec.errors.append(f"{rule.field}: {v} below minimum {rule.min}")
        if rule.max is not None and n is not None and n > Decimal(str(rule.max)):
            rec.errors.append(f"{rule.field}: {v} above maximum {rule.max}")
        if rule.pattern and not re.fullmatch(rule.pattern, str(v)):
            rec.errors.append(f"{rule.field}: {v!r} does not match {rule.pattern}")
        if rule.one_of is not None and v not in rule.one_of:
            rec.errors.append(f"{rule.field}: {v!r} not one of {rule.one_of}")
        if rule.sum_of:
            parts = [_num(rec.data.get(f)) for f in rule.sum_of]
            if any(p is None for p in parts):
                continue  # a missing part means the sum cannot be checked
            total, target = sum(p for p in parts if p is not None), _num(v)
            if target is None or abs(target - total) > Decimal(str(rule.tolerance)):
                rec.errors.append(
                    f"{rule.field}: {v} does not equal {' + '.join(rule.sum_of)} = {total}"
                )


def _num(v) -> Decimal | None:
    try:
        return Decimal(str(v))
    except (ArithmeticError, ValueError):
        return None


def validate(
    records: list[Record], cfg: ValidationConfig, extra_checks: list[Check] | None = None
) -> Outcome:
    seen: dict[tuple, str] = {}
    for rec in records:
        _check_rules(rec, cfg)
        if rec.errors:
            rec.status = INVALID
            continue
        if cfg.key:
            k = tuple(rec.data.get(f) for f in cfg.key)
            if k in seen:
                rec.status = DUPLICATE
                rec.errors.append(f"duplicate of {seen[k]} on key {cfg.key}")
                continue
            seen[k] = rec.provenance.locator

    counts = {
        "extracted": len(records),
        "valid": sum(r.status == VALID for r in records),
        "invalid": sum(r.status == INVALID for r in records),
        "duplicate": sum(r.status == DUPLICATE for r in records),
    }
    checks = list(extra_checks or [])
    checks.append(
        Check("Records were extracted", counts["extracted"] > 0, f"{counts['extracted']} records")
    )
    balance = counts["valid"] + counts["invalid"] + counts["duplicate"]
    checks.append(
        Check(
            "Every extracted record accounted for",
            balance == counts["extracted"],
            f"{counts['extracted']} extracted = {counts['valid']} valid + "
            f"{counts['invalid']} invalid + {counts['duplicate']} duplicate",
        )
    )
    if cfg.min_records:
        checks.append(
            Check(
                f"At least {cfg.min_records} valid records",
                counts["valid"] >= cfg.min_records,
                f"{counts['valid']} valid",
            )
        )
    return Outcome(records=records, counts=counts, checks=checks)


def completeness(records: list[Record], fields: list[str]) -> dict[str, float]:
    """Share of valid records with a non-empty value, per field."""
    valid = [r for r in records if r.status == VALID]
    if not valid:
        return {f: 0.0 for f in fields}
    return {f: sum(r.data.get(f) not in (None, "") for r in valid) / len(valid) for f in fields}
