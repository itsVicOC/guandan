"""pytest 全局配置。"""
import sys
from pathlib import Path

# 确保 src/ 在 sys.path 中能找到包
src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src))
