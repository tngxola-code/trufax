from __future__ import annotations

import subprocess
from pathlib import Path

from gates.impl.unit import UnitGate
from gates.registry import Gate, Stage, Verdict


def _gate() -> Gate:
    return Gate(
        id="QG-2",
        name="unit-tests",
        stage=Stage.COMMIT,
        blocking=True,
        impl="gates.impl.unit:UnitGate",
        timeout_seconds=300,
    )


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


_COVERAGE_OK = """
Name                      Stmts   Miss  Cover
---------------------------------------------
gates/__init__.py             1      0   100%
gates/registry.py            50      5    90%
gates/runner.py              40      4    90%
---------------------------------------------
TOTAL                        91      9    90%
"""

_COVERAGE_LOW = """
Name                      Stmts   Miss  Cover
---------------------------------------------
gates/__init__.py             1      0   100%
gates/registry.py            50     30    40%
gates/runner.py              40     30    25%
---------------------------------------------
TOTAL                        91     60    34%
"""


def test_pass_when_tests_and_coverage_clean(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("gates.impl.unit.shutil.which", lambda _: "/usr/bin/pytest")
    monkeypatch.setattr(
        "gates.impl.unit.subprocess.run",
        lambda *a, **kw: _completed(0, stdout=_COVERAGE_OK),
    )
    monkeypatch.setattr(UnitGate, "TEST_PATH", str(tmp_path))

    result = UnitGate().run(_gate())

    assert result.verdict == Verdict.PASS
    assert "coverage 90%" in result.message
    assert result.details["coverage"] == 90
    assert result.details["threshold"] == 80


def test_fail_when_coverage_below_threshold(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("gates.impl.unit.shutil.which", lambda _: "/usr/bin/pytest")
    monkeypatch.setattr(
        "gates.impl.unit.subprocess.run",
        lambda *a, **kw: _completed(1, stdout=_COVERAGE_LOW),
    )
    monkeypatch.setattr(UnitGate, "TEST_PATH", str(tmp_path))

    result = UnitGate().run(_gate())

    assert result.verdict == Verdict.FAIL
    assert "coverage 34%" in result.message
    assert result.details["coverage"] == 34
    assert result.details["threshold"] == 80


def test_fail_when_tests_fail_without_coverage_report(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("gates.impl.unit.shutil.which", lambda _: "/usr/bin/pytest")
    monkeypatch.setattr(
        "gates.impl.unit.subprocess.run",
        lambda *a, **kw: _completed(1, stdout="1 failed, 5 passed"),
    )
    monkeypatch.setattr(UnitGate, "TEST_PATH", str(tmp_path))

    result = UnitGate().run(_gate())

    assert result.verdict == Verdict.FAIL
    assert "pytest failed" in result.message
    assert result.details["coverage"] is None


def test_error_when_pytest_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("gates.impl.unit.shutil.which", lambda _: None)
    monkeypatch.setattr(UnitGate, "TEST_PATH", str(tmp_path))

    result = UnitGate().run(_gate())

    assert result.verdict == Verdict.ERROR
    assert "pytest is not installed" in result.message


def test_skip_when_test_path_missing(monkeypatch) -> None:
    monkeypatch.setattr("gates.impl.unit.shutil.which", lambda _: "/usr/bin/pytest")
    monkeypatch.setattr(UnitGate, "TEST_PATH", "does-not-exist-xyz")

    result = UnitGate().run(_gate())

    assert result.verdict == Verdict.SKIP
    assert "test path not found" in result.message


def test_coverage_extraction_handles_missing_total() -> None:
    assert UnitGate._extract_coverage("no total line here") is None


def test_coverage_extraction_parses_percent() -> None:
    assert UnitGate._extract_coverage(_COVERAGE_OK) == 90


def test_coverage_extraction_handles_malformed_percent() -> None:
    assert UnitGate._extract_coverage("TOTAL   10   5   100%extra") is None


def test_details_include_command_and_output_on_failure(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("gates.impl.unit.shutil.which", lambda _: "/usr/bin/pytest")
    monkeypatch.setattr(
        "gates.impl.unit.subprocess.run",
        lambda *a, **kw: _completed(1, stdout="something failed", stderr="err"),
    )
    monkeypatch.setattr(UnitGate, "TEST_PATH", str(tmp_path))

    result = UnitGate().run(_gate())

    assert "command" in result.details
    assert "stdout" in result.details
    assert "stderr" in result.details
