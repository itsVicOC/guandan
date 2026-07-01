"""GUI entrypoint.

PySide6 is an optional dependency. Keeping the import lazy lets CLI/TUI users run
the project without installing Qt.
"""
from __future__ import annotations


def main() -> int:
    try:
        from .window import run_gui
    except ModuleNotFoundError as exc:
        if not (exc.name and exc.name.startswith("PySide6")):
            raise
        print(
            "启动 GUI 需要安装 PySide6：请运行 "
            'pip install -e ".[gui]" 后再执行 guandan-gui。'
        )
        print(f"导入失败：{exc}")
        return 2
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
