"""Command line: trufax run | sample | check | new | packs | export-repo | serve."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from . import __version__
from .config import load_job
from .fetch import FetchError
from .runner import run_job
from .scaffold import export_client_repo, new_job


def _load(path: str):
    try:
        return load_job(path)
    except ValidationError as e:
        print(f"{path}: invalid job file\n{e}", file=sys.stderr)
        sys.exit(2)
    except (OSError, ValueError) as e:
        print(f"{path}: {e}", file=sys.stderr)
        sys.exit(2)


def _summary(result) -> int:
    m = result.manifest
    c = m.counts
    print(f"{m.job}  run {m.run_id}  status {m.status}")
    print(
        f"  extracted {c['extracted']}  valid {c['valid']}  "
        f"invalid {c['invalid']}  duplicate {c['duplicate']}"
    )
    for chk in m.checks:
        print(f"  [{'PASS' if chk['passed'] else 'FAIL'}] {chk['name']}")
    for w in m.warnings[:5]:
        print(f"  warning: {w}")
    print(f"  output: {result.out_dir}")
    print(f"  proof report: {result.report}")
    return 0 if m.status == "PASSED" else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="trufax", description=__doc__)
    p.add_argument("--version", action="version", version=f"trufax {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a job and write data + proof report")
    r.add_argument("job")
    r.add_argument("--out", help="output root (default: the job's output.dir)")

    s = sub.add_parser("sample", help="quick run capped at N records (for proposals)")
    s.add_argument("job")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--out")

    c = sub.add_parser("check", help="validate a job file without fetching anything")
    c.add_argument("job")

    n = sub.add_parser("new", help="create a job file from a template")
    n.add_argument("name")
    n.add_argument("--type", choices=["html", "pdf", "xml", "json", "spreadsheet"], default="html")
    n.add_argument("--dir", default="jobs")

    pk = sub.add_parser("packs", help="list domain packs, or show one pack's entities")
    pk.add_argument("name", nargs="?")

    sv = sub.add_parser("serve", help="run the HTTP API (needs: pip install 'trufax[api]')")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--home", help="state folder (default: $TRUFAX_HOME or ./trufax-home)")

    e = sub.add_parser("export-repo", help="create a standalone repository for the client")
    e.add_argument("job")
    e.add_argument("--out", required=True)
    e.add_argument("--title")
    e.add_argument("--no-git", action="store_true")

    a = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if a.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if a.cmd in ("run", "sample"):
        job = _load(a.job)
        limit = a.limit if a.cmd == "sample" else None
        try:
            result = run_job(
                job, base_dir=Path.cwd(), limit=limit, out_root=Path(a.out) if a.out else None
            )
        except FetchError as e:  # e.g. a ${env:NAME} secret that is not set
            print(f"{a.job}: {e}", file=sys.stderr)
            return 2
        return _summary(result)
    if a.cmd == "check":
        job = _load(a.job)
        print(
            f"{a.job}: OK ({job.source.type} source, {len(job.output_fields)} fields, "
            f"{len(job.source.start_urls)} start URL(s))"
        )
        return 0
    if a.cmd == "new":
        path = new_job(a.name, a.type, Path(a.dir))
        print(f"created {path}")
        return 0
    if a.cmd == "packs":
        from .packs import available_packs, get_pack

        if a.name:
            pack = get_pack(a.name)
            print(f"{pack.pack} (v{pack.version}): {pack.description.strip()}")
            for ename, ent in pack.entities.items():
                print(f"\n  {ename}  key={ent.key}  required={ent.required}")
                for fname, f in ent.field_specs().items():
                    flag = "  [personal data]" if f.personal_data else ""
                    print(f"    {fname:<24} {f.type}{flag}")
        else:
            for pack in available_packs().values():
                print(f"{pack.pack:<16} {', '.join(pack.entities)}")
        return 0
    if a.cmd == "serve":
        from .api import main as serve

        serve(a.host, a.port, a.home)
        return 0
    if a.cmd == "export-repo":
        out = export_client_repo(Path(a.job), Path(a.out), a.title, init_git=not a.no_git)
        print(f"client repository ready: {out}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
