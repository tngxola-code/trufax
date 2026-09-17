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
| QG-3 | security-scan | pull-request | pip-audit, bandit, detect-secrets |
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

## Security gate (QG-3)

Runs in the **pull-request** stage. Blocks merge if any of the following
report an issue:

- `pip-audit --strict` — known CVEs in installed dependencies
- `bandit -r -q -ll` — Python security anti-patterns (high/medium)
- `detect-secrets scan --all-files` — hardcoded secrets

Scope: `gates/` and `src/`. Tests are excluded because bandit legitimately
flags patterns used in fixtures.

If any required tool is missing, the gate errors and blocks merge. Install
all three via `pip install -e ".[dev]"`.

## Security gate (QG-3)

Runs in the **pull-request** stage. Blocks merge if any of the following
report an issue:

- `pip-audit --strict` — known CVEs in installed dependencies
- `bandit -r -q -ll` — Python security anti-patterns (high/medium)
- `detect-secrets scan --all-files` — hardcoded secrets

Scope: `gates/` and `src/`. Tests are excluded because bandit legitimately
flags patterns used in fixtures.

If any required tool is missing, the gate errors and blocks merge. Install
all three via `pip install -e ".[dev]"`.

## Unit-test gate (QG-2)

Runs in the **commit** stage. Blocks PR merge if any test fails or if
coverage on `gates/` drops below the threshold.

- **Test path**: `tests/gates/`
- **Coverage source**: `gates/`
- **Threshold**: 80%
- **Tool**: pytest + pytest-cov

Widening the scope to `tests/` and `src/` is a follow-up branch once the
existing test suite is coverage-ready.
