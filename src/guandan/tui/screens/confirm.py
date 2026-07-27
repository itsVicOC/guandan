"""Reusable confirmation and card-choice modals."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ...engine.card import Card
from ...ui.formatting import card_label


class ConfirmModal(ModalScreen[str]):
    """Return a stable action id for destructive or conflicting choices."""

    DEFAULT_CSS = """
    ConfirmModal { align: center middle; }
    #confirm-box {
        width: 62;
        height: auto;
        max-height: 22;
        padding: 1 2;
        border: thick #d6b35a;
        background: #18211d;
    }
    #confirm-title { text-style: bold; color: #ffd978; margin-bottom: 1; }
    #confirm-message { margin-bottom: 1; }
    .confirm-action { width: 100%; margin-top: 1; }
    """

    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(
        self,
        title: str,
        message: str,
        actions: Sequence[
            tuple[str, str, Literal["default", "primary", "success", "warning", "error"]]
        ],
    ) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._actions = tuple(actions)

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._title, id="confirm-title")
            yield Static(self._message, id="confirm-message")
            for action_id, label, variant in self._actions:
                yield Button(
                    label,
                    id=f"confirm-{action_id}",
                    variant=variant,
                    classes="confirm-action",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action_id = (event.button.id or "").removeprefix("confirm-")
        self.dismiss(action_id)

    def action_cancel(self) -> None:
        self.dismiss("cancel")


class TributeChoiceModal(ModalScreen[Card | None]):
    """Let the human choose one legal tribute or return card."""

    DEFAULT_CSS = """
    TributeChoiceModal { align: center middle; }
    #tribute-choice-box {
        width: 54;
        height: 80%;
        max-height: 30;
        padding: 1 2;
        border: thick #d6b35a;
        background: #18211d;
    }
    #tribute-choice-title { text-style: bold; color: #ffd978; margin-bottom: 1; }
    #tribute-choice-list { height: 1fr; }
    .tribute-card { width: 100%; margin-bottom: 1; }
    #tribute-cancel { width: 100%; margin-top: 1; }
    """

    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, kind: str, cards: Sequence[Card]) -> None:
        super().__init__()
        self._kind = kind
        self._cards = tuple(cards)

    def compose(self) -> ComposeResult:
        verb = "进贡" if self._kind == "tribute" else "还贡"
        with Vertical(id="tribute-choice-box"):
            yield Static(f"选择{verb}牌", id="tribute-choice-title")
            with VerticalScroll(id="tribute-choice-list"):
                for index, card in enumerate(self._cards):
                    yield Button(
                        card_label(card),
                        id=f"tribute-card-{index}",
                        classes="tribute-card",
                    )
            yield Button("取消", id="tribute-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("tribute-card-"):
            self.dismiss(self._cards[int(button_id.rsplit("-", 1)[1])])
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
