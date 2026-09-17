"""Gate runner: executes gates and aggregates verdicts."""

from __future__ import annotations

import importlib
import time
from typing import Protocol

from gates.registry import Gate, GateResult, Registry, Stage, Verdict


class GateImpl(Protocol):
    def run(self, gate: Gate) -> GateResult: ...


def load_impl(dotted_path: str) -> GateImpl:
    module_path, class_name = dotted_path.split(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


class Runner:
    def __init__(self, registry: Registry):
        self.registry = registry

    def run_stage(self, stage: Stage) -> list[GateResult]:
        gates = self.registry.for_stage(stage)
        if not gates:
            return []
        return [self._run_one(g) for g in gates]

    def _run_one(self, gate: Gate) -> GateResult:
        start = time.monotonic()
        try:
            impl = load_impl(gate.impl)
            result = impl.run(gate)
            result.duration_ms = int((time.monotonic() - start) * 1000)
            return result
        # A gate must never crash the runner. Any exception from a gate
        # implementation is captured as an ERROR verdict for that gate.
        except Exception as exc:  # noqa: BLE001
            return GateResult(
                gate=gate,
                verdict=Verdict.ERROR,
                duration_ms=int((time.monotonic() - start) * 1000),
                message=str(exc),
            )

    @staticmethod
    def verdict(results: list[GateResult]) -> Verdict:
        if any(r.verdict == Verdict.ERROR for r in results if r.gate.blocking):
            return Verdict.ERROR
        if any(r.verdict == Verdict.FAIL for r in results if r.gate.blocking):
            return Verdict.FAIL
        return Verdict.PASS
