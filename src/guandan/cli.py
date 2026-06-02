"""命令行 CLI：跑通一局完整对局。

v0.1.0 (M0a) 简化版：
- 1 名真人玩家 + 3 名电脑
- 电脑为"贪心"AI（出最小可压的牌型）
- 命令行提示出牌
"""
from __future__ import annotations

import argparse
import random
import sys
from typing import List, Optional

from .engine.card import Card, RANK_2, RANK_A, Suit
from .engine.hand import Hand, Pattern, PatternType, sort_cards
from .engine.rules.patterns import detect_patterns, find_complete_pattern
from .engine.state import (
    SEAT_NAMES,
    IllegalPlayError,
    make_initial_state,
    pass_turn,
    play_pattern,
    team_of,
)


# ---- AI 策略（贪心，单遍扫描） ----


def _greedy_ai_select(state, player: int) -> Optional[Pattern]:
    """贪心 AI：选最小可压牌型。

    实现：单遍扫描手牌，按牌型分类找最小可压，不做指数级枚举。
    """
    hand = state.hands[player]
    wild = state.wild_card
    table_top = state.table[-1] if state.table else None

    # 1. 新一轮先手：出最小单张
    if table_top is None:
        sorted_hand = sort_cards(hand)
        if not sorted_hand:
            return None
        c = sorted_hand[-1]  # 最小
        return find_complete_pattern([c], wild)

    # 2. 同类型压牌：找刚好大于 table_top 的最小牌型
    by_rank: dict[int, list[Card]] = {}
    for c in hand:
        if c.rank not in by_rank:
            by_rank[c.rank] = []
        by_rank[c.rank].append(c)
    wild_count = sum(1 for c in hand if c == wild) if wild else 0

    target_type = table_top.type
    target_rank = table_top.rank
    target_len = table_top.length

    if target_type == PatternType.SINGLE:
        # 找最小单张 > table_top（从小到大遍历）
        sorted_cards = sort_cards(hand)
        # sort_cards 默认是 reverse=True（从大到小），所以 reversed 是从小到大
        for c in reversed(sorted_cards):
            if c.rank > target_rank:
                p = find_complete_pattern([c], wild)
                if p and p.type == PatternType.SINGLE:
                    return p
        # 没找到单张能压
    elif target_type == PatternType.PAIR:
        # 找最小对子 > table_top（rank 大于）
        for r in range(target_rank + 1, RANK_A + 1):
            if r == 100 or r == 101:  # 跳过 joker
                continue
            if r == RANK_2:
                continue
            if r in by_rank and len(by_rank[r]) >= 2:
                cards = by_rank[r][:2]
                p = find_complete_pattern(cards, wild)
                if p:
                    return p
        # wild 凑对
        if wild_count >= 1:
            for r in range(target_rank + 1, RANK_A + 1):
                if r in by_rank and len(by_rank[r]) >= 1:
                    cards = [by_rank[r][0], wild]
                    p = find_complete_pattern(cards, wild)
                    if p and p.type == PatternType.PAIR:
                        return p
    elif target_type == PatternType.TRIPLE:
        for r in range(target_rank + 1, RANK_A + 1):
            if r in by_rank and len(by_rank[r]) >= 3:
                cards = by_rank[r][:3]
                p = find_complete_pattern(cards, wild)
                if p:
                    return p
        # wild 凑
        if wild_count >= 1:
            for r in range(target_rank + 1, RANK_A + 1):
                if r in by_rank and len(by_rank[r]) >= 2:
                    cards = by_rank[r][:2] + [wild]
                    p = find_complete_pattern(cards, wild)
                    if p and p.type == PatternType.TRIPLE:
                        return p
    else:
        # 其他牌型（顺子、连对、钢板）暂不实现
        # 简单处理：检查是否能用炸弹压
        pass

    # 3. 炸弹压（包括同花顺、四王）
    # 普通 4+ 张炸弹
    for r in range(RANK_2, RANK_A + 1):
        if r in by_rank and len(by_rank[r]) >= 4:
            length = min(len(by_rank[r]), 8)
            cards = by_rank[r][:length]
            p = find_complete_pattern(cards, wild)
            if p and p.type == PatternType.BOMB and p.can_be_played_on(table_top):
                return p
    # wild 凑炸弹
    if wild_count >= 1 and RANK_2 <= 2 + wild_count:  # ensure we can form 4-card bomb
        for r in range(RANK_2, RANK_A + 1):
            if r in by_rank and len(by_rank[r]) + wild_count >= 4:
                need = 4 - wild_count
                if len(by_rank[r]) >= need and need >= 0:
                    cards = by_rank[r][:need] + [wild] * wild_count
                    p = find_complete_pattern(cards, wild)
                    if p and p.type == PatternType.BOMB and p.can_be_played_on(table_top):
                        return p
    # 四王
    big = sum(1 for c in hand if c.is_big_joker)
    small = sum(1 for c in hand if c.is_small_joker)
    if big >= 2 and small >= 2:
        cards = [c for c in hand if c.is_joker][:4]
        p = find_complete_pattern(cards, wild)
        if p and p.type == PatternType.FOUR_JOKERS:
            return p

    return None


