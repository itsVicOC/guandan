"""Card widgets for the desktop GUI."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QPushButton, QSizePolicy, QWidget

from ..engine.card import Card, Suit
from ..ui.formatting import rank_label, suit_symbol_plain

CARD_WIDTH = 74
CARD_HEIGHT = 102
CARD_GAP = 8
NORMAL_SUIT_FONT_SIZE = 46
RED_SUIT_COLOR = "#c1121f"
BLACK_SUIT_COLOR = "#111111"
CARD_BACKGROUND = "#fffdf7"


def gui_suit_name(suit: Suit) -> str:
    return {
        Suit.HEARTS: "红心",
        Suit.DIAMONDS: "方片",
        Suit.SPADES: "黑桃",
        Suit.CLUBS: "梅花",
        Suit.BIG_JOKER: "大王",
        Suit.SMALL_JOKER: "小王",
    }[suit]


def card_palette(card: Card) -> tuple[str, str, str]:
    """Return text, border and background colors."""
    if card.is_big_joker:
        return RED_SUIT_COLOR, "#f59e0b", "#fff7ed"
    if card.is_small_joker:
        return BLACK_SUIT_COLOR, "#f59e0b", "#fff7ed"
    if card.suit in (Suit.HEARTS, Suit.DIAMONDS):
        return RED_SUIT_COLOR, RED_SUIT_COLOR, "#fffafa"
    return BLACK_SUIT_COLOR, BLACK_SUIT_COLOR, CARD_BACKGROUND


class CardButton(QPushButton):
    """Clickable playing card bound to its position in the rendered hand."""

    clicked_index = Signal(int)

    def __init__(self, index: int, card: Card, *, wild: bool = False, selected: bool = False) -> None:
        super().__init__()
        self.index = index
        self.card = card
        self.wild = wild
        self.selected = selected
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(CARD_WIDTH, CARD_HEIGHT))
        self.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.clicked.connect(self._emit_index)
        self.setMouseTracking(True)
        self._render()

    def _emit_index(self) -> None:
        self.clicked_index.emit(self.index)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._render()

    def _render(self) -> None:
        self.setText("")
        self.setAccessibleName(self._card_text().replace("\n", " "))
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fg, border, bg = card_palette(self.card)
        if self.underMouse():
            border = "#f59e0b"
            bg = "#fffbea"
        if self.selected:
            border = "#f59e0b"
            bg = "#fff7cc"

        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.setPen(QPen(QColor(border), 4 if self.selected else 2))
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, 8, 8)

        if self.selected:
            self._paint_selected_badge(painter, rect)
        if self.card.is_joker:
            self._paint_joker(painter, rect, fg)
        else:
            self._paint_normal_card(painter, rect, fg)
        if self.wild:
            self._paint_wild_badge(painter, rect)
        painter.end()

    def _paint_normal_card(self, painter: QPainter, rect: QRect, color: str) -> None:
        painter.setPen(QColor(color))
        painter.setFont(QFont("Arial", 18, QFont.Weight.Black))
        painter.drawText(
            QRect(rect.left() + 6, rect.top() + 4, rect.width() - 12, 24),
            Qt.AlignmentFlag.AlignCenter,
            rank_label(self.card),
        )
        painter.setFont(QFont("Times New Roman", NORMAL_SUIT_FONT_SIZE, QFont.Weight.Black))
        painter.drawText(
            QRect(rect.left(), rect.top() + 24, rect.width(), 50),
            Qt.AlignmentFlag.AlignCenter,
            suit_symbol_plain(self.card.suit),
        )
        painter.setFont(QFont("PingFang SC", 15, QFont.Weight.Bold))
        painter.drawText(
            QRect(rect.left() + 4, rect.bottom() - 24, rect.width() - 8, 20),
            Qt.AlignmentFlag.AlignCenter,
            gui_suit_name(self.card.suit),
        )

    def _paint_joker(self, painter: QPainter, rect: QRect, color: str) -> None:
        painter.setPen(QColor(color))
        painter.setFont(QFont("Arial", 18, QFont.Weight.Black))
        title = "大王" if self.card.is_big_joker else "小王"
        painter.drawText(
            QRect(rect.left(), rect.top() + 18, rect.width(), 28),
            Qt.AlignmentFlag.AlignCenter,
            title,
        )
        painter.setFont(QFont("Arial", 13, QFont.Weight.Black))
        label = "JOKER" if self.card.is_big_joker else "joker"
        painter.drawText(
            QRect(rect.left(), rect.top() + 50, rect.width(), 26),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )

    def _paint_selected_badge(self, painter: QPainter, rect: QRect) -> None:
        badge_rect = QRect(rect.right() - 22, rect.top() + 5, 16, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f59e0b"))
        painter.drawEllipse(badge_rect)
        painter.setPen(QColor("#132019"))
        painter.setFont(QFont("Arial", 10, QFont.Weight.Black))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "✓")

    def _paint_wild_badge(self, painter: QPainter, rect: QRect) -> None:
        badge = QRect(rect.left(), rect.bottom() - 17, rect.width(), 17)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#16a34a"))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "逢人配")

    def _card_text(self) -> str:
        selected = "✓\n" if self.selected else ""
        if self.card.is_big_joker:
            base = "大王\nJOKER"
        elif self.card.is_small_joker:
            base = "小王\njoker"
        else:
            suit_cn = gui_suit_name(self.card.suit)
            base = f"{suit_cn}\n{suit_symbol_plain(self.card.suit)} {rank_label(self.card)}"
        if self.wild:
            base += "\n逢人配"
        return selected + base


class HandWidget(QWidget):
    """Responsive two-to-four-row hand display."""

    card_clicked = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._cards: list[Card] = []
        self._wild_card: Card | None = None
        self._selected: set[int] = set()
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(CARD_GAP)
        self._layout.setVerticalSpacing(CARD_GAP)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_cards(
        self,
        cards: list[Card],
        *,
        wild_card: Card | None,
        selected_indices: set[int],
    ) -> None:
        self._cards = list(cards)
        self._wild_card = wild_card
        self._selected = set(selected_indices)
        self._rebuild()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rebuild()

    def _cards_per_row(self) -> int:
        width = max(self.width(), CARD_WIDTH * 8)
        return max(8, min(18, width // (CARD_WIDTH + CARD_GAP)))

    def _row_count(self, per_row: int | None = None) -> int:
        if not self._cards:
            return 1
        cards_per_row = per_row or self._cards_per_row()
        return (len(self._cards) + cards_per_row - 1) // cards_per_row

    def _content_height(self, per_row: int | None = None) -> int:
        rows = self._row_count(per_row)
        return rows * CARD_HEIGHT + max(0, rows - 1) * CARD_GAP

    def sizeHint(self) -> QSize:
        per_row = self._cards_per_row()
        width = min(max(len(self._cards), 8), per_row) * (CARD_WIDTH + CARD_GAP)
        return QSize(width, self._content_height(per_row))

    def minimumSizeHint(self) -> QSize:
        return QSize(CARD_WIDTH * 8, self._content_height())

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild(self) -> None:
        self._clear_layout()
        per_row = self._cards_per_row()
        height = self._content_height(per_row)
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        for index, card in enumerate(self._cards):
            button = CardButton(
                index,
                card,
                wild=self._wild_card is not None and card == self._wild_card,
                selected=index in self._selected,
            )
            button.clicked_index.connect(self.card_clicked.emit)
            row = index // per_row
            col = index % per_row
            self._layout.addWidget(button, row, col)
        self._layout.setColumnStretch(per_row, 1)
        self.updateGeometry()
