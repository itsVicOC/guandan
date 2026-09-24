"""Painted card widgets for the desktop GUI."""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from ..engine.card import Card, Suit
from ..engine.hand import sort_cards
from ..ui.formatting import rank_label, suit_symbol_plain
from ..ui.hand_organizer import HandGroup
from .theme import GOLD, GOLD_BRIGHT

CARD_WIDTH = 72
CARD_HEIGHT = 104
CARD_GAP = 8
CARD_OVERLAP_MIN = 32
SELECT_LIFT = 14
HAND_HEIGHT = CARD_HEIGHT + SELECT_LIFT + 10
NORMAL_SUIT_FONT_SIZE = 44
RED_SUIT_COLOR = "#c72f3e"
BLACK_SUIT_COLOR = "#15201c"
CARD_BACKGROUND = "#fbf8ef"


def sort_cards_for_display(cards: Sequence[Card], *, level: int) -> list[Card]:
    """Sort a hand for the table view, placing the current level after jokers.

    The engine's ordering remains unchanged.  Starting from its stable display
    order preserves the existing joker and same-rank suit ordering while the
    GUI-only grouping moves every level card between jokers and aces.
    """
    base = sort_cards(cards)
    return sorted(
        base,
        key=lambda card: (
            0 if card.is_joker else 1 if card.rank == level else 2,
        ),
    )


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
        return RED_SUIT_COLOR, "#d5a63b", "#fff7e8"
    if card.is_small_joker:
        return BLACK_SUIT_COLOR, "#d5a63b", "#fff7e8"
    if card.suit in (Suit.HEARTS, Suit.DIAMONDS):
        return RED_SUIT_COLOR, "#d7d1c5", "#fffaf5"
    return BLACK_SUIT_COLOR, "#d7d1c5", CARD_BACKGROUND


