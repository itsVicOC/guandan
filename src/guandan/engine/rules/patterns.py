"""牌型识别（Pattern Detection）。

输入：一组牌（含几张 wild）
输出：所有合法牌型 Pattern 列表

设计：
- 不依赖 GameState / Level，由调用方负责传入"哪些是 wild"及 level
- 牌型分类见 hand.PatternType
- 同一组牌可能有多种合法解释（如 3 张 5 + 1 张 6 可能是 PAIR_SEQUENCE 的局部）
  —— detector 返回所有合法 Pattern，调用方选择最大或特定的

API：
    detect_patterns(cards: Sequence[Card], wild_card: Card | None) -> list[Pattern]
    is_valid_pattern(cards, wild_card, target_type) -> Pattern | None
    patterns_of(cards, wild_card) -> list[Pattern]
"""
from __future__ import annotations

from collections.abc import Sequence

from ..card import (
    RANK_2,
    RANK_3,
    RANK_4,
    RANK_5,
    RANK_6,
    RANK_7,
    RANK_8,
    RANK_9,
    RANK_10,
    RANK_A,
    RANK_BIG_JOKER,
    RANK_J,
    RANK_K,
    RANK_Q,
    Card,
    Suit,
)
from ..hand import Pattern, PatternType

# ---- 内部工具 ----


def _split_wild(cards: Sequence[Card], wild_card: Card | None) -> tuple[list[Card], int]:
    """把 wild 牌和普通牌分开。返回 (normal_cards, wild_count)。"""
    if wild_card is None:
        return list(cards), 0
    wild_count = sum(1 for c in cards if c == wild_card)
    normal = [c for c in cards if c != wild_card]
    return normal, wild_count


def _is_normal(c: Card) -> bool:
    """是否是普通牌（2..A）。"""
    return RANK_2 <= c.rank <= RANK_A


def _has_joker(cards: Sequence[Card]) -> bool:
    return any(c.is_joker for c in cards)


def _can_use_wild_for(cards: Sequence[Card], wild_count: int) -> list[tuple[list[Card], int]]:
    """枚举"用 k 张 wild 替换为某种牌"的所有可能性。

    返回 [(effective_cards, wild_used), ...]
    """
    # 这里先不展开具体替换，仅返回 (cards, wild_count) ——
    # 真正的"替换成什么"在具体 pattern 识别时枚举
    return [(list(cards), 0)]


# ---- 单 / 对 / 三（基础） ----


def _try_single(
    normal: Sequence[Card], wild_count: int, wild_card: Card | None
) -> list[Pattern]:
    """单张：1 张牌。wild 可作单张直接出。"""
    patterns: list[Pattern] = []
    # 1 张普通牌 / 王
    for c in normal:
        patterns.append(
            Pattern(
                type=PatternType.SINGLE,
                rank=c.rank,
                length=1,
                cards=(c,),
                wild_used=0,
            )
        )
    # 1 张 wild 作单张
    if wild_count >= 1 and wild_card is not None:
        patterns.append(
            Pattern(
                type=PatternType.SINGLE,
                rank=wild_card.rank,  # wild 本身的 rank（被视作本级数）
                length=1,
                cards=(wild_card,),
                wild_used=1,
            )
        )
    return patterns


