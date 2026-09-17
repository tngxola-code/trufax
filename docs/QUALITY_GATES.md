# Quality Gates

Trufax has 12 quality gates. Each gate is a checkpoint that blocks promotion
if it fails. A gate is only added when it catches a real failure mode we have
seen or expect.

## Stages

| Stage | When it runs | Blocks |
|---|---|---|
| `commit` | Every push | PR merge |
| `pull-request` | Every PR | PR merge |
| `deploy` | Before production deploy | Deploy |

## Gate inventory

| ID | Name | Stage | Tool |
|---|---|---|---|
| QG-1 | lint | commit | ruff, mypy |
| QG-2 | unit-tests | commit | pytest |
| QG-3 | secrets-scan | commit | gitleaks |
| QG-4 | dependency-audit | commit | pip-audit |
| QG-5 | integration-tests | pull-request | pytest |
| QG-6 | data-contracts | pull-request | pandera |
| QG-7 | api-contract | pull-request | openapi-spec-validator |
| QG-8 | api-breaking-change | pull-request | openapi-diff |
| QG-9 | container-scan | deploy | trivy |
| QG-10 | provenance-smoke | deploy | trufax verify |
| QG-11 | tenant-isolation | deploy | pytest |
| QG-12 | migrations-reversible | deploy | alembic |

## How gates are declared

Gates live in `gates/registry.yaml`. Each gate entry points to a Python
implementation under `gates/impl/`.

```yaml
version: 1
gates:
  - id: QG-1
    name: lint
    stage: commit
    blocking: true
    impl: gates.impl.lint:LintGate
    timeout_seconds: 120
```

## How gates are run

```bash
./scripts/run-gates.sh commit
./scripts/run-gates.sh pull-request
./scripts/run-gates.sh deploy
```

Or directly:

```bash
python -m gates.cli --stage commit
```

## What is NOT a gate

- Runtime alerts (latency, error rate, SLO burn)
- Compliance certifications (GDPR, SOC 2, HIPAA)
- Production Readiness Reviews
- Roadmap features

These are important. They are not gates.

## Adding a gate

1. Prove it catches a failure we have seen or expect.
2. Add an entry to `gates/registry.yaml`.
3. Implement it under `gates/impl/`.
4. Add a test under `tests/gates/`.
5. Wire it into `.github/workflows/quality-gates.yml` if it introduces a new
   external tool.

A gate that does not block promotion is not a gate.
