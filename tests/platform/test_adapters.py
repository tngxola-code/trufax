from decimal import Decimal

import pytest

from trufax.config import load_job
from trufax.runner import run_job


def test_html_catalog_with_pagination_and_details(examples, tmp_path):
    res = run_job(load_job(examples / "catalog" / "catalog.yaml"), out_root=tmp_path)
    o = res.outcome
    assert o.counts == {"extracted": 6, "valid": 4, "invalid": 1, "duplicate": 1}
    drill = next(r for r in o.valid if r.data["sku"] == "DRL-1001")
    assert drill.data["price"] == Decimal("1249.00")
    assert drill.data["stock_qty"] == 14 and drill.data["in_stock"] is True
    assert drill.data["category"] == "Power tools"
    assert drill.provenance.locator == "page 1 item 1 (detail)"
    assert len(drill.provenance.source_sha256) == 64
    gloves = next(r for r in o.valid if r.data["sku"] == "PPE-0410")
    assert gloves.data["in_stock"] is False
    bad = next(r for r in o.rejected if r.status == "INVALID")
    assert "price: required but missing" in bad.errors
    assert res.manifest.status == "PASSED"


def test_sample_limit(examples, tmp_path):
    res = run_job(load_job(examples / "catalog" / "catalog.yaml"), out_root=tmp_path, limit=2)
    assert res.outcome.counts["extracted"] == 2
    assert res.manifest.mode == "sample"


def test_pdf_totals_reconcile(examples, tmp_path):
    res = run_job(load_job(examples / "budget" / "budget.yaml"), out_root=tmp_path)
    o = res.outcome
    assert o.counts["valid"] == 10  # total rows are checks, not records
    total_checks = [c for c in o.checks if "matches its rows" in c.name]
    assert len(total_checks) == 6 and all(c.passed for c in total_checks)
    refunds = next(r for r in o.valid if r.data["line_item"].startswith("Refunds"))
    assert refunds.data["amount_prior"] == Decimal(-12400)


def test_pdf_total_mismatch_is_flagged(tmp_path):
    reportlab = pytest.importorskip("reportlab")  # noqa: F841
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    pdf = tmp_path / "bad.pdf"
    t = Table([["Item", "Amount"], ["A", "100"], ["B", "250"], ["Total", "999"]])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))]))
    SimpleDocTemplate(str(pdf), pagesize=A4).build([t])
    job_file = tmp_path / "job.yaml"
    job_file.write_text(f"""
job: bad-total
source:
  type: pdf
  start_urls: [{pdf}]
  pdf:
    totals: [{{label_field: item, label_regex: "^Total", sum_fields: [amount]}}]
  fields:
    item: Item
    amount: {{src: Amount, type: decimal}}
""")
    res = run_job(load_job(job_file), out_root=tmp_path / "out")
    failed = [c for c in res.outcome.checks if not c.passed]
    assert failed and "rows sum to 350" in failed[0].detail
    assert res.manifest.status == "REVIEW"


def test_xml_stream_and_sum_rule(examples, tmp_path):
    res = run_job(
        load_job(examples / "assessment-roll" / "assessment-roll.yaml"), out_root=tmp_path
    )
    o = res.outcome
    assert o.counts["valid"] == 4 and o.counts["invalid"] == 1
    unit = next(r for r in o.valid if r.data["parcel_id"] == "9900-14-0001")
    assert unit.data["total_value"] == 4660500 and unit.data["use_code"] == "5000"
    assert str(unit.data["reference_date"]) == "2024-07-01"
    bad = o.rejected[0]
    assert bad.data["parcel_id"] == "9900-14-0002"
    assert "does not equal land_value + building_value" in bad.errors[0]


def test_outputs_written(examples, tmp_path):
    res = run_job(load_job(examples / "catalog" / "catalog.yaml"), out_root=tmp_path)
    names = {p.name for p in res.out_dir.iterdir()}
    assert {
        "data.csv",
        "data.xlsx",
        "data.json",
        "rejected.csv",
        "manifest.json",
        "proof-report.html",
    } <= names
    html = res.report.read_text()
    assert "All checks passed" in html and "DRL-1001" in html
