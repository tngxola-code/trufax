"""Gate registry: loads gate definitions from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class Stage(str, Enum):
    COMMIT = "commit"
    PULL_REQUEST = "pull-request"
    DEPLOY = "deploy"


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


@dataclass(frozen=True)
class Gate:
    id: str
    name: str
    stage: Stage
    blocking: bool
    impl: str
    timeout_seconds: int
    description: str = ""


@dataclass
class GateResult:
    gate: Gate
    verdict: Verdict
    duration_ms: int
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class Registry:
    def __init__(self, gates: list[Gate]):
        self.gates = gates

    @classmethod
    def load(cls, path: str | Path) -> "Registry":
        data = yaml.safe_load(Path(path).read_text()) or {}
        raw_gates = data.get("gates", [])
        gates = [
            Gate(
                id=g["id"],
                name=g["name"],
                stage=Stage(g["stage"]),
                blocking=bool(g.get("blocking", True)),
                impl=g["impl"],
                timeout_seconds=int(g.get("timeout_seconds", 300)),
                description=g.get("description", ""),
            )
            for g in raw_gates
        ]
        return cls(gates)

    def for_stage(self, stage: Stage) -> list[Gate]:
        return [g for g in self.gates if g.stage == stage]

    def get(self, gate_id: str) -> Gate | None:
        return next((g for g in self.gates if g.id == gate_id), None)