def _try_pair(
    normal: Sequence[Card], wild_count: int, wild_card: Card | None
) -> list[Pattern]:
    """对子：2 张同点。

    - 2 张普通同点 → 0 wild
    - 1 张普通 + 1 张 wild 顶替 → 1 wild
    - 2 张 wild 顶替（都作 wild）→ 2 wild（其实只 1 张 wild 时 wild_used=1，第二张本身就是 wild）
    """
    patterns: list[Pattern] = []
    by_rank: dict[int, list[Card]] = {}
    for c in normal:
        if not _is_normal(c):
            continue
        by_rank.setdefault(c.rank, []).append(c)

    # 0 wild：同 rank 至少 2 张
    for rank, cards in by_rank.items():
        if len(cards) >= 2:
            patterns.append(
                Pattern(
                    type=PatternType.PAIR,
                    rank=rank,
                    length=1,
                    cards=tuple(cards[:2]),
                    wild_used=0,
                )
            )

    # 1 wild：1 张普通 + 1 张 wild 顶替（取每种 rank 配 1 张）
    if wild_count >= 1 and wild_card is not None:
        for rank, cards in by_rank.items():
            patterns.append(
                Pattern(
                    type=PatternType.PAIR,
                    rank=rank,
                    length=1,
                    cards=(cards[0], wild_card),
                    wild_used=1,
                )
            )

    # 2 wild：2 张 wild 顶替成对
    if wild_count >= 2 and wild_card is not None:
        # 这种情况下其实是 1 张 wild + 1 张普通（如果是 1 wild + 1 普通，已经在上面）
        # 真"2 wild"是 wild 替代成"对子"
        # 但 wild 本身已经是对子（两张同点 wild），所以 wild_used=2, rank = wild.rank
        # 实际上：如果 wild_count=2，两张 wild 配对直接组成对子
        patterns.append(
            Pattern(
                type=PatternType.PAIR,
                rank=wild_card.rank,
                length=1,
                cards=(wild_card, wild_card),
                wild_used=2,
            )
        )

    return patterns


def _try_triple(
    normal: Sequence[Card], wild_count: int, wild_card: Card | None
) -> list[Pattern]:
    """三张：3 张同点。"""
    patterns: list[Pattern] = []
    by_rank: dict[int, list[Card]] = {}
    for c in normal:
        if not _is_normal(c):
            continue
        by_rank.setdefault(c.rank, []).append(c)

    # 0 wild
    for rank, cards in by_rank.items():
        if len(cards) >= 3:
            patterns.append(
                Pattern(
                    type=PatternType.TRIPLE,
                    rank=rank,
                    length=1,
                    cards=tuple(cards[:3]),
                    wild_used=0,
                )
            )

    # 1 wild：2 张普通 + 1 wild
    if wild_count >= 1 and wild_card is not None:
        for rank, cards in by_rank.items():
            if len(cards) >= 2:
                patterns.append(
                    Pattern(
                        type=PatternType.TRIPLE,
                        rank=rank,
                        length=1,
                        cards=(cards[0], cards[1], wild_card),
                        wild_used=1,
                    )
                )

    # 2 wild：1 张普通 + 2 wild
    if wild_count >= 2 and wild_card is not None:
        for rank, cards in by_rank.items():
            patterns.append(
                Pattern(
                    type=PatternType.TRIPLE,
                    rank=rank,
                    length=1,
                    cards=(cards[0], wild_card, wild_card),
                    wild_used=2,
                )
            )

    # 3 wild：三 wild 凑三张
    if wild_count >= 3 and wild_card is not None:
        patterns.append(
            Pattern(
                type=PatternType.TRIPLE,
                rank=wild_card.rank,
                length=1,
                cards=(wild_card, wild_card, wild_card),
                wild_used=3,
            )
        )

    return patterns


# ---- 三带二 ----


