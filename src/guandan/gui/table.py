"""PySide6 desktop GUI for the local Guandan game."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from ..engine.card import Card
from ..engine.events import Event, Pass, TributeReturned, TributeSent, TurnPlayed
from ..engine.hand import Pattern
from ..engine.state import SEAT_NAMES, GameState
from ..ui.formatting import card_label, pattern_type_label
from .cards import MiniCardStrip
from .theme import GOLD_BRIGHT, TEXT_MUTED
from .widgets import set_property


class GameArena(QFrame):
    """Painted felt surface behind the four seats and current trick."""

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = self.rect().adjusted(1, 1, -1, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 125))
        painter.drawRoundedRect(outer.translated(0, 3), 23, 23)

        rim = QLinearGradient(outer.topLeft(), outer.bottomRight())
        rim.setColorAt(0.0, QColor("#5b724f"))
        rim.setColorAt(0.45, QColor("#af8d43"))
        rim.setColorAt(1.0, QColor("#2c5c49"))
        painter.setBrush(rim)
        painter.drawRoundedRect(outer, 23, 23)

        inner = outer.adjusted(4, 4, -4, -4)
        felt = QRadialGradient(inner.center(), max(inner.width(), inner.height()) * 0.68)
        felt.setColorAt(0.0, QColor("#09654c"))
        felt.setColorAt(0.7, QColor("#064633"))
        felt.setColorAt(1.0, QColor("#032c23"))
        painter.setPen(QPen(QColor("#174c3c"), 1))
        painter.setBrush(felt)
        painter.drawRoundedRect(inner, 20, 20)

        field = inner.adjusted(12, 12, -12, -12)
        painter.setPen(QPen(QColor(147, 203, 179, 58), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(field, 15, 15)
        center = inner.center()
        painter.setPen(QPen(QColor(224, 196, 123, 42), 1))
        painter.drawEllipse(center, min(190, inner.width() // 4), min(105, inner.height() // 3))
        painter.drawEllipse(center, min(168, inner.width() // 5), min(84, inner.height() // 4))
        painter.setPen(QColor(235, 216, 166, 28))
        painter.setFont(QFont("Songti SC", 52, QFont.Weight.Black))
        painter.drawText(
            QRect(center.x() - 100, center.y() - 38, 200, 76),
            Qt.AlignmentFlag.AlignCenter,
            "掼",
        )
        painter.end()


class SeatPanel(QFrame):
    def __init__(self, *, human: bool = False) -> None:
        super().__init__()
        self._human = human
        self.setObjectName("seatPanel")
        self.setMinimumSize(174, 50)
        self.setMaximumHeight(56)
        set_property(self, "human", human)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(9)

        self.avatar = QLabel("-")
        self.avatar.setObjectName("seatAvatar")
        self.avatar.setFixedSize(32, 32)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.avatar)

        labels = QVBoxLayout()
        labels.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("seatName")
        self.detail = QLabel("")
        self.detail.setObjectName("seatMeta")
        self.claim_badge = QLabel("")
        self.claim_badge.setObjectName("claimBadge")
        self.claim_badge.hide()
        name_line = QHBoxLayout()
        name_line.setSpacing(4)
        name_line.addWidget(self.title, 1)
        name_line.addWidget(self.claim_badge)
        labels.addLayout(name_line)
        labels.addWidget(self.detail)
        layout.addLayout(labels, 1)

    def update_state(
        self, seat: int, hand_size: int, finished: bool, is_turn: bool,
        ai_name: str, *, thinking: bool = False,
    ) -> None:
        team = "gold" if seat % 2 == 0 else "cyan"
        self.avatar.setText(SEAT_NAMES[seat])
        set_property(self.avatar, "team", team)
        set_property(self, "active", is_turn)
        set_property(self.detail, "active", is_turn)
        self.title.setText(f"{SEAT_NAMES[seat]}家" + (" · 你" if self._human else ""))
        if finished:
            meta = "已出完"
        elif is_turn:
            meta = f"● {'思考中' if thinking else '行动中'} · {hand_size} 张"
        else:
            meta = f"{ai_name} · {hand_size} 张"
        self.detail.setText(meta)
        claim = self._claim_text(hand_size) if not finished else ""
        self.claim_badge.setText(claim)
        self.claim_badge.setVisible(bool(claim))

    @staticmethod
    def _claim_text(hand_size: int) -> str:
        if hand_size == 1:
            return "报单"
        if hand_size == 2:
            return "报双"
        if 0 < hand_size <= 10:
            return f"报{hand_size}张"
        return ""


class SeatPlayArea(QFrame):
    """Upright public cards immediately in front of one seat."""
    def __init__(self, seat: int) -> None:
        super().__init__()
        self.seat = seat
        self.setObjectName("seatPlayArea")
        self.setMinimumWidth(192)
        self.setFixedHeight(70)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(2)
        header = QHBoxLayout()
        header.setSpacing(4)
        self.seat_label = QLabel(f"{SEAT_NAMES[seat]}家")
        self.seat_label.setObjectName("muted")
        self.action_label = QLabel("等待")
        self.action_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.cards = MiniCardStrip(card_width=34, card_height=40, minimum_width=178)
        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #afc5b9; font-size: 16px; font-weight: 700;")
        self.card_slot = QStackedWidget()
        self.card_slot.setFixedHeight(44)
        self.card_slot.addWidget(self.cards)
        self.card_slot.addWidget(self.empty_label)
        header.addWidget(self.seat_label)
        header.addWidget(self.action_label, 1)
        layout.addLayout(header)
        layout.addWidget(self.card_slot)

    def update_action(
        self,
        action: tuple[str, Pattern | None] | None,
        *,
        is_top: bool,
        is_turn: bool,
    ) -> None:
        prefix = "最大 · " if is_top else ""
        if action is None:
            self.action_label.setText("等待")
            self.cards.set_cards(())
        else:
            kind, pattern = action
            if kind == "pass":
                self.action_label.setText("过牌")
                self.cards.set_cards(())
            elif pattern is not None:
                self.action_label.setText(prefix + pattern_type_label(pattern.type))
                self.cards.set_cards(pattern.cards)
            else:
                self.action_label.setText("等待")
                self.cards.set_cards(())
        has_cards = action is not None and action[0] == "play" and action[1] is not None
        self.empty_label.setText("过牌" if action is not None and action[0] == "pass" else "")
        self.card_slot.setCurrentWidget(self.cards if has_cards else self.empty_label)
        color = GOLD_BRIGHT.name() if is_top else TEXT_MUTED.name()
        self.seat_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 800;")
        self.action_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 750;")
        set_property(self, "top", is_top)
        set_property(self, "turn", is_turn)


class ActivityRail(QFrame):
    """Compact public action trail that keeps the flow of play readable."""

    _MAX_VISIBLE = 5

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("activityRail")
        self.setMinimumWidth(280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(3)
        title = QLabel("最近行动")
        title.setObjectName("activityTitle")
        layout.addWidget(title)
        self.lines: list[QLabel] = []
        for _ in range(self._MAX_VISIBLE):
            line = QLabel("—")
            line.setObjectName("activityLine")
            line.setMinimumHeight(20)
            line.setWordWrap(False)
            layout.addWidget(line)
            self.lines.append(line)
        layout.addStretch(1)
        self.counter = QLabel("尚未出牌")
        self.counter.setObjectName("activityCounter")
        layout.addWidget(self.counter)

    def update_events(self, events: list[Event]) -> None:
        public_actions = [
            event for event in events if isinstance(event, (TurnPlayed, Pass))
        ]
        recent = public_actions[-self._MAX_VISIBLE :]
        empty_count = self._MAX_VISIBLE - len(recent)
        rows: list[tuple[str, bool]] = [("—", False)] * empty_count
        first_number = len(public_actions) - len(recent) + 1
        for offset, event in enumerate(recent):
            number = first_number + offset
            if isinstance(event, Pass):
                text = f"{number:02}  {SEAT_NAMES[event.player]}家 · 过牌"
            else:
                cards = " ".join(card_label(card) for card in event.pattern.cards)
                text = (
                    f"{number:02}  {SEAT_NAMES[event.player]}家 · "
                    f"{pattern_type_label(event.pattern.type)} {cards}"
                )
            rows.append((text, offset == len(recent) - 1))

        for label, (text, latest) in zip(self.lines, rows):
            label.setText(text)
            label.setToolTip(text if text != "—" else "")
            set_property(label, "latest", latest)
        self.counter.setText(f"本局共 {len(public_actions)} 次公开行动" if public_actions else "尚未出牌")


class TablePanel(GameArena):
    def __init__(self, *, human: int = 0) -> None:
        super().__init__()
        self.setObjectName("gameArena")
        grid = QGridLayout(self)
        grid.setContentsMargins(18, 10, 18, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        self.seat_panels = {seat: SeatPanel(human=seat == human) for seat in range(4)}
        self.play_areas = {seat: SeatPlayArea(seat) for seat in range(4)}
        # These aliases keep the label/card access used by the page and tooling.
        self.trick_rows = self.play_areas
        self.rows = {seat: area.action_label for seat, area in self.play_areas.items()}
        left, opposite, right = (human + 1) % 4, (human + 2) % 4, (human - 1) % 4
        for seat, seat_pos, cards_pos in (
            (opposite, (0, 2), (1, 2)), (left, (2, 0), (2, 1)),
            (right, (2, 4), (2, 3)), (human, (4, 2), (3, 2)),
        ):
            grid.addWidget(self.seat_panels[seat], *seat_pos)
            alignment = (Qt.AlignmentFlag.AlignTop if seat == opposite else
                         Qt.AlignmentFlag.AlignBottom if seat == human else Qt.AlignmentFlag(0))
            grid.addWidget(self.play_areas[seat], *cards_pos, alignment)
        for column in range(5):
            grid.setColumnStretch(column, 2 if column == 2 else 1)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(3, 1)

        center = QFrame()
        center.setObjectName("trickPanel")
        layout = QVBoxLayout(center)
        layout.setContentsMargins(9, 5, 9, 5)
        layout.setSpacing(3)
        header = QHBoxLayout()
        self.title = QLabel("当前牌墩")
        self.title.setObjectName("accentTitle")
        self.phase_badge = QLabel("等待")
        self.phase_badge.setObjectName("trickPhase")
        self.trick_meta = QLabel("等待先手")
        self.trick_meta.setObjectName("muted")
        self.trick_meta.setWordWrap(True)
        self.trick_meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.phase_badge)
        layout.addLayout(header)
        layout.addWidget(self.trick_meta)
        grid.addWidget(center, 2, 2)

        self.activity_button = QPushButton("最近行动 ▾")
        self.activity_button.setObjectName("tableActivityButton")
        self.activity_button.clicked.connect(self.show_activity)
        grid.addWidget(self.activity_button, 0, 4, Qt.AlignmentFlag.AlignRight)
        self.activity_popup = QFrame(self, Qt.WindowType.Popup)
        self.activity_popup.setObjectName("activityPopup")
        popup_layout = QVBoxLayout(self.activity_popup)
        popup_layout.setContentsMargins(0, 0, 0, 0)
        self.activity = ActivityRail()
        popup_layout.addWidget(self.activity)

        # Reparented into the page's HUD so tribute never competes with cards.
        self.tribute_banner = QFrame()
        self.tribute_banner.setObjectName("tributeBanner")
        tribute_layout = QHBoxLayout(self.tribute_banner)
        tribute_layout.setContentsMargins(0, 0, 0, 0)
        tribute_layout.setSpacing(8)
        self.tribute_text = QLabel()
        self.tribute_text.setObjectName("tributeText")
        self.tribute_text.setWordWrap(True)
        self.tribute_cards = MiniCardStrip()
        tribute_layout.addWidget(self.tribute_text, 1)
        tribute_layout.addWidget(self.tribute_cards)
        self.tribute_banner.hide()

    def show_activity(self) -> None:
        self.activity_popup.adjustSize()
        anchor = self.activity_button.mapToGlobal(self.activity_button.rect().bottomRight())
        self.activity_popup.move(anchor.x() - self.activity_popup.width(), anchor.y() + 4)
        self.activity_popup.show()

    def update_table(
        self,
        state: GameState,
        actions: dict[int, tuple[str, Pattern | None]],
        table_players: list[int],
        tribute_events: tuple[Event, ...],
        tribute_notice: str,
        *,
        awaiting_tribute: bool = False,
    ) -> None:
        self._update_tribute(tribute_events, tribute_notice)
        top_player = table_players[-1] if state.table and table_players else self._last_top_player(state)
        if awaiting_tribute:
            self.title.setText("第 1 墩")
            self.phase_badge.setText("贡还中")
            set_property(self.phase_badge, "phase", "waiting")
            self.trick_meta.setText("贡还确认后开始出牌")
        elif state.finished:
            self.title.setText(f"第 {max(1, state.trick_number + bool(state.table))} 墩")
            self.phase_badge.setText("已结束")
            set_property(self.phase_badge, "phase", "cleared")
            self.trick_meta.setText(
                f"本局结束 · 最后出牌：{SEAT_NAMES[top_player]}家"
                if top_player is not None else "本局结束"
            )
        elif state.table:
            self.title.setText(f"第 {state.trick_number + 1} 墩")
            self.phase_badge.setText("进行中")
            set_property(self.phase_badge, "phase", "active")
            self.trick_meta.setText(
                f"最大：{SEAT_NAMES[top_player]}家" if top_player is not None else "等待先手"
            )
        elif actions and top_player is not None:
            self.title.setText(f"第 {max(1, state.trick_number)} 墩")
            self.phase_badge.setText("已收牌")
            set_property(self.phase_badge, "phase", "cleared")
            starter = state.next_trick_starter if state.next_trick_starter is not None else state.turn_index
            if starter == top_player:
                self.trick_meta.setText(f"{SEAT_NAMES[top_player]}家收牌并先手")
            else:
                self.trick_meta.setText(
                    f"{SEAT_NAMES[top_player]}家收牌 · {SEAT_NAMES[starter]}家接风"
                )
        else:
            self.title.setText(f"第 {state.trick_number + 1} 墩")
            self.phase_badge.setText("等待")
            set_property(self.phase_badge, "phase", "waiting")
            self.trick_meta.setText(f"等待 {SEAT_NAMES[state.turn_index]}家先手")
        for seat, row in self.trick_rows.items():
            row.update_action(
                actions.get(seat),
                is_top=seat == top_player and actions.get(seat, (None,))[0] == "play",
                is_turn=not awaiting_tribute and not state.finished and seat == state.turn_index,
            )
        self.activity.update_events(state.history)
        if self.activity_popup.isVisible():
            self.activity_popup.adjustSize()

    @staticmethod
    def _last_top_player(state: GameState) -> int | None:
        for event in reversed(state.history):
            if isinstance(event, TurnPlayed):
                return event.player
        return None

    def _update_tribute(self, events: tuple[Event, ...], notice: str) -> None:
        cards: list[Card] = []
        for event in events:
            if isinstance(event, (TributeSent, TributeReturned)):
                cards.append(event.card)
        self.tribute_text.setText(notice)
        self.tribute_cards.set_cards(cards)
        self.tribute_cards.setVisible(bool(cards))
        self.tribute_banner.show()
