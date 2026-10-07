"""Cleaning and typing of raw extracted values.

Transforms are named in config and applied in order before typing, e.g.
``transforms: [collapse_ws, strip_currency]`` or ``transforms: ["regex:(\\d+) in stock"]``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

from .config import FieldSpec


class TransformError(ValueError):
    pass


def _collapse_ws(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip()


def _strip_currency(v: str) -> str:
    return re.sub(r"[^\d,.\-()]", "", v)


def _fr_number(v: str) -> str:
    """French/European style "1 234,56" -> "1234.56"."""
    v = re.sub(r"[\s  ]", "", v)
    return v.replace(".", "").replace(",", ".") if "," in v else v


def _nonzero(v: str) -> str:
    """'14' -> 'true', '0' -> 'false': stock counts into in-stock flags."""
    try:
        return "true" if Decimal(_number_text(v) or "0") != 0 else "false"
    except InvalidOperation:
        return v


SIMPLE: dict[str, Callable[[str], str]] = {
    "strip": str.strip,
    "lower": str.lower,
    "upper": str.upper,
    "title": str.title,
    "collapse_ws": _collapse_ws,
    "strip_currency": _strip_currency,
    "remove_commas": lambda v: v.replace(",", ""),
    "digits": lambda v: re.sub(r"\D", "", v),
    "fr_number": _fr_number,
    "nonzero": _nonzero,
}


def apply_transforms(value: Any, names: list[str]) -> Any:
    for name in names:
        if value is None:
            return None
        value = str(value)
        if name in SIMPLE:
            value = SIMPLE[name](value)
        elif name.startswith("regex:"):
            m = re.search(name[len("regex:") :], value)
            value = (m.group(1) if m and m.groups() else m.group(0)) if m else None
        elif name.startswith("replace:"):
            old, _, new = name[len("replace:") :].partition("|")
            value = value.replace(old, new)
        else:
            raise TransformError(f"unknown transform '{name}'")
    return value


TRUE = {"true", "yes", "y", "1", "oui", "x"}
FALSE = {"false", "no", "n", "0", "non", ""}
DEFAULT_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %B %Y", "%B %d, %Y", "%Y%m%d"]


def _number_text(v: str) -> str:
    v = v.strip()
    negative = v.startswith("(") and v.endswith(")")  # accounting negatives: (1,234)
    v = v.strip("()").replace(",", "").replace(" ", "")
    return "-" + v if negative else v


def coerce(value: Any, spec: FieldSpec, base_url: str = "") -> Any:
    """Convert a cleaned value to the field's type. Raises TransformError if it can't."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return spec.default
    t = spec.type or "string"
    try:
        if t == "string":
            return str(value).strip()
        if t == "url":
            return urljoin(base_url, str(value).strip())
        if t == "int":
            return int(Decimal(_number_text(str(value))))
        if t == "decimal":
            return Decimal(_number_text(str(value)))
        if t == "float":
            return float(_number_text(str(value)))
        if t == "bool":
            s = str(value).strip().lower()
            if s in TRUE:
                return True
            if s in FALSE:
                return False
            raise TransformError(f"not a boolean: {value!r}")
        if t == "date":
            if isinstance(value, (date, datetime)):
                return value if isinstance(value, date) else value.date()
            s = str(value).strip()
            for fmt in spec.date_formats or DEFAULT_DATE_FORMATS:
                try:
                    return datetime.strptime(s, fmt).date()  # noqa: DTZ007 - a calendar date
                except ValueError:
                    continue
            raise TransformError(f"unrecognised date: {value!r}")
    except (InvalidOperation, ValueError) as e:
        if isinstance(e, TransformError):
            raise
        raise TransformError(f"cannot convert {value!r} to {t}") from e
    raise TransformError(f"unknown type {t}")


def clean(raw: Any, spec: FieldSpec, base_url: str = "") -> Any:
    return coerce(apply_transforms(raw, spec.transforms), spec, base_url)