def _try_triple_pair(
    normal: Sequence[Card], wild_count: int, wild_card: Card | None
) -> list[Pattern]:
    """三带二：3 张同点 + 1 对子。

    复杂度：wild 分配有多种（0/1/2/3 张 wild 用于三张，0/1/2 用于对子），
    总 wild_used ≤ wild_count。枚举所有可能。
    """
    patterns: list[Pattern] = []
    by_rank: dict[int, list[Card]] = {}
    for c in normal:
        if not _is_normal(c):
            continue
        by_rank.setdefault(c.rank, []).append(c)

    ranks = sorted(by_rank.keys())
    # 枚举三元组 rank X 和对子 rank Y（X 可以等于 Y 表示同点三带对，但掼蛋规则要求 X≠Y）
    # 简化：先按无 wild 处理
    for x in ranks:
        x_cards = by_rank[x]
        for y in ranks:
            if x == y:
                # 同 rank 至少 3 + 2 = 5 张才有意义，且至少分出 3+2
                if len(x_cards) >= 5:
                    patterns.append(
                        Pattern(
                            type=PatternType.TRIPLE_PAIR,
                            rank=x,
                            length=1,
                            cards=tuple(x_cards[:5]),
                            wild_used=0,
                        )
                    )
            else:
                y_cards = by_rank[y]
                if len(x_cards) >= 3 and len(y_cards) >= 2:
                    patterns.append(
                        Pattern(
                            type=PatternType.TRIPLE_PAIR,
                            rank=x,
                            length=1,
                            cards=tuple(x_cards[:3] + y_cards[:2]),
                            wild_used=0,
                        )
                    )

    # 1 wild
    if wild_count >= 1 and wild_card is not None:
        for x in ranks:
            x_cards = by_rank[x]
            for y in ranks:
                if x == y:
                    if len(x_cards) >= 4:
                        # 4 张同点 + 1 wild = 三 + 对
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=tuple([*x_cards[:4], wild_card]),
                                wild_used=1,
                            )
                        )
                else:
                    y_cards = by_rank[y]
                    if len(x_cards) >= 3 and len(y_cards) >= 1:
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=tuple([*x_cards[:3], y_cards[0], wild_card]),
                                wild_used=1,
                            )
                        )
                    if len(x_cards) >= 2 and len(y_cards) >= 2:
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=tuple([*x_cards[:2], wild_card, *y_cards[:2]]),
                                wild_used=1,
                            )
                        )

    # 2 wilds
    if wild_count >= 2 and wild_card is not None:
        for x in ranks:
            x_cards = by_rank[x]
            for y in ranks:
                if x == y:
                    if len(x_cards) >= 3:
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=tuple([*x_cards[:3], wild_card, wild_card]),
                                wild_used=2,
                            )
                        )
                else:
                    y_cards = by_rank[y]
                    if len(x_cards) >= 3:
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=tuple(
                                    [*x_cards[:3], y_cards[0], wild_card]
                                    if y_cards
                                    else [*x_cards[:3], wild_card, wild_card]
                                ),
                                wild_used=2,
                            )
                        )
                    if len(x_cards) >= 2 and len(y_cards) >= 1:
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=tuple([*x_cards[:2], y_cards[0], wild_card, wild_card]),
                                wild_used=2,
                            )
                        )
                    if len(x_cards) >= 1 and len(y_cards) >= 2:
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=tuple([x_cards[0], wild_card, wild_card, *y_cards[:2]]),
                                wild_used=2,
                            )
                        )

    # 3 wilds: 1 普通 + 2 wild 作三张 + (1 普通 + 1 wild) 作对 = 5 张；或 3 wild 作三 + 2 wild 作对
    if wild_count >= 3 and wild_card is not None:
        for x in ranks:
            x_cards = by_rank[x]
            if len(x_cards) >= 1:
                # 1 普通 + 2 wild 作三，2 wild 作对
                if wild_count >= 5:
                    patterns.append(
                        Pattern(
                            type=PatternType.TRIPLE_PAIR,
                            rank=x,
                            length=1,
                            cards=(x_cards[0], wild_card, wild_card, wild_card, wild_card),
                            wild_used=4,
                        )
                    )
                # 1 普通 + 2 wild 作三，1 普通 + 1 wild 作对
                for y in ranks:
                    if y == x:
                        continue
                    y_cards = by_rank[y]
                    if len(y_cards) >= 1:
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=(x_cards[0], wild_card, wild_card, y_cards[0], wild_card),
                                wild_used=3,
                            )
                        )

    return patterns


# ---- 顺子 ----


