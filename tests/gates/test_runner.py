from gates.registry import Gate, GateResult, Registry, Stage, Verdict
from gates.runner import Runner


class _PassGate:
    def run(self, gate: Gate) -> GateResult:
        return GateResult(gate=gate, verdict=Verdict.PASS, duration_ms=0)


class _FailGate:
    def run(self, gate: Gate) -> GateResult:
        return GateResult(gate=gate, verdict=Verdict.FAIL, duration_ms=0,
                          message="intentional failure")


class _ErrorGate:
    def run(self, gate: Gate) -> GateResult:
        raise RuntimeError("boom")


def test_runner_pass() -> None:
    gate = Gate("QG-1", "lint", Stage.COMMIT, True,
                "tests.gates.test_runner:_PassGate", 60)
    reg = Registry([gate])
    results = Runner(reg).run_stage(Stage.COMMIT)
    assert len(results) == 1
    assert results[0].verdict == Verdict.PASS
    assert Runner.verdict(results) == Verdict.PASS


def test_runner_fail_blocking() -> None:
    gate = Gate("QG-1", "lint", Stage.COMMIT, True,
                "tests.gates.test_runner:_FailGate", 60)
    reg = Registry([gate])
    results = Runner(reg).run_stage(Stage.COMMIT)
    assert results[0].verdict == Verdict.FAIL
    assert Runner.verdict(results) == Verdict.FAIL


def test_runner_error_captured() -> None:
    gate = Gate("QG-1", "lint", Stage.COMMIT, True,
                "tests.gates.test_runner:_ErrorGate", 60)
    reg = Registry([gate])
    results = Runner(reg).run_stage(Stage.COMMIT)
    assert results[0].verdict == Verdict.ERROR
    assert "boom" in results[0].message


def test_non_blocking_fail_does_not_block() -> None:
    gate = Gate("QG-1", "lint", Stage.COMMIT, False,
                "tests.gates.test_runner:_FailGate", 60)
    reg = Registry([gate])
    results = Runner(reg).run_stage(Stage.COMMIT)
    assert Runner.verdict(results) == Verdict.PASS


def test_empty_stage() -> None:
    reg = Registry([])
    assert Runner(reg).run_stage(Stage.DEPLOY) == []
