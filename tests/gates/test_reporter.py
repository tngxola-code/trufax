from gates.registry import Gate, GateResult, Stage, Verdict
from gates.reporter import emit, render_json, render_text


def _result(verdict: Verdict, blocking: bool = True) -> GateResult:
    gate = Gate("QG-1", "lint", Stage.COMMIT, blocking,
                "gates.impl.lint:LintGate", 60)
    return GateResult(gate=gate, verdict=verdict, duration_ms=42)


def test_render_text_pass() -> None:
    out = render_text([_result(Verdict.PASS)])
    assert "PASS" in out
    assert "QG-1" in out


def test_render_text_empty() -> None:
    assert render_text([]) == "(no gates in this stage)"


def test_render_json_roundtrip() -> None:
    import json
    payload = json.loads(render_json([_result(Verdict.FAIL)]))
    assert payload[0]["id"] == "QG-1"
    assert payload[0]["verdict"] == "fail"


def test_emit_returns_1_on_blocking_failure() -> None:
    rc = emit([_result(Verdict.FAIL)], fmt="text")
    assert rc == 1


def test_emit_returns_0_on_pass() -> None:
    rc = emit([_result(Verdict.PASS)], fmt="text")
    assert rc == 0
