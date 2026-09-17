from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gates.impl.lint import LintGate
from gates.registry import Gate, Stage, Verdict


def _gate() -> Gate:
    return Gate(
        id="QG-1",
        name="lint",
        stage=Stage.COMMIT,
        blocking=True,
        impl="gates.impl.lint:LintGate",
        timeout_seconds=120,
    )


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_pass_when_all_tools_clean(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("gates.impl.lint.shutil.which", lambda _: "/usr/bin/ruff")
    monkeypatch.setattr(
        "gates.impl.lint.subprocess.run",
        lambda *a, **kw: _completed(0),
    )
    monkeypatch.setattr(LintGate, "TARGETS", [str(tmp_path)])

    result = LintGate().run(_gate())

    assert result.verdict == Verdict.PASS
    assert "all tools passed" in result.message


def test_fail_when_tool_returns_nonzero(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("gates.impl.lint.shutil.which", lambda _: "/usr/bin/ruff")
    monkeypatch.setattr(
        "gates.impl.lint.subprocess.run",
        lambda *a, **kw: _completed(1, stderr="bad formatting"),
    )
    monkeypatch.setattr(LintGate, "TARGETS", [str(tmp_path)])

    result = LintGate().run(_gate())

    assert result.verdict == Verdict.FAIL
    assert "failed" in result.message
    assert "failures" in result.details
    assert len(result.details["failures"]) == len(LintGate.COMMANDS)


def test_error_when_tool_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("gates.impl.lint.shutil.which", lambda _: None)
    monkeypatch.setattr(LintGate, "TARGETS", [str(tmp_path)])

    result = LintGate().run(_gate())

    assert result.verdict == Verdict.ERROR
    assert "not installed" in result.message


def test_skip_when_no_targets(monkeypatch) -> None:
    monkeypatch.setattr(LintGate, "TARGETS", ["definitely-not-a-real-dir-xyz"])

    result = LintGate().run(_gate())

    assert result.verdict == Verdict.SKIP
    assert "no target directories" in result.message


def test_details_include_targets_on_pass(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("gates.impl.lint.shutil.which", lambda _: "/usr/bin/x")
    monkeypatch.setattr(
        "gates.impl.lint.subprocess.run",
        lambda *a, **kw: _completed(0),
    )
    monkeypatch.setattr(LintGate, "TARGETS", [str(tmp_path)])

    result = LintGate().run(_gate())

    assert result.details["targets"] == [str(tmp_path)]


def test_failure_details_capture_output(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("gates.impl.lint.shutil.which", lambda _: "/usr/bin/x")
    monkeypatch.setattr(
        "gates.impl.lint.subprocess.run",
        lambda *a, **kw: _completed(1, stdout="warning text", stderr="error text"),
    )
    monkeypatch.setattr(LintGate, "TARGETS", [str(tmp_path)])

    result = LintGate().run(_gate())

    failures = result.details["failures"]
    assert any("error text" in f["stderr"] for f in failures)
    assert any("warning text" in f["stdout"] for f in failures)


@pytest.mark.parametrize("returncode", [1, 2, 127])
def test_nonzero_returncodes_all_fail(monkeypatch, tmp_path: Path, returncode: int) -> None:
    monkeypatch.setattr("gates.impl.lint.shutil.which", lambda _: "/usr/bin/x")
    monkeypatch.setattr(
        "gates.impl.lint.subprocess.run",
        lambda *a, **kw: _completed(returncode),
    )
    monkeypatch.setattr(LintGate, "TARGETS", [str(tmp_path)])

    result = LintGate().run(_gate())

    assert result.verdict == Verdict.FAIL
