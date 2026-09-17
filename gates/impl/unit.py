"""QG-2: unit-test gate.

Runs pytest with coverage and enforces a minimum coverage threshold. The
gate passes only if all tests pass and coverage meets or exceeds the
threshold. If pytest is not installed, the gate errors.

Targets are scoped to known-good directories. Widening the scope is a
separate change.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

from gates.registry import Gate, GateResult, Verdict


class UnitGate:
    # Test directory to run. Coverage is measured on the source directory.
    TEST_PATH: ClassVar[str] = "tests/gates"
    COVERAGE_SOURCE: ClassVar[str] = "gates"
    COVERAGE_THRESHOLD: ClassVar[int] = 80

    TIMEOUT: ClassVar[int] = 300

    def run(self, gate: Gate) -> GateResult:
        if not Path(self.TEST_PATH).exists():
            return GateResult(
                gate=gate,
                verdict=Verdict.SKIP,
                duration_ms=0,
                message=f"test path not found: {self.TEST_PATH}",
                details={"test_path": self.TEST_PATH},
            )

        if shutil.which("pytest") is None:
            return GateResult(
                gate=gate,
                verdict=Verdict.ERROR,
                duration_ms=0,
                message="pytest is not installed",
                details={"tool": "pytest"},
            )

        cmd = [
            "pytest",
            self.TEST_PATH,
            f"--cov={self.COVERAGE_SOURCE}",
            "--cov-report=term",
            f"--cov-fail-under={self.COVERAGE_THRESHOLD}",
            "-q",
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=self.TIMEOUT,
        )

        coverage = self._extract_coverage(proc.stdout)

        if proc.returncode != 0:
            message = (
                f"pytest failed (exit {proc.returncode})"
                if coverage is None
                else f"pytest failed (exit {proc.returncode}, coverage {coverage}%)"
            )
            return GateResult(
                gate=gate,
                verdict=Verdict.FAIL,
                duration_ms=0,
                message=message,
                details={
                    "command": " ".join(cmd),
                    "returncode": proc.returncode,
                    "coverage": coverage,
                    "threshold": self.COVERAGE_THRESHOLD,
                    "stdout": proc.stdout[-3000:],
                    "stderr": proc.stderr[-2000:],
                },
            )

        return GateResult(
            gate=gate,
            verdict=Verdict.PASS,
            duration_ms=0,
            message=(
                f"all tests passed, coverage {coverage}% "
                f"(threshold {self.COVERAGE_THRESHOLD}%)"
                if coverage is not None
                else "all tests passed"
            ),
            details={
                "coverage": coverage,
                "threshold": self.COVERAGE_THRESHOLD,
            },
        )

    @staticmethod
    def _extract_coverage(stdout: str) -> int | None:
        """Parse pytest-cov 'TOTAL ... NN%' line from stdout."""
        for line in stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("TOTAL"):
                parts = stripped.split()
                for part in reversed(parts):
                    if part.endswith("%"):
                        try:
                            return int(part.rstrip("%"))
                        except ValueError:
                            return None
        return None