def _try_straight(
    normal: Sequence[Card], wild_count: int, wild_card: Card | None, suit_filter: int | None = None
) -> list[Pattern]:
    """顺子 / 同花顺：5+ 张连续单张。

    suit_filter: None = 顺子（任意花色），int = 同花顺（指定花色 Suit 值）

    wild 处理：wild 可填入窗口中的"缺口"（即 rank_count[r]==0 的位置）。
    """
    if _has_joker(normal):
        return []  # 顺子不含王

    # 过滤出指定花色（如果 suit_filter 不为 None）
    if suit_filter is not None:
        cards_of_filter = [c for c in normal if c.suit == suit_filter]
    else:
        cards_of_filter = list(normal)

    # 按 rank 统计
    rank_count: dict[int, int] = {}
    for c in cards_of_filter:
        if not _is_normal(c):
            continue
        rank_count[c.rank] = rank_count.get(c.rank, 0) + 1

    patterns: list[Pattern] = []
    ptype = PatternType.STRAIGHT_FLUSH if suit_filter is not None else PatternType.STRAIGHT

    def _window_uses(rank_list: list[int]) -> tuple[bool, int, list[Card]]:
        """计算用 rank_list 长度对应的牌所需 wild 数和实际可用牌。

        返回 (valid, wild_needed, actual_cards)。
        actual_cards 是从 cards_of_filter 中按 rank 找的 + wild_card 补的。
        """
        wild_needed = 0
        actual: list[Card] = []
        for r in rank_list:
            if rank_count.get(r, 0) > 0:
                # 找一张该 rank 的牌
                for c in cards_of_filter:
                    if c.rank == r and c not in actual:
                        actual.append(c)
                        break
            else:
                wild_needed += 1
                if wild_needed > wild_count:
                    return False, wild_needed, []
                if wild_card is not None:
                    actual.append(wild_card)
        return True, wild_needed, actual

    # 1. 非 wrap 情形：枚举 [start, end] 长度 ≥ 5 的窗口
    for start in range(RANK_3, RANK_A):  # start 不能是 A
        for end in range(start + 4, RANK_A + 1):  # end ≥ start+4
            window = list(range(start, end + 1))
            if RANK_2 in window:
                continue
            valid, w, used = _window_uses(window)
            if not valid:
                continue
            patterns.append(
                Pattern(
                    type=ptype,
                    rank=window[-1],
                    length=len(window),
                    cards=tuple(used),
                    wild_used=w,
                    suit=suit_filter,
                )
            )

    # 2. A2345 wrap 情形
    # 需要 A, 2, 3, 4, 5 都在或由 wild 替代
    wrap = [RANK_A, RANK_2, RANK_3, RANK_4, RANK_5]
    valid, w, used = _window_uses(wrap)
    if valid:
        patterns.append(
            Pattern(
                type=ptype,
                rank=RANK_5,
                length=5,
                cards=tuple(used),
                wild_used=w,
                suit=suit_filter,
            )
        )

    return patterns


def _is_valid_straight_window(window: list[int]) -> bool:
    """判断一组连续 rank 是否构成合法顺子窗口。

    规则：
    - 长度 ≥ 5
    - 全部在 [RANK_2..RANK_A] 内
    - 不能含 RANK_2（除非是 wrap A2345，但 wrap 单独处理）
    - A 只能作最大或最小
    """
    if len(window) < 5:
        return False
    if any(r < RANK_2 or r > RANK_A for r in window):
        return False
    if RANK_2 in window:
        # wrap A2345 的情形
        return window == [RANK_A, RANK_2, RANK_3, RANK_4, RANK_5]
    # A 只能出现在最大位置。
    return not (RANK_A in window and window[-1] != RANK_A)


# ---- 连对 ----


