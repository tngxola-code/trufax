#!/usr/bin/env bash
set -euo pipefail

STAGE="${1:-commit}"
FORMAT="${2:-text}"

python -m gates.cli \
  --registry gates/registry.yaml \
  --stage "$STAGE" \
  --format "$FORMAT"
