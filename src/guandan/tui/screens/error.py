"""简单的错误信息 Modal。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ErrorModal(ModalScreen):
    """显示一段错误/提示消息 + OK 按钮。"""

    DEFAULT_CSS = """
    ErrorModal {
        align: center middle;
    }
    #error-box {
        width: 60;
        height: auto;
        border: thick $error;
        padding: 1 2;
        background: $surface;
    }
    #error-title {
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }
    #error-body {
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        ("escape", "close", "关闭"),
        ("enter", "close", "关闭"),
    ]

    def __init__(self, message: str, *, title: str = "提示") -> None:
        super().__init__()
        self._message = message
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="error-box"):
            yield Static(self._title, id="error-title")
            yield Static(self._message, id="error-body")
            yield Button("OK", id="error-ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "error-ok":
            self.dismiss()

    def action_close(self) -> None:
        self.dismiss()