def _try_pair_sequence(
    normal: Sequence[Card], wild_count: int, wild_card: Card | None
) -> list[Pattern]:
    """连对：3+ 对连续对子。"""
    if _has_joker(normal):
        return []

    # 按 rank 统计
    by_rank: dict[int, list[Card]] = {}
    for c in normal:
        if not _is_normal(c):
            continue
        by_rank.setdefault(c.rank, []).append(c)

    # 至少 3 对连续 rank
    pairs_available = {r: cards for r, cards in by_rank.items() if len(cards) >= 2}
    if not pairs_available and wild_count < 2:
        return []

    patterns: list[Pattern] = []
    # 枚举连续 rank 段（不含 2）
    available_ranks = sorted(r for r in pairs_available if r != RANK_2)
    # 找连续段
    runs: list[list[int]] = []
    if available_ranks:
        cur = [available_ranks[0]]
        for r in available_ranks[1:]:
            if r == cur[-1] + 1:
                cur.append(r)
            else:
                runs.append(cur)
                cur = [r]
        runs.append(cur)

    # 每段枚举 ≥3 长的窗口
    for run in runs:
        for i in range(len(run)):
            for j in range(i + 2, len(run)):
                window = run[i : j + 1]
                if RANK_2 in window:
                    continue
                if RANK_A in window and window[-1] != RANK_A:
                    continue
                used_cards = []
                for r in window:
                    used_cards.extend(pairs_available[r][:2])
                patterns.append(
                    Pattern(
                        type=PatternType.PAIR_SEQUENCE,
                        rank=window[-1],
                        length=len(window),
                        cards=tuple(used_cards),
                        wild_used=0,
                    )
                )

    # 1 wild: 用 1 wild 顶替 1 对
    if wild_count >= 1 and wild_card is not None:
        for run in runs:
            for i in range(len(run)):
                for j in range(i + 1, len(run)):
                    window = run[i : j + 1]  # length >= 3 (i+2 <= j+1 即 j >= i+1)
                    if len(window) < 2:
                        continue
                    # 实际需要 window 个对子，wild 顶替 1 个，剩下需要至少 2 张普通
                    # 但我们这里只枚举：window 中 1 个 rank 只有 1 张，1 个 rank 有 2 张
                    # 简化：找所有"含 1 张"rank 配 wild
                    single_ranks = [r for r in window if r in by_rank and len(by_rank[r]) == 1]
                    if not single_ranks:
                        continue
                    used_cards = []
                    for r in window:
                        if r in pairs_available:
                            used_cards.extend(pairs_available[r][:2])
                        elif r in single_ranks:
                            used_cards.append(by_rank[r][0])
                            used_cards.append(wild_card)
                    if len(used_cards) == len(window) * 2:
                        patterns.append(
                            Pattern(
                                type=PatternType.PAIR_SEQUENCE,
                                rank=window[-1],
                                length=len(window),
                                cards=tuple(used_cards),
                                wild_used=1,
                            )
                        )

    # 2 wild: 顶替 2 对
    if wild_count >= 2 and wild_card is not None:
        # 简化：先支持无普通对 + 2 wild 起手 + 1 对
        for r in [RANK_3, RANK_4, RANK_5, RANK_6, RANK_7, RANK_8, RANK_9, RANK_10, RANK_J, RANK_Q, RANK_K]:
            if r in pairs_available:
                used = [pairs_available[r][0], pairs_available[r][1], wild_card, wild_card, wild_card, wild_card]
                patterns.append(
                    Pattern(
                        type=PatternType.PAIR_SEQUENCE,
                        rank=RANK_3,
                        length=3,
                        cards=tuple(used),
                        wild_used=2,
                    )
                )
                break

    return patterns


# ---- 钢板 / 三顺 ----


