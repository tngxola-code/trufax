"""Gate reporter: renders results as text or JSON."""

from __future__ import annotations

import json

from gates.registry import GateResult, Verdict

ICON = {
    Verdict.PASS: "PASS",
    Verdict.FAIL: "FAIL",
    Verdict.SKIP: "SKIP",
    Verdict.ERROR: "ERR ",
}


def render_text(results: list[GateResult]) -> str:
    if not results:
        return "(no gates in this stage)"
    lines = []
    for r in results:
        tag = ICON[r.verdict]
        block = "blocking" if r.gate.blocking else "non-blocking"
        lines.append(
            f"[{tag}] {r.gate.id} {r.gate.name:<28} "
            f"{r.duration_ms:>6}ms  ({block})"
        )
        if r.message:
            lines.append(f"        {r.message}")
    return "\n".join(lines)


def render_json(results: list[GateResult]) -> str:
    return json.dumps(
        [
            {
                "id": r.gate.id,
                "name": r.gate.name,
                "stage": r.gate.stage.value,
                "blocking": r.gate.blocking,
                "verdict": r.verdict.value,
                "duration_ms": r.duration_ms,
                "message": r.message,
                "details": r.details,
            }
            for r in results
        ],
        indent=2,
    )


def emit(results: list[GateResult], fmt: str = "text") -> int:
    out = render_text(results) if fmt == "text" else render_json(results)
    print(out)
    blocking_failures = [
        r for r in results if r.gate.blocking and r.verdict != Verdict.PASS
    ]
    return 1 if blocking_failures else 0
