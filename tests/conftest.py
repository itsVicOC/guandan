"""pytest 全局配置。"""
import sys
from pathlib import Path

import pytest

# 确保 src/ 在 sys.path 中能找到包
src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))


@pytest.fixture(autouse=True)
def isolated_user_data(tmp_path, monkeypatch):
    """Tests and their subprocesses never read or write the real user profile."""
    monkeypatch.setenv("GUANDAN_DATA_DIR", str(tmp_path / "user-data"))
