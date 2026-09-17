from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gates.impl.security import SecurityGate
from gates.registry import Gate, Stage, Verdict


def _gate() -> Gate:
    return Gate(
        id="QG-3",
        name="security-scan",
        stage=Stage.PULL_REQUEST,
        blocking=True,
        impl="gates.impl.security:SecurityGate",
        timeout_seconds=300,
    )


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _all_tools_present(monkeypatch) -> None:
    monkeypatch.setattr("gates.impl.security.shutil.which", lambda _: "/usr/local/bin/tool")


def _no_tools_present(monkeypatch) -> None:
    monkeypatch.setattr("gates.impl.security.shutil.which", lambda _: None)


def test_pass_when_all_checks_clean(monkeypatch, tmp_path: Path) -> None:
    _all_tools_present(monkeypatch)

    def fake_run(cmd, **kwargs):
        # detect-secrets returns an empty baseline on success.
        if cmd[0] == "detect-secrets":
            return _completed(0, stdout=json.dumps({"results": {}}))
        return _completed(0)

    monkeypatch.setattr("gates.impl.security.subprocess.run", fake_run)
    monkeypatch.setattr(SecurityGate, "TARGETS", [str(tmp_path)])

    result = SecurityGate().run(_gate())

    assert result.verdict == Verdict.PASS
    assert "all security checks passed" in result.message


def test_fail_when_pip_audit_reports_cve(monkeypatch, tmp_path: Path) -> None:
    _all_tools_present(monkeypatch)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "pip-audit":
            return _completed(1, stdout="Found 3 known vulnerabilities")
        if cmd[0] == "detect-secrets":
            return _completed(0, stdout=json.dumps({"results": {}}))
        return _completed(0)

    monkeypatch.setattr("gates.impl.security.subprocess.run", fake_run)
    monkeypatch.setattr(SecurityGate, "TARGETS", [str(tmp_path)])

    result = SecurityGate().run(_gate())

    assert result.verdict == Verdict.FAIL
    assert "pip-audit" in result.message
    assert any(f["tool"] == "pip-audit" for f in result.details["failures"])


def test_fail_when_bandit_reports_issue(monkeypatch, tmp_path: Path) -> None:
    _all_tools_present(monkeypatch)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "bandit":
            return _completed(1, stdout="Issue: B301 pickle")
        if cmd[0] == "detect-secrets":
            return _completed(0, stdout=json.dumps({"results": {}}))
        return _completed(0)

    monkeypatch.setattr("gates.impl.security.subprocess.run", fake_run)
    monkeypatch.setattr(SecurityGate, "TARGETS", [str(tmp_path)])

    result = SecurityGate().run(_gate())

    assert result.verdict == Verdict.FAIL
    assert "bandit" in result.message


def test_fail_when_detect_secrets_finds_secret(monkeypatch, tmp_path: Path) -> None:
    _all_tools_present(monkeypatch)

    baseline = {
        "results": {
            "gates/impl/bad.py": [
                {"type": "AWS Access Key", "line_number": 12},
            ]
        }
    }

    def fake_run(cmd, **kwargs):
        if cmd[0] == "detect-secrets":
            return _completed(0, stdout=json.dumps(baseline))
        return _completed(0)

    monkeypatch.setattr("gates.impl.security.subprocess.run", fake_run)
    monkeypatch.setattr(SecurityGate, "TARGETS", [str(tmp_path)])

    result = SecurityGate().run(_gate())

    assert result.verdict == Verdict.FAIL
    assert "detect-secrets" in result.message
    failures = result.details["failures"]
    ds = next(f for f in failures if f["tool"] == "detect-secrets")
    assert ds["files"]["gates/impl/bad.py"] == 1


def test_error_when_a_tool_is_missing(monkeypatch, tmp_path: Path) -> None:
    _no_tools_present(monkeypatch)
    monkeypatch.setattr(SecurityGate, "TARGETS", [str(tmp_path)])

    result = SecurityGate().run(_gate())

    assert result.verdict == Verdict.ERROR
    assert "required tools not installed" in result.message
    assert set(result.details["missing"]) == {"pip-audit", "bandit", "detect-secrets"}


def test_skip_when_no_targets(monkeypatch) -> None:
    _all_tools_present(monkeypatch)
    monkeypatch.setattr(SecurityGate, "TARGETS", ["does-not-exist-xyz"])

    result = SecurityGate().run(_gate())

    assert result.verdict == Verdict.SKIP
    assert "no target directories" in result.message


def test_multiple_failures_are_all_reported(monkeypatch, tmp_path: Path) -> None:
    _all_tools_present(monkeypatch)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "detect-secrets":
            return _completed(0, stdout=json.dumps({"results": {"x.py": [{"type": "secret"}]}}))
        return _completed(1, stdout="issue")

    monkeypatch.setattr("gates.impl.security.subprocess.run", fake_run)
    monkeypatch.setattr(SecurityGate, "TARGETS", [str(tmp_path)])

    result = SecurityGate().run(_gate())

    assert result.verdict == Verdict.FAIL
    tools = {f["tool"] for f in result.details["failures"]}
    assert tools == {"pip-audit", "bandit", "detect-secrets"}


def test_malformed_detect_secrets_output_fails(monkeypatch, tmp_path: Path) -> None:
    _all_tools_present(monkeypatch)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "detect-secrets":
            return _completed(0, stdout="not json")
        return _completed(0)

    monkeypatch.setattr("gates.impl.security.subprocess.run", fake_run)
    monkeypatch.setattr(SecurityGate, "TARGETS", [str(tmp_path)])

    result = SecurityGate().run(_gate())

    assert result.verdict == Verdict.FAIL
    ds = next(f for f in result.details["failures"] if f["tool"] == "detect-secrets")
    assert "could not parse" in ds["stderr"]
