"""QG-3 and QG-4: the same lint and unit-test gates, scoped to the platform engine.

The engine (src/trufax) and its tests were added lint-clean, type-checked and with
coverage above the threshold, so they are held to the gates from the start. The
Québec extractor (src/qc_property) stays outside these gates until it is cleaned up.
"""

from __future__ import annotations

from typing import ClassVar

from gates.impl.lint import LintGate
from gates.impl.unit import UnitGate


class PlatformLintGate(LintGate):
    TARGETS: ClassVar[list[str]] = ["src/trufax", "tests/platform"]


class PlatformUnitGate(UnitGate):
    TEST_PATH: ClassVar[str] = "tests/platform"
    COVERAGE_SOURCE: ClassVar[str] = "src/trufax"
    COVERAGE_THRESHOLD: ClassVar[int] = 80
