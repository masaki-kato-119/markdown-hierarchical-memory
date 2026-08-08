import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest


@pytest.fixture(autouse=True)
def _no_ambient_actor(monkeypatch):
    """MDMEM_ACTOR is set per client in mcp.json, so a developer running the suite
    with it exported would otherwise change what the log records under."""
    monkeypatch.delenv("MDMEM_ACTOR", raising=False)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "memory"
    r.mkdir()
    return r
