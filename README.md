# Trufax

**From raw data to trusted decisions.**

> **Trufax**: internet slang for "true facts." A platform that turns fragmented public
> and enterprise data into canonical datasets you can prove, in any domain.

---

## The problem

The data you need usually exists, is authoritative, and is useless in its current form:
a registry split across hundreds of files, budgets locked in PDFs, listings spread over
dozens of websites, each with its own layout. Teams write a scraper per source, a parser
per format and mapping code per domain. Six months later half of it is broken and nobody
can say which version produced which number.

**This is not a data problem. It's a trust problem.**

## What Trufax does

Trufax is a **headless, config-driven** extraction platform. You describe a job in YAML;
the engine fetches, extracts, cleans, validates and delivers it, and every run produces a
proof report showing what was collected, from where, and which checks it passed.

- **No code per source.** A new website, PDF or XML feed is a new YAML file.
- **No code per domain.** A domain pack defines the shape of the data once; every job in
  that domain produces the same columns, keys and checks.
- **Headless.** Everything runs from the CLI or the HTTP API. Dashboards, client
  deliverables and AI agents are consumers of the same API.
- **Provable.** Every record carries its source URL, its exact location in the source and
  the SHA-256 of the source bytes. Rejected records are listed with the reason.
- **Local AI, optional.** Fields can be filled by a model running on your own machine
  (Ollama), and every model-extracted value must appear in the source text or it is rejected.

---

## Works today

| Area | Capability |
|---|---|
| Sources | Web pages (CSS/XPath, pagination, detail pages, optional headless browser), PDF tables or text (multi-page tables, printed-total reconciliation), XML of any size (streamed, namespace-agnostic) |
| Fetching | Rate limit, retries with backoff, robots.txt, disk cache, headers, proxy |
| Domain packs | `real-estate` (Property, Sale, Listing), `e-commerce` (Product), `public-finance` (BudgetLine), `leads` (Company); add your own with `TRUFAX_PACKS` |
| Cleaning | 7 field types, 11 transforms, fixed values, accounting negatives, French number format |
| Trust | Required, min/max, pattern, one_of, sum_of rules; key-based de-duplication; every extracted record accounted for; provenance and SHA-256 per record |
| Local AI | `llm` fields via Ollama with JSON-schema output and a citation check |
| Outputs | CSV, Excel, JSON, rejected.csv with reasons, manifest.json, one-page proof-report.html, optional Google Sheets |
| Interfaces | CLI (`run`, `sample`, `check`, `new`, `packs`, `export-repo`, `serve`) and HTTP API |
| Delivery | `export-repo` builds a standalone repository a client owns and can run without you |
| Quality | Quality gates QG-1 to QG-4 (lint, types, tests, 80% coverage), Docker image and compose file |

---

## Quick start

```bash
pip install -e '.[dev]'
make demo        # three offline examples: an HTML catalogue, a budget PDF, an assessment roll
make gates       # the commit-stage quality gates
```

Each run writes `output/<job>/<run-id>/` containing `data.csv`, `data.xlsx`,
`rejected.csv`, `manifest.json` and `proof-report.html`.

```bash
trufax packs                              # list domain packs
trufax packs real-estate                  # entities and fields of one pack
trufax new acme-prices --type html        # job file from a template
trufax check jobs/acme-prices.yaml        # validate without fetching
trufax sample jobs/acme-prices.yaml       # 20 records + proof report
trufax run jobs/acme-prices.yaml          # full run
trufax export-repo jobs/acme-prices.yaml --out ../acme-delivery
```

---

## How a job looks

A job names a pack and an entity, then says where each field comes from. Types, keys,
required fields and rules come from the pack.

```yaml
job: example-assessment-roll
pack: real-estate
entity: Property

source:
  type: xml
  start_urls: [roll-sample.xml]
  xml: { record_tag: Unit }
  fields:
    jurisdiction: { value: "99001" }
    parcel_id: "@id"
    street: "Address/Street"
    land_value: { src: "Values/Land", transforms: [fr_number] }
    building_value: { src: "Values/Building", transforms: [fr_number] }
    total_value: { src: "Values/Total", transforms: [fr_number] }
```

