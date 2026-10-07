from datetime import date
from decimal import Decimal

import pytest

from trufax.config import FieldSpec
from trufax.transforms import TransformError, apply_transforms, clean


@pytest.mark.parametrize(
    "raw,transforms,expected",
    [
        ("  a   b ", ["collapse_ws"], "a b"),
        ("R 1,249.00", ["strip_currency"], "1,249.00"),
        ("1 234,56", ["fr_number"], "1234.56"),
        ("Only 3 left", ["regex:(\\d+) left"], "3"),
        ("no match", ["regex:(\\d+)"], None),
        ("In stock", ["replace:In stock|yes"], "yes"),
    ],
)
def test_transforms(raw, transforms, expected):
    assert apply_transforms(raw, transforms) == expected


def test_unknown_transform():
    with pytest.raises(TransformError):
        apply_transforms("x", ["nope"])


@pytest.mark.parametrize(
    "raw,ftype,expected",
    [
        ("1,249.50", "decimal", Decimal("1249.50")),
        ("(12,400)", "decimal", Decimal(-12400)),
        ("42", "int", 42),
        ("yes", "bool", True),
        ("2024-07-01", "date", date(2024, 7, 1)),
        ("31/12/2025", "date", date(2025, 12, 31)),
        ("", "decimal", None),
    ],
)
def test_types(raw, ftype, expected):
    assert clean(raw, FieldSpec(type=ftype)) == expected


def test_url_is_made_absolute():
    spec = FieldSpec(type="url")
    assert clean("../a.html", spec, "https://x.com/b/c.html") == "https://x.com/a.html"


def test_bad_number_raises():
    with pytest.raises(TransformError):
        clean("abc", FieldSpec(type="decimal"))


def test_default_used_when_empty():
    assert clean(None, FieldSpec(type="bool", default=False)) is False