def _ai_play(state, player: int) -> bool:
    """AI 玩家行动：返回 True 表示出牌，False 表示过牌。

    决策逻辑：
    - 找不到可压的牌 → 必须过
    - 是新一轮 leader（空表）→ 必须出
    - 压角色：模拟真实玩家，"明显小"才压，否则过牌
      概率：随牌力提升而过牌概率提高（手牌越强越舍不得出大牌）
    """
    if state.turn_index != player:
        return False
    p = _greedy_ai_select(state, player)
    if p is None:
        # 找不到可压的牌 → 过
        pass_turn(state, player)
        return False
    # 新一轮 leader（空表）→ 必须出
    if not state.table:
        play_pattern(state, player, p)
        return True
    # 压角色：有过牌概率（避免 AIs 100% 压让玩家被无限卡住）
    # 用 target_rank / RANK_A 作为过牌概率
    from .engine.card import RANK_A as _RANK_A
    table_top = state.table[-1]
    rank = table_top.rank if table_top.rank <= _RANK_A else _RANK_A
    pass_prob = (rank - 2) / (_RANK_A - 2) * 0.6 + 0.1  # 0.1~0.7 之间
    import random as _r
    if _r.random() < pass_prob:
        # 主动过牌
        pass_turn(state, player)
        return False
    play_pattern(state, player, p)
    return True


# ---- 真人交互 ----


def _render_table(state) -> str:
    """渲染当前出牌区。"""
    if not state.table:
        return "（空）"
    return " → ".join(
        f"{SEAT_NAMES[p.player]}{_pattern_short(p.pattern)}" for p in []  # placeholder
    )


def _pattern_short(p: Pattern) -> str:
    if p.type == PatternType.SINGLE:
        return p.cards[0].short
    if p.type == PatternType.PAIR:
        return f"对{p.cards[0].rank_display}" if hasattr(p.cards[0], "rank_display") else f"对{p.cards[0].short}"
    cards_str = " ".join(c.short for c in p.cards)
    return f"{p.type.value}[{cards_str}]"


def _format_hand(hand: List[Card]) -> str:
    """格式化为可读列表（含序号）。"""
    sorted_hand = sort_cards(hand)
    lines = []
    for i, c in enumerate(sorted_hand):
        marker = " ★wild" if c == _GLOBAL_WILD else ""
        lines.append(f"  [{i:2d}] {c.short}{marker}")
    return "\n".join(lines)


_GLOBAL_WILD: Optional[Card] = None  # 渲染时引用


def _parse_selection(user_input: str, max_idx: int) -> List[int]:
    """解析用户输入的牌序号。"""
    user_input = user_input.strip()
    if not user_input:
        return []
    if user_input.lower() in ("p", "pass", "过", "过牌"):
        return []
    parts = user_input.replace(",", " ").split()
    indices: List[int] = []
    for p in parts:
        try:
            idx = int(p)
        except ValueError:
            continue
        if 0 <= idx < max_idx:
            indices.append(idx)
    return sorted(set(indices))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="掼蛋 CLI (M0a)")
    parser.add_argument("--level", type=int, default=2, help="本局级牌 (2-14, 14=A)")
    parser.add_argument("--first", type=int, default=0, help="首发起家 (0-3)")
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    parser.add_argument(
        "--human", type=int, default=0, help="真人玩家座位 (0-3, default=0)"
    )
    args = parser.parse_args(argv)

    if not RANK_2 <= args.level <= RANK_A:
        print(f"级牌必须在 2..14 之间，得到 {args.level}", file=sys.stderr)
        return 1

    print("=" * 60)
    print(f"掼蛋 CLI (M0a) · 级牌 = {args.level} · 首发起家 = {SEAT_NAMES[args.first]}")
    print("=" * 60)

    state = make_initial_state(
        level=args.level, first_player=args.first, seed=args.seed
    )

    global _GLOBAL_WILD
    _GLOBAL_WILD = state.wild_card

    print(f"\n逢人配：{state.wild_card.short if state.wild_card else '（无）'}")
    print(f"真人玩家：{SEAT_NAMES[args.human]}")
    print(f"初始手牌：")
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
                state.history.append(
                    type(state.history[0])  # placeholder
                ) if False else None

            prompt = "\n请出牌（输入序号，空格分隔）/ 过牌(p) / 报牌(b) > "
            user_in = input(prompt).strip()

            if user_in.lower() in ("p", "pass", "过牌", "过"):
                try:
                    pass_turn(state, cur)
                    print("→ 过牌")
                except IllegalPlayError as e:
                    print(f"非法：{e}")
                    continue
            else:
                indices = _parse_selection(user_in, len(sorted_hand))
                if not indices:
                    print("无效输入")
                    continue
                cards = [sorted_hand[i] for i in indices]
                p = find_complete_pattern(cards, state.wild_card)
                if p is None:
                    print("这组牌不是合法牌型，请重选")
                    continue
                try:
                    play_pattern(state, cur, p)
                    print(f"→ 你出：{_pattern_short(p)}")
                except IllegalPlayError as e:
                    print(f"非法：{e}")
                    continue
        else:
            # AI
            ai_name = SEAT_NAMES[cur]
            played = _ai_play(state, cur)
            if played:
                last = state.history[-1]
                p = last.pattern
                print(f"  {ai_name} 出：{_pattern_short(p)}")
            else:
                print(f"  {ai_name} 过牌")

    print("\n" + "=" * 60)
    if state.finished:
        print("本局结束！")
        if hasattr(state, "team_levels_final"):
            print(f"两队最终级牌：{[lvl for lvl in state.team_levels_final]}")
            print(f"漂牌：{state.drift_flag}")
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
