# Trufax

**From raw data to trusted decisions.**

[![Website](https://img.shields.io/badge/website-trufax.dev-blue)]()
[![Docs](https://img.shields.io/badge/docs-docs.trufax.dev-green)]()
[![Status](https://img.shields.io/badge/status-alpha-orange)]()

> **Trufax** - internet slang for "true facts." It meant verified truth before anyone built a company around it. We're bringing it back as a platform that turns fragmented data into provable, trusted decisions - across any domain.

---

## The problem

Every organization that works with public or enterprise data hits the same wall.

The data you need exists. It's authoritative. It's public. And it's useless in its current form.

A government registry is spread across hundreds of files - one per agency, each with its own schema. A health authority publishes patient outcomes as scanned PDFs going back to 2005. A legal gazette releases notices as HTML with no consistent structure. A financial regulator publishes filings in a different format every quarter. A procurement portal exposes tender data across a dozen disconnected sites. An environmental agency ships sensor readings as compressed archives with a different column order each month.

You can't query it. You can't join it. You can't audit it. You can't prove where a number came from.

So teams do what teams always do: they write scrapers. They write parsers. They write mapping code. They write it again for the next source. They write it again for the next domain. Six months later, half the scrapers are broken, nobody knows which version produced which number, and the analyst who built it has left the company.

**This is not a data problem. It's a trust problem.**

And it is the same problem in every domain - government, health, legal, financial, procurement, environment, education, immigration. The surface changes. The shape does not.

---

## What Trufax solves

Trufax turns fragmented, heterogeneous, untrusted sources into **canonical, provable, composable datasets** - driven entirely by configuration.

You declare a domain. You declare sources, formats, and mappings. Trufax does the rest: fetch, parse, transform, validate, publish, and prove.

**You do not write code for each new source. You write configuration.**

**You do not build a new pipeline for each new domain. You write a new config.**

Trufax is domain-agnostic by design. Government registries, health records, legal notices, financial filings, procurement data, environmental monitoring, education statistics, immigration records - they are all the same shape. Only the configuration changes.

---

## The journey: from data to trusted decisions

Trufax is built around a simple progression:

```
Raw data  -->  Information  -->  Knowledge  -->  Trusted decision
```

| Stage | What happens | What you get |
|---|---|---|
| **Raw data** | Fragmented sources in any format | XML, CSV, PDF, HTML, scans, archives, images |
| **Information** | Parsed, typed, validated records | Structured data with contract enforcement |
| **Knowledge** | Canonical entities, relationships, history | Queryable, joinable, versioned facts |
| **Trusted decision** | Provenance, verification, audit | Every fact traces to its source, with proof |

Most tools stop at **raw data** or **information**. Trufax goes all the way to **trusted decision**.

---

## What you get

| What | Why it matters |
|---|---|
| **Config-driven extraction** | Onboard a new domain by writing YAML, not deploying code |
| **Any format** | XML, CSV, JSON, PDF, Excel, HTML, images, archives |
| **Canonical model** | One schema across all sources, not one per source |
| **Provable provenance** | Every fact traces to its source bytes, with cryptographic proof |
| **Bi-temporal history** | Ask what was true then, not just what is true now |
| **Workspace** | Teams organize data, tasks, reports, and documents in one place |
| **API-first** | Every capability reachable programmatically, versioned, tenant-scoped |
| **Deploy anywhere** | SaaS, on-prem, or air-gapped - your choice |

---

## How it works (in plain language)

Trufax is **configuration-driven**. You describe your domain in a declarative file. Trufax reads that file and builds the pipeline.

Here is what a domain looks like - a public registry spread across multiple agencies and formats:

```yaml
domain: national-public-registry

sources:
  - id: agency-index
    format: csv
    url: https://registry.example.gov/agencies.csv

  - id: agency-records
    format: xml
    url: "{{ index.rows.*.url }}"

  - id: historical-archive
    format: pdf
    url: "https://archive.example.gov/{{ year }}/records.pdf"

parsers:
  - id: xml-records
    format: xml
    schema: schemas/records.xsd

  - id: pdf-archive
    format: pdf
    engine: pdfplumber
    options: { layout: true, ocr: fallback }

mappings:
  - from: xml-records
    fields:
      - source: "RecordId"
        target: record.identifier
      - source: "Value"
        target: valuation.amount

  - from: pdf-archive
    fields:
      - source: "regex:Record No\\. (\\d+)"
        target: record.identifier

canonical:
  entities:
    - name: record
      keys: [record_id]
    - name: valuation
      keys: [record_id]

contracts:
  - entity: record
    rules:
      - record_id is unique
      - identifier is not null
  - entity: valuation
    rules:
      - amount >= 0
```

That's it. No Python. No ETL code. No per-agency if-statements.

**The same pattern works for any domain.** A health registry, a legal gazette, a financial filing system, a procurement portal - the configuration changes, the platform does not.

Register the domain. Trigger a run. Query the result. Prove it.

```bash
trufax domains register domains/public-registry.yaml
trufax runs trigger --domain public-registry
trufax query --domain public-registry \
  "SELECT agency, AVG(amount) FROM record JOIN valuation USING (record_id) GROUP BY 1"
trufax export --domain public-registry --format xlsx --output records.xlsx
trufax verify --run-id <run_id>
```

**Onboarding a second domain - health, legal, financial, procurement - is the same process.** Write a config. Register it. Run it.

---

## What makes it trustworthy

Trust is not a feature. It's the architecture.

Every run produces a **signed manifest**:
- Source URLs and retrieval timestamps
- Byte sizes and SHA-256 hashes
- Parser versions, mapping versions, extractor versions
- Record counts and error counts
- An Ed25519 signature over the entire manifest

Every fact is **traceable**:
```
canonical value --> raw source tag --> retained source artifact --> run manifest
```

Every run is **verifiable**:
```bash
trufax verify --run-id <run_id>
```
This re-hashes the retained source bytes and compares them against the manifest. If they match, the run is verified. If they don't, you know exactly which source changed and when.

Every fact is **explainable**:
```bash
trufax provenance explain <record_id>
```
This returns the full chain from the canonical value back to the source bytes.

**No external service required.** Optionally, you can anchor manifest hashes to RFC 3161 timestamps or a public transparency log for independent third-party attestation.

---

## One platform. Every fragmented domain.

Trufax is domain-agnostic. If your data is fragmented, heterogeneous, and needs to be trustworthy, Trufax fits.

**Government and public sector**
Extract registries, permits, licenses, and public records across fragmented agencies. Publish open data as canonical, queryable datasets. Preserve provenance for FOI requests. Meet open-government commitments without building per-department pipelines.

**Health and life sciences**
Extract clinical registries, patient outcomes, trial data, and publications. Preserve lineage across decades of records. Support reproducible research and regulatory submissions.

**Legal and regulatory**
Extract gazettes, notices, court filings, and regulations. Trace every clause to its source document. Prove compliance to auditors.

**Financial services**
Extract filings, prospectuses, disclosures, and transaction records. Derive facts with bi-temporal history. Prove to regulators that a number came from a specific page of a specific filing.

**Procurement and supply chain**
Extract tender notices, award records, and supplier registries across disconnected portals. Join across jurisdictions. Prove sourcing decisions.

**Environment and climate**
Extract monitoring data, permits, emissions records, and sensor feeds. Join across agencies and time periods. Prove environmental compliance.

**Education and research**
Extract enrollment statistics, credentials, funding records, and publications. Preserve lineage. Support reproducible analysis.

**Immigration and borders**
Extract visa records, residency permits, and border statistics. Join across agencies. Prove chain of custody.

**Real estate and property**
Extract assessment rolls, land titles, permits, and zoning records across every jurisdiction. Join with sales, tax, and demographic data. Screen thousands of properties in seconds.

**Any domain where "where did this number come from?" matters.**

---

## Why it's different

Trufax is not competing with Bright Data, LlamaParse, Fivetran, or DataTrails. It sits **above** them.

| Layer | Who solves it | What Trufax does |
|---|---|---|
| Fetching | Bright Data, Zyte, Apify | Pluggable - use theirs |
| Parsing | LlamaParse, Textract, ABBYY | Pluggable - use theirs |
| Moving | Fivetran, Airbyte | Not our problem |
| Attesting | DataTrails, Woleet | We go further - semantic provenance |
| **Deriving facts with proof** | **Nobody** | **This is what we do** |

Every competitor stops at bytes. Trufax derives **facts** - with a citation, a derivation chain, a proof, and a bi-temporal record. You can ask *why* a fact is true, *when* it was true, and *what would change if the source changed*. No one else can answer that.

---

## Get started

**Prerequisites:** Docker, Python 3.12+, `make`.

```bash
git clone https://github.com/trufax/trufax.git
cd trufax
cp .env.example .env
./scripts/bootstrap.sh
```

Then open [https://localhost:8443/docs](https://localhost:8443/docs) to explore the API.

**Extract your first dataset:**

```bash
trufax domains register domains/public-registry.yaml
trufax runs trigger --domain public-registry
trufax runs watch --domain public-registry --latest
trufax export --domain public-registry --format xlsx --output records.xlsx
```

You now have a clean, canonical, verifiable spreadsheet. Every row traces to its source.

---

## Who it's for

**Data platform teams** who are tired of writing the same extraction code for every new source.

**Regulated enterprises** who need to prove where a number came from - to auditors, regulators, or courts.

**Government agencies** who need to publish open data as canonical, queryable datasets without building a pipeline per department.

**Health, legal, financial, and research institutions** who need reproducible, auditable data pipelines.

**Anyone who has ever asked: "where did this number come from?" and not had a good answer.**

---

## The name

**Trufax** is internet slang for "true facts" - a piece of factual information; truth. It was born in forums and chat rooms in the early 2000s, a shorthand for "this is verified, this is real, this is the truth."

The internet forgot the word. We're bringing it back - as a platform that turns fragmented data into verified, provable facts, across every domain.

---

## Support

- **Documentation:** [docs.trufax.dev](https://docs.trufax.dev)
- **API reference:** [docs.trufax.dev/api](https://docs.trufax.dev/api)
- **Discussions:** [github.com/trufax/trufax/discussions](https://github.com/trufax/trufax/discussions)
- **Issues:** [github.com/trufax/trufax/issues](https://github.com/trufax/trufax/issues)
- **Commercial:** [hello@trufax.dev](mailto:hello@trufax.dev)

---

## License

Apache License 2.0. See [LICENSE](./LICENSE).

---

> **Trufax is a platform, not a pipeline.**
> **From raw data to trusted decisions - in any domain.**
