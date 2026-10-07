"""Run manifest (machine-readable) and proof report (one self-contained HTML page).

The proof report is what goes to the client: what was collected, from where, which
checks it passed, and what was rejected and why.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from html import escape
from pathlib import Path

from . import __version__
from .export import _plain
from .fetch import Fetched
from .records import Record
from .validate import Check, Outcome


@dataclass
class Manifest:
    run_id: str
    job: str
    client: str
    mode: str  # "full" or "sample"
    started_at: str
    finished_at: str
    status: str  # PASSED or REVIEW
    counts: dict[str, int]
    checks: list[dict]
    sources: list[dict]
    warnings: list[str]
    outputs: list[str] = field(default_factory=list)
    engine_version: str = __version__

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, default=str), encoding="utf-8")


def source_entries(fetches: list[Fetched]) -> list[dict]:
    seen, out = set(), []
    for f in fetches:
        if f.final_url in seen:
            continue
        seen.add(f.final_url)
        out.append(
            {
                "url": f.final_url,
                "sha256": f.sha256,
                "bytes": len(f.content),
                "fetched_at": f.fetched_at.isoformat(timespec="seconds"),
                "from_cache": f.from_cache,
            }
        )
    return out


def make_manifest(
    run_id, job, mode, started, finished, outcome: Outcome, fetches, warnings, outputs
) -> Manifest:
    return Manifest(
        run_id=run_id,
        job=job.job,
        client=job.client,
        mode=mode,
        started_at=started.isoformat(timespec="seconds"),
        finished_at=finished.isoformat(timespec="seconds"),
        status="PASSED" if outcome.passed and outcome.counts["valid"] else "REVIEW",
        counts=outcome.counts,
        checks=[asdict(c) for c in outcome.checks],
        sources=source_entries(fetches),
        warnings=warnings,
        outputs=[str(p.name) for p in outputs],
    )


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e4e3de;
--ok:#1f7a4d;--okbg:#e5f3ec;--bad:#a8321e;--badbg:#f8e6e2;--bar:#2f5d8a}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#ecebe6;
--mute:#9b9a94;--line:#33322f;--ok:#5fc08f;--okbg:#17301f;--bad:#ef8a75;--badbg:#3a1f1a;
--bar:#7aa7d6}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 12px}
.meta{color:var(--mute);font-size:13px}.badge{display:inline-block;padding:3px 10px;
border-radius:99px;font-weight:600;font-size:13px;margin-left:8px;vertical-align:middle}
.pass{background:var(--okbg);color:var(--ok)}.fail{background:var(--badbg);color:var(--bad)}
.tiles{display:flex;flex-wrap:wrap;gap:12px;margin-top:20px}
.tile{flex:1 1 150px;background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px}.tile b{display:block;font-size:26px}.tile span{color:var(--mute);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;
padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-weight:600}tr:last-child td{border-bottom:0}
code{font:12px ui-monospace,Menlo,monospace;word-break:break-all}
.check{display:flex;gap:10px;padding:10px 12px;border-bottom:1px solid var(--line)}
.check:last-child{border-bottom:0}.check small{color:var(--mute);display:block}
.mark{font-weight:700;min-width:44px}.ok{color:var(--ok)}.no{color:var(--bad)}
.barwrap{background:var(--line);border-radius:4px;height:8px;width:160px;display:inline-block;
vertical-align:middle;margin-right:8px}.bar{background:var(--bar);height:8px;border-radius:4px}
a{color:var(--bar)}footer{margin-top:40px;color:var(--mute);font-size:12px}
"""


