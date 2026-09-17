"""CLI entry point for the gate framework."""

from __future__ import annotations

import argparse
import sys

from gates.registry import Registry, Stage
from gates.reporter import emit
from gates.runner import Runner


def main() -> int:
    parser = argparse.ArgumentParser(prog="gates")
    parser.add_argument(
        "--registry",
        default="gates/registry.yaml",
        help="Path to the gate registry YAML",
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=[s.value for s in Stage],
    )
    parser.add_argument(
        "--format",
        default="text",
        choices=["text", "json"],
    )
    args = parser.parse_args()

    registry = Registry.load(args.registry)
    runner = Runner(registry)
    results = runner.run_stage(Stage(args.stage))
    return emit(results, fmt=args.format)


if __name__ == "__main__":
    sys.exit(main())