def _try_triple_sequence(
    normal: Sequence[Card], wild_count: int, wild_card: Card | None
) -> list[Pattern]:
    """钢板：2+ 组连续三张。"""
    if _has_joker(normal):
        return []

    by_rank: dict[int, list[Card]] = {}
    for c in normal:
        if not _is_normal(c):
            continue
        by_rank.setdefault(c.rank, []).append(c)

    triples_available = {r: cards for r, cards in by_rank.items() if len(cards) >= 3}
    if not triples_available and wild_count < 3:
        return []

    patterns: list[Pattern] = []

    # 枚举连续 rank 段（不含 2、不含 A 作为最大）
    available_ranks = sorted(r for r in triples_available if r != RANK_2)
    runs: list[list[int]] = []
    if available_ranks:
        cur = [available_ranks[0]]
        for r in available_ranks[1:]:
            if r == cur[-1] + 1:
                cur.append(r)
            else:
                runs.append(cur)
                cur = [r]
        runs.append(cur)

    # 枚举 ≥2 长的窗口
    for run in runs:
        for i in range(len(run)):
            for j in range(i + 1, len(run)):
                window = run[i : j + 1]
                if RANK_2 in window:
                    continue
                if RANK_A in window and window[-1] != RANK_A:
                    continue
                used_cards = []
                for r in window:
                    used_cards.extend(triples_available[r][:3])
                patterns.append(
                    Pattern(
                        type=PatternType.TRIPLE_SEQUENCE,
                        rank=window[-1],
                        length=len(window),
                        cards=tuple(used_cards),
                        wild_used=0,
                    )
                )

    return patterns


# ---- 炸弹 / 同花顺（高阶） ----


def _try_bomb(
    normal: Sequence[Card], wild_count: int, wild_card: Card | None
) -> list[Pattern]:
    """炸弹：4+ 张同点。"""
    if _has_joker(normal):
        return []  # 4 王单独处理

    by_rank: dict[int, list[Card]] = {}
    for c in normal:
        if not _is_normal(c):
            continue
        by_rank.setdefault(c.rank, []).append(c)

    patterns: list[Pattern] = []

    # 0 wild
    for rank, cards in by_rank.items():
        if len(cards) >= 4:
            for n in range(4, len(cards) + 1):
                patterns.append(
                    Pattern(
                        type=PatternType.BOMB,
                        rank=rank,
                        length=n,
                        cards=tuple(cards[:n]),
                        wild_used=0,
                    )
                )

    # 1 wild：k 张普通 + 1 wild（k ≥ 3）
    if wild_count >= 1 and wild_card is not None:
        for rank, cards in by_rank.items():
            for k in range(3, len(cards) + 1):
                patterns.append(
                    Pattern(
                        type=PatternType.BOMB,
                        rank=rank,
                        length=k + 1,
                        cards=tuple([*cards[:k], wild_card]),
                        wild_used=1,
                    )
                )

    # 2 wilds
    if wild_count >= 2 and wild_card is not None:
        for rank, cards in by_rank.items():
            for k in range(2, len(cards) + 1):
                patterns.append(
                    Pattern(
                        type=PatternType.BOMB,
                        rank=rank,
                        length=k + 2,
                        cards=tuple([*cards[:k], wild_card, wild_card]),
                        wild_used=2,
                    )
                )

    # 3 wilds
    if wild_count >= 3 and wild_card is not None:
        for rank, cards in by_rank.items():
            for k in range(1, len(cards) + 1):
                patterns.append(
                    Pattern(
                        type=PatternType.BOMB,
                        rank=rank,
                        length=k + 3,
                        cards=tuple(cards[:k] + [wild_card] * 3),
                        wild_used=3,
                    )
                )

    # 4 wilds
    if wild_count >= 4 and wild_card is not None:
        # 至少 4 wild，组成 4 张炸弹
        patterns.append(
            Pattern(
                type=PatternType.BOMB,
                rank=wild_card.rank,
                length=4,
                cards=tuple([wild_card] * 4),
                wild_used=4,
            )
        )
        # 5+ 张 wild 凑炸弹
        for n in range(5, wild_count + 1):
            patterns.append(
                Pattern(
                    type=PatternType.BOMB,
                    rank=wild_card.rank,
                    length=n,
                    cards=tuple([wild_card] * n),
                    wild_used=n,
                )
            )

    return patterns


