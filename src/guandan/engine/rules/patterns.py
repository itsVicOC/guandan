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

from typing import Sequence

from ..card import (
    Card,
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
    RANK_SMALL_JOKER,
    Suit,
)
from ..hand import Hand, Pattern, PatternType


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
                                cards=tuple(x_cards[:4] + [wild_card]),
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
                                cards=tuple(x_cards[:3] + [y_cards[0], wild_card]),
                                wild_used=1,
                            )
                        )
                    if len(x_cards) >= 2 and len(y_cards) >= 2:
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=tuple(x_cards[:2] + [wild_card] + y_cards[:2]),
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
                                cards=tuple(x_cards[:3] + [wild_card, wild_card]),
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
                                cards=tuple(x_cards[:3] + [y_cards[0], wild_card] if y_cards else x_cards[:3] + [wild_card, wild_card]),
                                wild_used=2,
                            )
                        )
                    if len(x_cards) >= 2 and len(y_cards) >= 1:
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=tuple(x_cards[:2] + [y_cards[0], wild_card, wild_card]),
                                wild_used=2,
                            )
                        )
                    if len(x_cards) >= 1 and len(y_cards) >= 2:
                        patterns.append(
                            Pattern(
                                type=PatternType.TRIPLE_PAIR,
                                rank=x,
                                length=1,
                                cards=tuple([x_cards[0], wild_card, wild_card] + y_cards[:2]),
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
    """
    if _has_joker(normal):
        return []  # 顺子不含王

    # 过滤出指定花色（如果 suit_filter 不为 None）
    if suit_filter is not None:
        cards_of_filter = [c for c in normal if c.suit == suit_filter]
    else:
        cards_of_filter = list(normal)

    # 按 rank 统计（每种 rank 最多 4 张同 rank，但顺子中每种 rank 只取 1 张）
    rank_count: dict[int, int] = {}
    for c in cards_of_filter:
        if not _is_normal(c):
            continue
        rank_count[c.rank] = min(rank_count.get(c.rank, 0) + 1, 4)

    patterns: list[Pattern] = []
    ptype = PatternType.STRAIGHT_FLUSH if suit_filter is not None else PatternType.STRAIGHT

    # 枚举所有可能的"窗口"（连续 rank 段，长度 ≥ 5）
    # 顺子规则：
    # - A-2-3-4-5 合法（A 作最小）
    # - 10-J-Q-K-A 合法（A 作最大）
    # - A-2-3-4-5-6 不合法（A 只在端点 wrap 一次）
    # - 2-3-4-5-6 不合法（2 不能在非 wrap 顺子中）
    # - 2345678 长度 7 是合法（不含 2 wrap 的情况下，但 2 在内就不行）
    # 实施：枚举 [start, end] range，处理两种 A 情形
    if not rank_count:
        return patterns

    # 找所有"连续"rank 段（rank 在 [RANK_2..RANK_A] 内）
    # 不含 2：rank_count[RANK_2] 不参与普通顺子（除非 wrap A2345）
    # 我们先处理非 wrap 情形
    present = sorted(r for r in rank_count if r != RANK_2)  # 排除 2
    # 枚举连续段
    runs: list[list[int]] = []
    if present:
        cur = [present[0]]
        for r in present[1:]:
            if r == cur[-1] + 1:
                cur.append(r)
            else:
                runs.append(cur)
                cur = [r]
        runs.append(cur)

    # 枚举每段中所有 ≥5 长度的窗口
    for run in runs:
        for i in range(len(run)):
            for j in range(i + 4, len(run)):
                window = run[i : j + 1]
                if not _is_valid_straight_window(window):
                    continue
                # 找该 window 对应的牌（每种 rank 1 张）
                used_cards = []
                for r in window:
                    # 找一张该 rank 的牌
                    found = next((c for c in cards_of_filter if c.rank == r), None)
                    if found is None:
                        break
                    used_cards.append(found)
                if len(used_cards) != len(window):
                    continue
                patterns.append(
                    Pattern(
                        type=ptype,
                        rank=window[-1],  # 最大一张的 rank
                        length=len(window),
                        cards=tuple(used_cards),
                        wild_used=0,
                        suit=suit_filter,
                    )
                )

    # A2345 wrap 情形
    if RANK_2 in rank_count and RANK_A in rank_count and wild_count == 0:
        # 无 wild 才能用 2 当普通牌进 wrap
        # 5 张：A, 2, 3, 4, 5
        need = [RANK_A, RANK_2, RANK_3, RANK_4, RANK_5]
        used_cards = []
        for r in need:
            if r not in rank_count:
                break
            found = next((c for c in cards_of_filter if c.rank == r), None)
            if found is None:
                break
            used_cards.append(found)
        if len(used_cards) == 5:
            patterns.append(
                Pattern(
                    type=ptype,
                    rank=RANK_5,  # 最大一张是 5
                    length=5,
                    cards=tuple(used_cards),
                    wild_used=0,
                    suit=suit_filter,
                )
            )

    # 1+ wild 参与顺子：每张 wild 顶替一段缺口
    # 实现：枚举用 k 张 wild 顶替 5+k 张连续 rank 中的 k 个
    if wild_count >= 1 and wild_card is not None:
        for k_used in range(1, wild_count + 1):
            # 至少 5 张普通/wild 混合 = 5 - k_used 实际普通 + k_used wild
            min_len = 5
            for length in range(min_len, min_len + k_used + 5):  # 探索合理长度
                # 枚举所有连续的 (length - k_used) 段
                # 因为 k_used 张 wild 顶替后总长 = length
                # 实际普通数 = length - k_used
                # 即：枚举 length-k_used 张连续普通牌 + k_used wild
                actual_normal = length - k_used
                if actual_normal < 1:
                    continue
                # 枚举连续段
                for start_rank in range(RANK_2, RANK_A - actual_normal + 2):
                    window = list(range(start_rank, start_rank + actual_normal))
                    if not _is_valid_straight_window(window):
                        continue
                    # 构造牌：window 中每 rank 1 张 + k_used wild
                    used_cards = []
                    for r in window:
                        if r not in rank_count:
                            break
                        found = next((c for c in cards_of_filter if c.rank == r), None)
                        if found is None:
                            break
                        used_cards.append(found)
                    if len(used_cards) != actual_normal:
                        continue
                    used_cards.extend([wild_card] * k_used)
                    patterns.append(
                        Pattern(
                            type=ptype,
                            rank=window[-1],
                            length=length,
                            cards=tuple(used_cards),
                            wild_used=k_used,
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
        if window == [RANK_A, RANK_2, RANK_3, RANK_4, RANK_5]:
            return True
        return False
    if RANK_A in window and window[-1] != RANK_A:
        # A 出现在中间或开头但不是最大
        return False
    return True


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

    # 1 wild：3 张普通 + 1 wild
    if wild_count >= 1 and wild_card is not None:
        for rank, cards in by_rank.items():
            if len(cards) >= 3:
                patterns.append(
                    Pattern(
                        type=PatternType.BOMB,
                        rank=rank,
                        length=4,
                        cards=tuple(cards[:3] + [wild_card]),
                        wild_used=1,
                    )
                )

    # 2 wilds: 2 普通 + 2 wild / 3 普通 + 1 wild 已经上面
    if wild_count >= 2 and wild_card is not None:
        for rank, cards in by_rank.items():
            if len(cards) >= 2:
                patterns.append(
                    Pattern(
                        type=PatternType.BOMB,
                        rank=rank,
                        length=4,
                        cards=tuple(cards[:2] + [wild_card, wild_card]),
                        wild_used=2,
                    )
                )

    # 3 wilds: 1 普通 + 3 wild
    if wild_count >= 3 and wild_card is not None:
        for rank, cards in by_rank.items():
            if len(cards) >= 1:
                patterns.append(
                    Pattern(
                        type=PatternType.BOMB,
                        rank=rank,
                        length=4,
                        cards=tuple([cards[0]] + [wild_card] * 3),
                        wild_used=3,
                    )
                )

    # 4 wilds: 4 wild 凑炸弹（rank = wild.rank）
    if wild_count >= 4 and wild_card is not None:
        patterns.append(
            Pattern(
                type=PatternType.BOMB,
                rank=wild_card.rank,
                length=4,
                cards=tuple([wild_card] * 4),
                wild_used=4,
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
        if p.type == target:
            # 验证用掉所有 cards
            if frozenset(p.cards) == frozenset(cards):
                return p
    return None