class CardButton(QPushButton):
    """Clickable playing card bound to its position in the rendered hand."""

    clicked_index = Signal(int)
    double_clicked_index = Signal(int)

    def __init__(
        self, index: int, card: Card, *, wild: bool = False,
        selected: bool = False, eligible: bool | None = None,
    ) -> None:
        super().__init__()
        self.index = index
        self.card = card
        self.wild = wild
        self.selected = selected
        self.eligible = eligible
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(CARD_WIDTH, CARD_HEIGHT))
        self.setFlat(True)
        self.setStyleSheet("QPushButton { border: 0; background: transparent; padding: 0; }")
        self.clicked.connect(self._emit_index)
        self.setMouseTracking(True)
        self._render()

    def _emit_index(self) -> None:
        self.clicked_index.emit(self.index)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked_index.emit(self.index)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def set_visual_state(
        self, *, wild: bool, selected: bool, eligible: bool | None = None
    ) -> None:
        changed = self.wild != wild or self.selected != selected or self.eligible != eligible
        self.wild = wild
        self.selected = selected
        self.eligible = eligible
        if changed:
            self._render()

    def _render(self) -> None:
        self.setText("")
        self.setAccessibleName(self._card_text().replace("\n", " "))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fg, border, bg = card_palette(self.card)
        if self.underMouse():
            border = GOLD.name()
        if self.selected:
            border = GOLD_BRIGHT.name()
            bg = "#fff4c8"
        elif self.eligible:
            border = GOLD_BRIGHT.name()

        shadow = self.rect().adjusted(5, 7, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 92))
        painter.drawRoundedRect(shadow, 9, 9)

        rect = self.rect().adjusted(2, 2, -4, -5)
        surface = QLinearGradient(rect.topLeft(), rect.bottomRight())
        surface.setColorAt(0.0, QColor("#ffffff") if not self.selected else QColor("#fff9d7"))
        surface.setColorAt(1.0, QColor(bg))
        if self.selected:
            painter.setPen(QPen(QColor(246, 207, 103, 90), 5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 9, 9)
        painter.setPen(QPen(QColor(border), 3 if self.selected else 1))
        painter.setBrush(surface)
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QPen(QColor(255, 255, 255, 175), 1))
        painter.drawLine(rect.left() + 8, rect.top() + 2, rect.right() - 8, rect.top() + 2)

        if self.card.is_joker:
            self._paint_joker(painter, rect, fg)
        else:
            self._paint_normal_card(painter, rect, fg)
        if self.wild:
            self._paint_wild_badge(painter, rect)
        if self.selected:
            self._paint_selected_badge(painter, rect)
        if self.eligible is False:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(4, 15, 13, 150))
            painter.drawRoundedRect(rect, 8, 8)
        painter.end()

    def _paint_normal_card(self, painter: QPainter, rect: QRect, color: str) -> None:
        painter.setPen(QColor(color))
        painter.setFont(QFont("Arial", 17, QFont.Weight.Black))
        painter.drawText(
            QRect(rect.left() + 7, rect.top() + 4, 30, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            rank_label(self.card),
        )
        painter.setFont(QFont("Times New Roman", 19, QFont.Weight.Black))
        painter.drawText(
            QRect(rect.left() + 7, rect.top() + 23, 26, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            suit_symbol_plain(self.card.suit),
        )
        painter.setFont(QFont("Times New Roman", NORMAL_SUIT_FONT_SIZE, QFont.Weight.Black))
        painter.drawText(
            QRect(rect.left() + 16, rect.top() + 29, rect.width() - 22, 50),
            Qt.AlignmentFlag.AlignCenter,
            suit_symbol_plain(self.card.suit),
        )
        painter.setFont(QFont("Times New Roman", 14, QFont.Weight.Black))
        painter.drawText(
            QRect(rect.right() - 25, rect.bottom() - 25, 18, 18),
            Qt.AlignmentFlag.AlignCenter,
            suit_symbol_plain(self.card.suit),
        )

    def _paint_joker(self, painter: QPainter, rect: QRect, color: str) -> None:
        painter.setPen(QColor(color))
        painter.setFont(QFont("PingFang SC", 15, QFont.Weight.Black))
        title = "大王" if self.card.is_big_joker else "小王"
        painter.drawText(
            QRect(rect.left() + 6, rect.top() + 8, rect.width() - 12, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
        )
        painter.setFont(QFont("Arial", 27, QFont.Weight.Black))
        painter.drawText(
            QRect(rect.left() + 8, rect.top() + 31, rect.width() - 16, 34),
            Qt.AlignmentFlag.AlignCenter,
            "★",
        )
        painter.setPen(QColor("#c4942f"))
        painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        painter.drawText(
            QRect(rect.left() + 5, rect.bottom() - 23, rect.width() - 10, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "BIG" if self.card.is_big_joker else "SMALL",
        )

    def _paint_selected_badge(self, painter: QPainter, rect: QRect) -> None:
        badge_rect = QRect(rect.right() - 22, rect.top() + 5, 16, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(GOLD_BRIGHT)
        painter.drawEllipse(badge_rect)
        painter.setPen(QColor("#121820"))
        painter.setFont(QFont("Arial", 10, QFont.Weight.Black))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "✓")

    def _paint_wild_badge(self, painter: QPainter, rect: QRect) -> None:
        badge = QRect(rect.left() + 4, rect.bottom() - 18, rect.width() - 8, 15)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#178a5d"))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("PingFang SC", 8, QFont.Weight.Bold))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "逢人配")

    def _card_text(self) -> str:
        selected = "已选择\n" if self.selected else ""
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
    """Single-row overlapping hand with lift-to-select interaction."""

    card_clicked = Signal(int)
    group_double_clicked = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._cards: list[Card] = []
        self._wild_card: Card | None = None
        self._selected: set[int] = set()
        self._eligible: set[int] | None = None
        self._group_starts: set[int] = set()
        self._group_ranges: list[tuple[int, int, HandGroup]] = []
        self._buttons: list[CardButton] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(HAND_HEIGHT)
        self.setMaximumHeight(HAND_HEIGHT)

    def set_cards(
        self,
        cards: list[Card],
        *,
        wild_card: Card | None,
        selected_indices: set[int],
        eligible_indices: set[int] | None = None,
        groups: Sequence[HandGroup] | None = None,
    ) -> None:
        cards_changed = cards != self._cards
        self._cards = list(cards)
        self._wild_card = wild_card
        self._selected = set(selected_indices)
        self._eligible = None if eligible_indices is None else set(eligible_indices)
        self._group_ranges = []
        position = 0
        for group in groups or ():
            end = position + len(group.cards)
            self._group_ranges.append((position, end, group))
            position = end
        self._group_starts = {start for start, _, _ in self._group_ranges if start}
        if cards_changed:
            self._rebuild_buttons()
        else:
            for index, card_button in enumerate(self._buttons):
                card_button.setEnabled(self._eligible is None or index in self._eligible)
                card_button.set_visual_state(
                    wild=self._is_wild(card_button.card),
                    selected=index in self._selected,
                    eligible=None if self._eligible is None else index in self._eligible,
                )
                card_button.setToolTip(self._card_tooltip(index))
        self._position_cards()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_cards()

    def sizeHint(self) -> QSize:
        natural_width = CARD_WIDTH + max(0, len(self._cards) - 1) * (CARD_WIDTH + CARD_GAP)
        return QSize(min(natural_width, 1200), HAND_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(CARD_WIDTH + CARD_OVERLAP_MIN * 7, HAND_HEIGHT)

    def _is_wild(self, card: Card) -> bool:
        return self._wild_card is not None and card == self._wild_card

    def _rebuild_buttons(self) -> None:
        for card_button in self._buttons:
            card_button.hide()
            card_button.deleteLater()
        self._buttons = []
        for index, card in enumerate(self._cards):
            card_button = CardButton(
                index,
                card,
                wild=self._is_wild(card),
                selected=index in self._selected,
                eligible=None if self._eligible is None else index in self._eligible,
            )
            card_button.setEnabled(self._eligible is None or index in self._eligible)
            card_button.setParent(self)
            card_button.clicked_index.connect(self.card_clicked.emit)
            card_button.double_clicked_index.connect(self.group_double_clicked.emit)
            card_button.setToolTip(self._card_tooltip(index))
            card_button.show()
            self._buttons.append(card_button)

    def _card_tooltip(self, index: int) -> str:
        for start, end, group in self._group_ranges:
            if start <= index < end:
                return (
                    f"{group.label} · 双击选中整组"
                    if group.pattern is not None else group.label
                )
        return ""

    def _position_cards(self) -> None:
        count = len(self._buttons)
        if not count:
            return
        usable_width = max(CARD_WIDTH, self.width() - 8)
        boundary_count = len(self._group_starts)
        # Cards in one combination form a compact, slightly stepped pile;
        # a wider gap makes each pile readable without a label above it.
        group_gap = (
            min(24, max(0, (usable_width - CARD_WIDTH - (count - 1) * 18)
                        // boundary_count))
            if boundary_count else 0
        )
        if count == 1:
            step: float = float(CARD_WIDTH + CARD_GAP)
        else:
            fit_step = (usable_width - CARD_WIDTH - boundary_count * group_gap) / (count - 1)
            step = min(34 if self._group_ranges else CARD_WIDTH + CARD_GAP,
                       max(18 if self._group_ranges else CARD_OVERLAP_MIN, fit_step))
        total_width = CARD_WIDTH + (count - 1) * step + boundary_count * group_gap
        start_x = max(4, int((self.width() - total_width) / 2))
        gaps_seen = 0
        pile_index = 0
        for index, card_button in enumerate(self._buttons):
            if index in self._group_starts:
                gaps_seen += 1
                pile_index = 0
            depth = min(pile_index * 2, 8) if self._group_ranges else 0
            y = (1 if index in self._selected else SELECT_LIFT + 1) + depth
            card_button.move(start_x + int(index * step) + gaps_seen * group_gap, y)
            card_button.raise_()
            pile_index += 1
        for index in sorted(self._selected):
            if 0 <= index < len(self._buttons):
                self._buttons[index].raise_()
        self.update()


class CardBackWidget(QWidget):
    """Compact card-back stack used by opponent seat panels."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(46, 58)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for offset in (6, 3, 0):
            rect = QRect(3 + offset, 2 + offset // 2, 34, 50)
            painter.setPen(QPen(QColor("#79bca9"), 1))
            back = QLinearGradient(rect.topLeft(), rect.bottomRight())
            back.setColorAt(0.0, QColor("#1a5a4c"))
            back.setColorAt(1.0, QColor("#0b2925"))
            painter.setBrush(back)
            painter.drawRoundedRect(rect, 5, 5)
            inner = rect.adjusted(4, 4, -4, -4)
            painter.setPen(QPen(QColor(169, 217, 196, 150), 1, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(inner, 3, 3)
            painter.drawLine(inner.left(), inner.center().y(), inner.center().x(), inner.top())
            painter.drawLine(inner.center().x(), inner.top(), inner.right(), inner.center().y())
            painter.drawLine(inner.right(), inner.center().y(), inner.center().x(), inner.bottom())
            painter.drawLine(inner.center().x(), inner.bottom(), inner.left(), inner.center().y())
        painter.end()


class MiniCardStrip(QWidget):
    """Small overlapping cards for the center trick history."""

    def __init__(
        self,
        *,
        card_width: int = 26,
        card_height: int = 34,
        minimum_width: int = 110,
    ) -> None:
        super().__init__()
        self._cards: tuple[Card, ...] = ()
        self._card_width = card_width
        self._card_height = card_height
        self.setMinimumWidth(minimum_width)
        self.setFixedHeight(card_height + 4)

    def set_cards(self, cards: tuple[Card, ...] | list[Card]) -> None:
        self._cards = tuple(cards)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._cards:
            painter.end()
            return
        card_width = self._card_width
        card_height = self._card_height
        step = min(
            max(20, card_width - 7),
            max(11, (self.width() - card_width) // max(1, len(self._cards) - 1)),
        )
        total_width = card_width + step * (len(self._cards) - 1)
        start_x = max(0, (self.width() - total_width) // 2)
        for index, card in enumerate(self._cards):
            x = start_x + index * step
            rect = QRect(x, 2, card_width, card_height)
            fg, _, bg = card_palette(card)
            painter.setPen(QPen(QColor("#cbc5b9"), 1))
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor(fg))
            painter.setFont(QFont("Arial", 11 if card_width >= 30 else 10, QFont.Weight.Black))
            label = "王" if card.is_joker else rank_label(card)
            painter.drawText(
                QRect(x + 3, 2, card_width - 6, max(16, card_height // 2 - 1)),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setFont(
                QFont("Times New Roman", 15 if card_width >= 30 else 13, QFont.Weight.Black)
            )
            symbol = "★" if card.is_joker else suit_symbol_plain(card.suit)
            painter.drawText(
                QRect(x + 3, card_height // 2, card_width - 6, card_height // 2 - 2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                symbol,
            )
        painter.end()


__all__ = [
    "BLACK_SUIT_COLOR",
    "CARD_HEIGHT",
    "CARD_WIDTH",
    "HAND_HEIGHT",
    "NORMAL_SUIT_FONT_SIZE",
    "RED_SUIT_COLOR",
    "CardBackWidget",
    "CardButton",
    "HandWidget",
    "MiniCardStrip",
    "card_palette",
    "gui_suit_name",
]