def _try_four_jokers(cards: Sequence[Card]) -> list[Pattern]:
    """四王炸弹：大王×2 + 小王×2。"""
    big = sum(1 for c in cards if c.is_big_joker)
    small = sum(1 for c in cards if c.is_small_joker)
    if big >= 2 and small >= 2:
        return [
            Pattern(
                type=PatternType.FOUR_JOKERS,
                rank=RANK_BIG_JOKER,
                length=4,
                cards=tuple(c for c in cards if c.is_joker)[:4],
                wild_used=0,
            )
        ]
    return []


# ---- 顶层 API ----


def detect_patterns(cards: Sequence[Card], wild_card: Card | None = None) -> list[Pattern]:
    """识别一组牌能构成的所有合法牌型。

    Args:
        cards: 输入的牌列表
        wild_card: 本局的"逢人配"牌（红心级牌），若 None 则视作无 wild

    Returns:
        合法 Pattern 列表（含不同 wild_used 数的版本）
    """
    if not cards:
        return []

    normal, wild_count = _split_wild(cards, wild_card)

    patterns: list[Pattern] = []

    # 四王（独立最优先）
    patterns.extend(_try_four_jokers(cards))

    # 单 / 对 / 三
    patterns.extend(_try_single(normal, wild_count, wild_card))
    patterns.extend(_try_pair(normal, wild_count, wild_card))
    patterns.extend(_try_triple(normal, wild_count, wild_card))

    # 三带二
    patterns.extend(_try_triple_pair(normal, wild_count, wild_card))

    # 顺子
    patterns.extend(_try_straight(normal, wild_count, wild_card, suit_filter=None))

    # 连对
    patterns.extend(_try_pair_sequence(normal, wild_count, wild_card))

    # 钢板
    patterns.extend(_try_triple_sequence(normal, wild_count, wild_card))

    # 炸弹
    patterns.extend(_try_bomb(normal, wild_count, wild_card))

    # 同花顺
    for s in (Suit.HEARTS, Suit.DIAMONDS, Suit.SPADES, Suit.CLUBS):
        patterns.extend(_try_straight(normal, wild_count, wild_card, suit_filter=int(s)))

    # 去重（同样的 (type, rank, length, wild_used) 算同一牌型）
    seen = set()
    unique: list[Pattern] = []
    for p in patterns:
        key = (p.type, p.rank, p.length, p.wild_used, p.suit)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def is_legal(cards: Sequence[Card], wild_card: Card | None = None) -> bool:
    """判断一组牌是否能**整体**构成一个合法牌型。

    区别于 has_legal_pattern：要求所有牌被一个 Pattern 完全用掉。
    """
    return find_complete_pattern(cards, wild_card) is not None


def find_complete_pattern(
    cards: Sequence[Card], wild_card: Card | None = None
) -> Pattern | None:
    """找一个用掉所有 cards 的合法 Pattern（cards 集合必须等于某 Pattern 的 cards）。"""
    input_set = frozenset(cards)
    for p in detect_patterns(cards, wild_card):
        if frozenset(p.cards) == input_set:
            return p
    return None


def has_legal_pattern(cards: Sequence[Card], wild_card: Card | None = None) -> bool:
    """判断一组牌中是否能凑出至少一个合法牌型（不要求用完全部牌）。"""
    return len(detect_patterns(cards, wild_card)) > 0


def find_pattern(
    cards: Sequence[Card], target: PatternType, wild_card: Card | None = None
) -> Pattern | None:
    """找一种特定类型的合法牌型（用掉所有 cards）。"""
    for p in detect_patterns(cards, wild_card):
        if p.type == target and frozenset(p.cards) == frozenset(cards):
            return p
    return None