The real-estate pack's rule `total_value = land_value + building_value` then rejects any
unit where the roll does not add up, with the reason in `rejected.csv`.

### A domain pack

```yaml
pack: e-commerce
entities:
  Product:
    key: [sku]
    required: [name, price]
    fields:
      sku: string
      name: string
      price: decimal
      in_stock: bool
      rating: decimal
    rules:
      - { field: rating, min: 0, max: 5 }
```

Built-in packs live in `src/trufax/domain_packs/`. Point `TRUFAX_PACKS` at a folder of
your own pack files to add domains without touching the code.

### Local AI fields

```yaml
ai: { base_url: "http://localhost:11434", model: "qwen3:4b" }
source:
  fields:
    brand: { llm: "the manufacturer's brand name" }
```

The model reads each record's text, returns JSON constrained to the field schema, and is
told to copy values verbatim. A value that does not appear in the source text is rejected.
Model-filled fields are named in the `_ai_fields` column with the model that filled them.

---

## Headless API

```bash
pip install -e '.[api]'
TRUFAX_API_KEY=change-me trufax serve --home trufax-home
```

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Liveness (no key needed) |
| GET | `/v1/packs`, `/v1/packs/{name}` | Domain packs and their entities |
| GET, PUT, DELETE | `/v1/jobs/{name}` | Read, save (YAML body, validated) or delete a job |
| POST | `/v1/jobs/{name}/runs?limit=&wait=` | Start a run (background by default) |
| GET | `/v1/runs`, `/v1/runs/{id}` | Run status, counts, checks |
| GET | `/v1/runs/{id}/report` | The proof report |
| GET | `/v1/runs/{id}/data?format=json\|csv\|xlsx&rejected=` | The data |

Send `Authorization: Bearer <key>` or `X-API-Key: <key>`. Jobs saved through the API may
only read local files inside `TRUFAX_HOME/data`. Interactive docs are at `/docs`.

### Docker

```bash
TRUFAX_API_KEY=change-me docker compose up -d
docker compose exec ollama ollama pull qwen3:4b
```

This starts the API on port 8000 and a local model server it can use for `llm` fields.

---

## Repository layout

```
src/trufax/          the platform engine
  config.py          job schema        packs.py       domain packs
  fetch.py           polite fetching   adapters/      html, pdf, xml
  transforms.py      cleaning, typing  validate.py    rules, de-duplication
  ai.py              local model extraction with citation check
  export.py          outputs           report.py      manifest, proof report
  api.py             HTTP API          cli.py         trufax command
  domain_packs/      built-in packs    templates/     job templates
src/qc_property/     the original Québec assessment-roll extractor (unchanged)
gates/               quality gate framework (QG-1 to QG-4)
examples/            one working job per source type, plus a Québec roll template
```

The Québec extractor package is kept as it was. `examples/quebec/quebec-city-roll.yaml`
shows the same roll as a real-estate pack job; its record tag and matricule format are
marked for confirmation against a downloaded roll file.

---

## Roadmap

| Next | Why |
|---|---|
| JSON API and spreadsheet sources | Many sources are hidden APIs or client spreadsheets |
| Docling for scanned and complex PDFs | Layout-aware tables and OCR without manual setup |
| Scheduled runs and change detection | New, changed and removed records between runs |
| Canonical store with history | Ask what was true on any date; join entities across sources |
| Entity resolution | The same property or product matched across sources |
| `trufax suggest <url>` | A local model drafts the job file from a sample page |
| Signed manifests and `trufax verify` | Ed25519-signed run records anyone can verify against the source bytes |
| Multi-tenant API and MCP server | Isolated tenants, per-tenant keys, AI agents querying data directly |

---

## License

No LICENSE file has been added yet. Add one before publishing or accepting contributions.
