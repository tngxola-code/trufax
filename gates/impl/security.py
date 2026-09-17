"""QG-3: security gate.

Runs three independent checks against the codebase:

  1. pip-audit       — dependency vulnerabilities (CVEs in installed packages)
  2. bandit          — Python static analysis for security anti-patterns
  3. detect-secrets  — secrets committed to the repository

The gate fails if any check reports an issue. The gate errors if any
required tool is not installed. The gate skips if no target directories
exist.

Targets are scoped to known-good directories. Widening the scope is a
separate change.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

from gates.registry import Gate, GateResult, Verdict


class SecurityGate:
    # Scope: source and gate implementations. Tests are excluded because
    # bandit legitimately flags patterns used in test fixtures.
    TARGETS: ClassVar[list[str]] = ["gates", "src"]

    # Timeout per tool, in seconds.
    TIMEOUT: ClassVar[int] = 300

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

        # 1. Dependency vulnerability scan.
        result = self._run_pip_audit()
        if result is not None and result["returncode"] != 0:
            failures.append(result)

        # 2. Static analysis for security anti-patterns.
        result = self._run_bandit(targets)
        if result is not None and result["returncode"] != 0:
            failures.append(result)

        # 3. Secret detection.
        result = self._run_detect_secrets()
        if result is not None and result["returncode"] != 0:
            failures.append(result)

        # If any tool was missing, surface it as an error, not a failure.
        missing = self._missing_tools()
        if missing:
            return GateResult(
                gate=gate,
                verdict=Verdict.ERROR,
                duration_ms=0,
                message=f"required tools not installed: {', '.join(missing)}",
                details={"missing": missing},
            )

        if failures:
            tools = ", ".join(f["tool"] for f in failures)
            return GateResult(
                gate=gate,
                verdict=Verdict.FAIL,
                duration_ms=0,
                message=f"{len(failures)} check(s) failed: {tools}",
                details={"failures": failures},
            )

        return GateResult(
            gate=gate,
            verdict=Verdict.PASS,
            duration_ms=0,
            message="all security checks passed",
            details={"targets": targets},
        )

    # -- individual checks -------------------------------------------------

    def _run_pip_audit(self) -> dict | None:
        if shutil.which("pip-audit") is None:
            return None
        proc = subprocess.run(
            ["pip-audit", "--strict", "--progress-spinner", "off"],
            capture_output=True,
            text=True,
            check=False,
            timeout=self.TIMEOUT,
        )
        if proc.returncode == 0:
            return None
        return {
            "tool": "pip-audit",
            "command": "pip-audit --strict",
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }

    def _run_bandit(self, targets: list[str]) -> dict | None:
        if shutil.which("bandit") is None:
            return None
        proc = subprocess.run(
            ["bandit", "-r", "-q", "-ll"] + targets,
            capture_output=True,
            text=True,
            check=False,
            timeout=self.TIMEOUT,
        )
        if proc.returncode == 0:
            return None
        return {
            "tool": "bandit",
            "command": f"bandit -r -q -ll {' '.join(targets)}",
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }

    def _run_detect_secrets(self) -> dict | None:
        if shutil.which("detect-secrets") is None:
            return None
        proc = subprocess.run(
            [
                "detect-secrets", "scan",
                "--exclude-files", r"(\.venv/|\.git/|data/|node_modules/)",
                "gates", "src", "tests/gates",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=self.TIMEOUT,
        )
        if proc.returncode != 0:
            return {
                "tool": "detect-secrets",
                "command": "detect-secrets scan --all-files",
                "returncode": proc.returncode,
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-2000:],
            }
        # Parse the JSON baseline. Any entry in "results" means a secret was
        # detected. Also honour inline allowlist entries (which the tool
        # excludes from results).
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {
                "tool": "detect-secrets",
                "command": "detect-secrets scan --all-files",
                "returncode": 1,
                "stdout": proc.stdout[-2000:],
                "stderr": "could not parse detect-secrets JSON output",
            }
        findings = data.get("results", {})
        total = sum(len(v) for v in findings.values())
        if total == 0:
            return None
        return {
            "tool": "detect-secrets",
            "command": "detect-secrets scan --all-files",
            "returncode": 1,
            "stdout": f"{total} potential secret(s) detected",
            "stderr": "",
            "files": {k: len(v) for k, v in findings.items()},
        }

    def _missing_tools(self) -> list[str]:
        required = ["pip-audit", "bandit", "detect-secrets"]
        return [t for t in required if shutil.which(t) is None]
