from pathlib import Path

from gates.registry import Gate, Registry, Stage


def test_load_empty_registry(tmp_path: Path) -> None:
    p = tmp_path / "registry.yaml"
    p.write_text("version: 1\ngates: []\n")
    reg = Registry.load(p)
    assert reg.gates == []


def test_load_one_gate(tmp_path: Path) -> None:
    p = tmp_path / "registry.yaml"
    p.write_text(
        "version: 1\n"
        "gates:\n"
        "  - id: QG-1\n"
        "    name: lint\n"
        "    stage: commit\n"
        "    blocking: true\n"
        "    impl: gates.impl.lint:LintGate\n"
        "    timeout_seconds: 60\n"
    )
    reg = Registry.load(p)
    assert len(reg.gates) == 1
    g = reg.gates[0]
    assert g.id == "QG-1"
    assert g.stage == Stage.COMMIT
    assert g.blocking is True


def test_for_stage_filters() -> None:
    gate_commit = Gate("QG-1", "lint", Stage.COMMIT, True,
                       "gates.impl.lint:LintGate", 60)
    gate_deploy = Gate("QG-9", "container", Stage.DEPLOY, True,
                       "gates.impl.container:ContainerGate", 300)
    reg = Registry([gate_commit, gate_deploy])
    assert reg.for_stage(Stage.COMMIT) == [gate_commit]
    assert reg.for_stage(Stage.DEPLOY) == [gate_deploy]
    assert reg.for_stage(Stage.PULL_REQUEST) == []


def test_get_by_id() -> None:
    gate = Gate("QG-1", "lint", Stage.COMMIT, True,
                "gates.impl.lint:LintGate", 60)
    reg = Registry([gate])
    assert reg.get("QG-1") is gate
    assert reg.get("QG-99") is None
