"""命令行 CLI：跑通一局完整对局。"""
from __future__ import annotations

import argparse
import random
import sys

from .ai import AINotImplementedError, make_strategy, play_or_pass
from .engine.card import RANK_2, RANK_A, Card
from .engine.events import TurnPlayed
from .engine.hand import Pattern, PatternType, sort_cards
from .engine.rules.patterns import find_complete_pattern
from .engine.state import (
    SEAT_NAMES,
    IllegalPlayError,
    make_initial_state,
    pass_turn,
    play_pattern,
)

# ---- AI 策略（v0.3.0 M2：从 guandan.ai 注入） ----


# AI 行动通过 `guandan.ai.play_or_pass` 统一；保留 `_ai_play` 为薄包装
# 以兼容潜在的内嵌调用。
def _ai_play(state, player: int, strategy, rng: random.Random) -> bool:
    return play_or_pass(state, player, strategy, rng)


# ---- 真人交互 ----


def _pattern_short(p: Pattern) -> str:
    if p.type == PatternType.SINGLE:
        return p.cards[0].short
    if p.type == PatternType.PAIR:
        return f"对{p.cards[0].rank_display}" if hasattr(p.cards[0], "rank_display") else f"对{p.cards[0].short}"
    cards_str = " ".join(c.short for c in p.cards)
    return f"{p.type.value}[{cards_str}]"


def _format_hand(hand: list[Card]) -> str:
    """格式化为可读列表（含序号）。"""
    sorted_hand = sort_cards(hand)
    lines = []
    for i, c in enumerate(sorted_hand):
        marker = " ★wild" if c == _GLOBAL_WILD else ""
        lines.append(f"  [{i:2d}] {c.short}{marker}")
    return "\n".join(lines)


_GLOBAL_WILD: Card | None = None  # 渲染时引用


def _parse_selection(user_input: str, max_idx: int) -> list[int]:
    """解析用户输入的牌序号。"""
    user_input = user_input.strip()
    if not user_input:
        return []
    if user_input.lower() in ("p", "pass", "过", "过牌"):
        return []
    parts = user_input.replace(",", " ").split()
    indices: list[int] = []
    for p in parts:
        try:
            idx = int(p)
        except ValueError:
            continue
        if 0 <= idx < max_idx:
            indices.append(idx)
    return sorted(set(indices))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="掼蛋 CLI (v0.8.0-beta.3 / Public Beta)")
    parser.add_argument("--level", type=int, default=2, help="本局级牌 (2-14, 14=A)")
    parser.add_argument(
        "--first", type=int, choices=range(4), default=None, help="首发起家 (0-3，默认随机)"
    )
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    parser.add_argument(
        "--human", type=int, choices=range(4), default=0, help="真人玩家座位 (0-3, default=0)"
    )
    parser.add_argument(
        "--difficulty",
        type=int,
        default=0,
        choices=[0, 1, 2, 3, 4],
        help="AI 难度档位 (0=新手 / 1=进阶 / 2=高手 / 3=职业 / 4=戴长胜)",
    )
    args = parser.parse_args(argv)

    if not RANK_2 <= args.level <= RANK_A:
        print(f"级牌必须在 2..14 之间，得到 {args.level}", file=sys.stderr)
        return 1

    try:
        strategy = make_strategy(args.difficulty)
    except AINotImplementedError as e:
        print(f"{e}", file=sys.stderr)
        return 2

    print("=" * 60)
    rng = random.Random(args.seed)
    first_player = args.first if args.first is not None else rng.randint(0, 3)
    print(f"掼蛋 CLI (Public Beta) · 级牌 = {args.level} · 首发起家 = {SEAT_NAMES[first_player]} · AI 档位 = {strategy.name}")
    print("=" * 60)

    state = make_initial_state(
        level=args.level, first_player=first_player, seed=args.seed
    )

    global _GLOBAL_WILD
    _GLOBAL_WILD = state.wild_card

    print(f"\n逢人配：{state.wild_card.short if state.wild_card else '（无）'}")
    print(f"真人玩家：{SEAT_NAMES[args.human]}")
    print("初始手牌：")
    for p in range(4):
        marker = " ← 真人" if p == args.human else "  (AI)"
        print(f"  {SEAT_NAMES[p]}  {len(state.hands[p])} 张{marker}")

    turn_count = 0
    max_turns = 200  # 防卡死
    while not state.finished and turn_count < max_turns:
        turn_count += 1
        cur = state.turn_index

        if cur == args.human:
            # 真人
            print(f"\n--- 第 {turn_count} 轮（你出牌）---")
            print(f"级牌：{args.level}  逢人配：{state.wild_card.short if state.wild_card else '（无）'}")
            print(f"本轮出牌：{_render_table_compact(state)}")
            print("你的手牌（从大到小）：")
            sorted_hand = sort_cards(state.hands[cur])
            print(_format_hand(sorted_hand))

            if state.hand_size(cur) <= 10:
                # 报牌提示
                print(f"⚠️ 你只剩 {state.hand_size(cur)} 张，必须报牌（自动报）")

            prompt = "\n请出牌（输入序号，空格分隔）/ 过牌(p) / 报牌状态(b) > "
            user_in = input(prompt).strip()

            if user_in.lower() in ("p", "pass", "过牌", "过"):
                try:
                    pass_turn(state, cur)
                    print("→ 过牌")
                except IllegalPlayError as e:
                    print(f"非法：{e}")
                    continue
            elif user_in.lower() in ("b", "claim", "报牌"):
                if state.hand_size(cur) <= 10:
                    print(f"→ 系统已自动报牌：你剩 {state.hand_size(cur)} 张")
                else:
                    print("→ 还未到报牌张数（剩余 10 张及以下会自动报牌）")
                continue
            else:
                indices = _parse_selection(user_in, len(sorted_hand))
                if not indices:
                    print("无效输入")
                    continue
                cards = [sorted_hand[i] for i in indices]
                pattern = find_complete_pattern(cards, state.wild_card)
                if pattern is None:
                    print("这组牌不是合法牌型，请重选")
                    continue
                try:
                    play_pattern(state, cur, pattern)
                    print(f"→ 你出：{_pattern_short(pattern)}")
                except IllegalPlayError as e:
                    print(f"非法：{e}")
                    continue
        else:
            # AI
            ai_name = SEAT_NAMES[cur]
            history_len_before = len(state.history)
            played = _ai_play(state, cur, strategy, rng)
            if played:
                for event in reversed(state.history[history_len_before:]):
                    if isinstance(event, TurnPlayed):
                        print(f"  {ai_name} 出：{_pattern_short(event.pattern)}")
                        break
            else:
                print(f"  {ai_name} 过牌")

    print("\n" + "=" * 60)
    if state.finished:
        print("本局结束！")
        if state.team_levels_final is not None:
            print(f"两队最终级牌：{[lvl for lvl in state.team_levels_final]}")
            print(f"过 A：{state.guo_a}")
        for i, p in enumerate(state.finish_order):
            label = ["上游", "次游", "中游", "下游"][i] if i < 4 else f"第{i+1}名"
            print(f"  {label}：{SEAT_NAMES[p]}")
    else:
        print(f"对局超时（>{max_turns} 轮），强制结束")
    return 0


def _render_table_compact(state) -> str:
    """渲染当前出牌区（紧凑）。"""
    if not state.table:
        return "（空）"
    return "  ".join(_pattern_short(p) for p in state.table)


if __name__ == "__main__":
    sys.exit(main())