def _table(rows: list[dict], columns: list[str]) -> str:
    head = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body = []
    for r in rows:
        cells = []
        for c in columns:
            v = r.get(c)
            v = "" if v is None else str(v)
            if c == "_source_url" and v:
                cells.append(f'<td><a href="{escape(v)}">{escape(v[-48:])}</a></td>')
            else:
                cells.append(f"<td>{escape(v[:160])}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="card"><table><tr>{head}</tr>{"".join(body)}</table></div>'


def render_report(
    m: Manifest,
    fields: list[str],
    completeness: dict[str, float],
    valid: list[Record],
    rejected: list[Record],
    description: str = "",
) -> str:
    passed = m.status == "PASSED"
    checks: list[Check] = [Check(**c) for c in m.checks]
    n_pass = sum(c.passed for c in checks)
    rejected_n = m.counts["invalid"] + m.counts["duplicate"]
    tiles = [
        (m.counts["extracted"], "records extracted"),
        (m.counts["valid"], "valid, delivered"),
        (rejected_n, "rejected, with reasons"),
        (f"{n_pass}/{len(checks)}", "checks passed"),
        (len(m.sources), "sources fetched"),
    ]
    check_html = "".join(
        f'<div class="check"><span class="mark {"ok" if c.passed else "no"}">'
        f"{'PASS' if c.passed else 'FAIL'}</span><div>{escape(c.name)}"
        f"<small>{escape(c.detail)}</small></div></div>"
        for c in checks
    )
    comp_rows = "".join(
        f'<tr><td>{escape(f)}</td><td><span class="barwrap"><span class="bar" '
        f'style="width:{pct * 100:.0f}%;display:block"></span></span>{pct:.0%}</td></tr>'
        for f, pct in completeness.items()
    )
    src_rows = [
        {
            "url": s["url"],
            "sha256": s["sha256"][:16] + "…",
            "bytes": s["bytes"],
            "fetched_at": s["fetched_at"],
        }
        for s in m.sources[:50]
    ]
    sample_cols = fields + ["_locator", "_source_url"]
    sample = [{k: _plain(v) for k, v in r.flat().items()} for r in valid[:10]]
    rej_rows = [
        {**{k: _plain(v) for k, v in r.flat().items()}, "reason": "; ".join(r.errors)}
        for r in rejected[:10]
    ]
    warn = "".join(f"<li>{escape(w)}</li>" for w in m.warnings[:30])
    more_sources = (
        f'<p class="meta">…and {len(m.sources) - 50} more in manifest.json</p>'
        if len(m.sources) > 50
        else ""
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Proof report: {escape(m.job)}</title><style>{CSS}</style></head><body><main>
<h1>{escape(m.job)}<span class="badge {"pass" if passed else "fail"}">
{"All checks passed" if passed else "Needs review"}</span></h1>
<div class="meta">{escape(m.client + " · " if m.client else "")}Run {escape(m.run_id)} ·
{escape(m.mode)} run · {escape(m.started_at)} to {escape(m.finished_at)}</div>
{f"<p>{escape(description)}</p>" if description else ""}
<div class="tiles">{
        "".join(f"<div class='tile'><b>{t}</b><span>{s}</span></div>" for t, s in tiles)
    }</div>
<h2>Checks</h2><div class="card">{check_html}</div>
<h2>Field completeness</h2><p class="meta">Share of delivered records with a value.</p>
<div class="card"><table>{comp_rows}</table></div>
<h2>Sample of delivered records</h2>
{_table(sample, sample_cols) if sample else '<p class="meta">No valid records.</p>'}
{
        "<h2>Rejected records and reasons</h2>" + _table(rej_rows, fields + ["reason", "_locator"])
        if rej_rows
        else ""
    }
<h2>Sources</h2><p class="meta">SHA-256 fingerprints let anyone confirm the exact source
bytes each record came from.</p>{_table(src_rows, ["url", "sha256", "bytes", "fetched_at"])}
{more_sources}
{f"<h2>Warnings</h2><div class='card'><ul>{warn}</ul></div>" if warn else ""}
<footer>Generated by trufax {escape(m.engine_version)}. Full details: manifest.json.
</footer></main></body></html>"""
