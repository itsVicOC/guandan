"""Research prototype of an exactly equivalent packed-multiset hand planner.

Each card type occupies a lane with a spare guard bit. Subset tests use guarded
integer subtraction; after a successful test plain subtraction removes cards.
The beam, pattern order, node ceiling and arithmetic match the original planner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from collections import Counter
from functools import lru_cache
from math import ceil
from pathlib import Path

from guandan.ai.hand_plan import _estimate, _play_cost
from guandan.engine.rules.patterns import detect_patterns
from guandan.engine.state import make_initial_state


@lru_cache(maxsize=8192)
def packed_estimate(cards, wild, level, width):
    if not cards:
        return 0.0
    patterns = detect_patterns(cards, wild)
    by_material = {}
    for pattern in patterns:
        material = tuple(sorted(pattern.cards))
        previous = by_material.get(material)
        if previous is None or _play_cost(pattern, level) < _play_cost(previous, level):
            by_material[material] = pattern
    singles = [p for p in by_material.values() if len(p.cards) == 1]
    grouped = sorted((p for p in by_material.values() if len(p.cards) > 1),
                     key=lambda p: (-len(p.cards), p.wild_used, _play_cost(p, level)))[:192]
    counts = Counter(cards)
    card_types = sorted(counts)
    bits = max(counts.values()).bit_length()
    stride = bits + 1
    shifts = {card: index * stride for index, card in enumerate(card_types)}
    guards = sum(1 << (shift + bits) for shift in shifts.values())
    initial = sum(count * (1 << shifts[card]) for card, count in counts.items())
    by_card = [[] for _ in card_types]
    sizes = {initial: len(cards)}
    for pattern in grouped + singles:
        used = Counter(pattern.cards)
        packed = sum(count << shifts[card] for card, count in used.items())
        item = (packed, _play_cost(pattern, level), len(pattern.cards))
        for card in used:
            by_card[shifts[card] // stride].append(item)
    for options in by_card:
        options.sort(key=lambda item: (item[1] / item[2], -item[2]))
    beam = [(0.0, initial)]
    best = len(cards) * 1.28
    expanded = 0
    node_limit = max(64, width * 12)
    while beam and expanded < node_limit:
        next_beam = {}
        for spent, rest in beam:
            if not rest:
                best = min(best, spent)
                continue
            pivot = ((rest & -rest).bit_length() - 1) // stride
            options = [item for item in by_card[pivot] if ((rest | guards) - item[0]) & guards == guards]
            for packed, cost, size in options[:16]:
                after = rest - packed
                value = spent + cost
                if not after:
                    best = min(best, value)
                else:
                    sizes[after] = sizes[rest] - size
                    if value + ceil(sizes[after] / 10) * 0.82 < best:
                        next_beam[after] = min(value, next_beam.get(after, float("inf")))
                expanded += 1
                if expanded >= node_limit:
                    break
            if expanded >= node_limit:
                break
        beam = sorted(((value, rest) for rest, value in next_beam.items()),
                      key=lambda item: item[0] + ceil(sizes[item[1]] / 8) * 0.9)[:width]
    for spent, rest in beam:
        best = min(best, spent + sizes[rest] * 1.28)
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hands", type=int, default=192)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = []
    rng = random.Random(392001)
    for index in range(args.hands):
        level = (2, 9, 14)[index % 3]
        state = make_initial_state(seed=392000 + index, level=level)
        hand = state.hands[index % 4]
        rng.shuffle(hand)
        cards = tuple(sorted(hand[:1 + index % 27]))
        cases.append((cards, state.wild_card, level, (6, 16, 24)[(index // 3) % 3]))
    timings = {"original": [], "packed": []}
    for index, case in enumerate(cases):
        values = {}
        # Alternate ordering, clear both value caches; no cross-case hot reuse.
        for name in (("original", "packed") if index % 2 else ("packed", "original")):
            function = _estimate if name == "original" else packed_estimate
            function.cache_clear()
            started = time.perf_counter()
            values[name] = function(*case)
            timings[name].append(time.perf_counter() - started)
        if values["original"] != values["packed"]:
            raise AssertionError((index, case, values))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = {"cases": len(cases), "exact_values_equal": True,
              "note": "cold planner caches; run serially without other workloads for timing",
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "seconds": {name: sum(values) for name, values in timings.items()},
              "speedup": sum(timings["original"]) / sum(timings["packed"]), "timings": timings}
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "timings"}, indent=2))


if __name__ == "__main__":
    main()
