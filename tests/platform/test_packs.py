from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from trufax.config import UnsafePath, parse_job
from trufax.packs import PackError, available_packs
from trufax.runner import run_job

PAGE = """<html><body>
<div class="p"><h2>Kettle</h2><span class="price">R 499.00</span><span class="sku">K-1</span></div>
<div class="p"><h2>Toaster</h2><span class="price">R 389.50</span><span class="sku">T-2</span></div>
</body></html>"""


def job_yaml(page: Path, fields: str, extra: str = "") -> str:
    return f"""
job: pack-test
pack: e-commerce
entity: Product
source:
  type: html
  start_urls: [{page}]
  html: {{item_selector: "div.p"}}
  fields:
{fields}
{extra}
"""


@pytest.fixture
def page(tmp_path):
    p = tmp_path / "shop.html"
    p.write_text(PAGE)
    return p


def test_builtin_packs_load():
    packs = available_packs()
    assert {"real-estate", "e-commerce", "public-finance", "leads"} <= set(packs)
    assert "Property" in packs["real-estate"].entities


def test_pack_supplies_types_keys_and_required(page, tmp_path):
    fields = (
        '    name: "h2::text"\n    sku: "span.sku::text"\n'
        '    price: {src: "span.price::text", transforms: [strip_currency]}'
    )
    job = parse_job(job_yaml(page, fields), tmp_path)
    assert job.fields["price"].type == "decimal"  # from the pack, not the job
    assert job.validation.key == ["sku"]
    assert "price" in job.validation.required
    assert job.output_fields[0] == "sku" and "brand" in job.output_fields

    res = run_job(job, out_root=tmp_path / "out")
    assert res.outcome.counts["valid"] == 2
    kettle = next(r for r in res.outcome.valid if r.data["sku"] == "K-1")
    assert kettle.data["price"] == Decimal("499.00")
    header = (res.out_dir / "data.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.startswith("sku,name,brand,category")


def test_unknown_field_is_rejected(page, tmp_path):
    with pytest.raises(PackError, match="not part of e-commerce/Product"):
        parse_job(job_yaml(page, '    colour: "h2::text"'), tmp_path)


def test_unknown_entity_is_rejected(page, tmp_path):
    text = job_yaml(page, '    name: "h2::text"').replace("entity: Product", "entity: Car")
    with pytest.raises(PackError, match="no entity 'Car'"):
        parse_job(text, tmp_path)


def test_pack_and_entity_go_together(page, tmp_path):
    text = job_yaml(page, '    name: "h2::text"').replace("entity: Product\n", "")
    with pytest.raises(ValidationError, match="set both"):
        parse_job(text, tmp_path)


def test_custom_pack_folder(page, tmp_path, monkeypatch):
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "shoes.yaml").write_text(
        "pack: shoes\nentities:\n  Shoe:\n    key: [model]\n"
        "    fields: {model: string, size: decimal}\n"
    )
    monkeypatch.setenv("TRUFAX_PACKS", str(packs))
    assert "shoes" in available_packs()


def test_local_sources_confined_to_data_root(page, tmp_path):
    fields = '    name: "h2::text"'
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(UnsafePath):
        parse_job(job_yaml(page, fields), root, local_root=root)
    inside = root / "shop.html"
    inside.write_text(PAGE)
    job = parse_job(job_yaml(Path("shop.html"), fields), root, local_root=root)
    assert job.source.start_urls == [str(inside.resolve())]
