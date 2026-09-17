"""QG-1: lint gate.

Runs ruff (check + format) and mypy on the target directories. The gate
passes only if every tool exits zero. If a tool is not installed, the gate
errors with a clear message instead of crashing.

Targets are scoped to known-good directories. Widening the scope is a
separate change and should be done only after existing code is clean.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

from gates.registry import Gate, GateResult, Verdict


class LintGate:
    # Scope: only the gate framework for now. Widen to ["src", "tests", "gates"]
    # in a follow-up once existing code is lint-clean.
    TARGETS: ClassVar[list[str]] = ["gates"]

    # Tools run in order. Each must exit zero.
    COMMANDS: ClassVar[list[tuple[str, list[str]]]] = [
        ("ruff-check", ["ruff", "check"]),
        ("ruff-format", ["ruff", "format", "--check"]),
        ("mypy", ["mypy"]),
    ]

    def run(self, gate: Gate) -> GateResult:
        targets = [t for t in self.TARGETS if Path(t).exists()]
        if not targets:
            return GateResult(
                gate=gate,
                verdict=Verdict.SKIP,
                duration_ms=0,
                message="no target directories found",
                details={"targets": self.TARGETS},
            )

        failures: list[dict] = []

        for tool_name, cmd in self.COMMANDS:
            if shutil.which(cmd[0]) is None:
                return GateResult(
                    gate=gate,
                    verdict=Verdict.ERROR,
                    duration_ms=0,
                    message=f"{tool_name} is not installed",
                    details={"tool": tool_name, "command": cmd},
                )

            proc = subprocess.run(
                cmd + targets,
                capture_output=True,
                text=True,
                check=False,
            )

            if proc.returncode != 0:
                failures.append(
                    {
                        "tool": tool_name,
                        "command": " ".join(cmd + targets),
                        "returncode": proc.returncode,
                        "stdout": proc.stdout[-2000:],
                        "stderr": proc.stderr[-2000:],
                    }
                )

        if failures:
            tools = ", ".join(f["tool"] for f in failures)
            return GateResult(
                gate=gate,
                verdict=Verdict.FAIL,
                duration_ms=0,
                message=f"{len(failures)} tool(s) failed: {tools}",
                details={"failures": failures},
            )

        return GateResult(
            gate=gate,
            verdict=Verdict.PASS,
            duration_ms=0,
            message=f"all tools passed on {', '.join(targets)}",
            details={"targets": targets},
        )
