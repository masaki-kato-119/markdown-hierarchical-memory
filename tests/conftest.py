import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "memory"
    r.mkdir()
    return r
