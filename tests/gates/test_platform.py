from gates.impl.lint import LintGate
from gates.impl.platform import PlatformLintGate, PlatformUnitGate
from gates.impl.unit import UnitGate
from gates.registry import Registry


def test_platform_gates_are_scoped_to_the_engine() -> None:
    assert issubclass(PlatformLintGate, LintGate)
    assert PlatformLintGate.TARGETS == ["src/trufax", "tests/platform"]
    assert issubclass(PlatformUnitGate, UnitGate)
    assert PlatformUnitGate.TEST_PATH == "tests/platform"
    assert PlatformUnitGate.COVERAGE_SOURCE == "src/trufax"


def test_registry_lists_platform_gates() -> None:
    ids = [g.id for g in Registry.load("gates/registry.yaml").gates]
    assert ids == ["QG-1", "QG-2", "QG-3", "QG-4"]
