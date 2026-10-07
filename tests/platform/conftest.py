from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"


@pytest.fixture
def examples() -> Path:
    return EXAMPLES


@pytest.fixture(autouse=True)
def _no_proxy_for_localhost(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
