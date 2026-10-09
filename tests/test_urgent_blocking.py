from __future__ import annotations

import copy
import math
import random
from collections import Counter
from dataclasses import replace
from itertools import combinations

import pytest

from guandan.ai.context import PublicTacticalContext
from guandan.ai.mcts.root_search import root_action_candidates
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.ai.tactics import select_heuristic_action
from guandan.ai.urgent_blocking import ShortHandRisks, action_key, blocking_reference
from guandan.engine.card import Card, Suit
from guandan.engine.deck import make_deck
from guandan.engine.events import Pass, TributeSent, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.rules.patterns import find_complete_pattern
from guandan.engine.state import GameState


def card(rank, suit=Suit.CLUBS):
    return Card(rank, Suit.SMALL_JOKER if rank == 100 else Suit.BIG_JOKER if rank == 101 else suit)


def context_for(pool, fixed, size, level, wild):
    return PublicTacticalContext(
        player=0, partner=2, level=level, sizes=(4, size, 4, 0), order=(3, 2, 1),
        top_player=None, top=None, unseen=tuple(pool)+tuple(fixed),
        known=((), tuple(fixed), (), ()), leads=(), passes=(), wild=wild,
    )


@pytest.mark.parametrize('level', [2, 9, 14])
@pytest.mark.parametrize('size', [1, 2, 3])
@pytest.mark.parametrize('known_count', [0, 1, 2])
def test_short_distribution_matches_physical_card_exhaustion(level, size, known_count):
    if known_count > size:
        return
    wild = card(level, Suit.HEARTS)
    pool = [wild, wild, card(8), card(8, Suit.SPADES), card(9), card(100), card(100), card(101)]
    fixed = [card(8, Suit.DIAMONDS), wild][:known_count]
    model = ShortHandRisks(context_for(pool, fixed, size, level, wild))
    tops = [None, Pattern(PatternType.SINGLE, 7, 1, (card(7),)),
            Pattern(PatternType.PAIR, 7, 1, (card(7), card(7, Suit.SPADES))),
            Pattern(PatternType.TRIPLE, 7, 1, (card(7), card(7, Suit.SPADES), card(7, Suit.DIAMONDS)))]
    for top in tops:
        count = 0
        for indices in combinations(range(len(pool)), size-known_count):
            complete = find_complete_pattern(fixed+[pool[i] for i in indices], wild)
            count += complete is not None and (top is None or complete.can_be_played_on(top, level=level))
        assert model.probability(1, top) == pytest.approx(count/math.comb(len(pool), size-known_count))


def test_two_wilds_are_one_disjoint_outcome_and_jokers_cannot_make_triples():
    wild = card(2, Suit.HEARTS)
    model = ShortHandRisks(context_for([wild, wild], [], 2, 2, wild))
    assert model.probability(1, None) == 1
    assert len(model.outcomes[1]) == 1
    model = ShortHandRisks(context_for([card(100)]*3, [], 3, 2, wild))
    assert model.probability(1, None) == 0


def public_state(hands, *, top_owner=3, passed=(), known=(), level=2, finish_order=()):
    top = Pattern(PatternType.SINGLE, 12, 1, (card(12),))
    remaining = Counter(make_deck())
    remaining.subtract(c for hand in hands for c in hand)
    remaining.subtract(top.cards)
    assert all(n >= 0 for n in remaining.values())
    history = [TributeSent(2, seat, c) for seat, cards in known for c in cards]
    history += [TurnPlayed(0, Pattern(PatternType.SINGLE, c.rank, 1, (c,)), 5) for c in remaining.elements()]
    history += [TurnPlayed(top_owner, top, len(hands[top_owner]))]
    history += [Pass(seat, len(hands[seat])) for seat in passed]
    return GameState(level=level, wild_card=card(level, Suit.HEARTS), hands=hands,
                     turn_index=0, leader=top_owner, table=[top], passed_players=set(passed),
                     history=history, finish_order=list(finish_order), ruleset_version=3)


def reopening_state():
    return public_state([[card(13), card(8), card(8, Suit.DIAMONDS)], [card(14)],
                         [card(6, suit) for suit in (Suit.HEARTS, Suit.DIAMONDS, Suit.SPADES) for _ in range(2)],
                         [card(7, suit) for suit in (Suit.HEARTS, Suit.DIAMONDS, Suit.SPADES, Suit.CLUBS) for _ in range(2)]],
                        passed=(2, 1), known=((1, (card(14),)),))


def test_pass_closes_trick_and_does_not_reopen_known_ace():
    state = reopening_state()
    context = PublicTacticalContext.from_state(state, 0)
    risks = ShortHandRisks(context)
    assert risks.after_action(state, 0, None) == {}
    king = Pattern(PatternType.SINGLE, 13, 1, (card(13),))
    assert risks.after_action(state, 0, king)[1] == 1.0
    old = select_heuristic_action(state, 0, 2)
    assert old is not None and old.rank == 13
    new, report = blocking_reference(state, 0, old, weight=12, deadline=None)
    assert new is None and report['reason'] == 'changed'


def test_partner_opportunity_does_not_erase_an_enemy_threat():
    state = public_state([[card(13), card(8), card(9)], [card(14)],
                          [card(6)]*2, [card(7)]*2], known=((1, (card(14),)),))
    risks = ShortHandRisks(PublicTacticalContext.from_state(state, 0))
    # Seat 2 precedes seat 1; its ability to block is unknown.
    assert risks.after_action(state, 0, Pattern(PatternType.SINGLE, 13, 1, (card(13),)))[1] == 1


def test_available_level_single_blocks_a_public_ace_despite_structure_cost():
    state = public_state([[card(13), card(2), card(2, Suit.DIAMONDS),
                           card(8), card(8, Suit.DIAMONDS)],
                          [card(7), card(7, Suit.DIAMONDS)]*2,
                          [card(6), card(6, Suit.DIAMONDS)]*2, [card(14)]],
                         top_owner=2, passed=(1,), known=((3, (card(14),)),))
    baseline = select_heuristic_action(state, 0, 2)
    assert baseline is not None and baseline.rank == 13
    action, report = blocking_reference(state, 0, baseline, weight=12, deadline=None)
    assert action is not None and action.type == PatternType.SINGLE and action.rank == 2
    selected = next(row for row in report['risks'] if row['key'] == action_key(action))
    assert selected['by_seat'][3] == 0
    original = next(row for row in report['risks'] if row['key'] == action_key(baseline))
    assert original['by_seat'][3] == 1
    risks = ShortHandRisks(PublicTacticalContext.from_state(state, 0))
    assert risks.after_action(state, 0, None) == {3: 1.0}


def test_head_already_fixed_preserves_later_place_by_not_reopening_enemy():
    state = public_state([[card(13), card(8), card(8, Suit.DIAMONDS)],
                          [card(14)], [], []], top_owner=2, passed=(1,),
                         known=((1, (card(14),)),), finish_order=(2, 3))
    baseline = select_heuristic_action(state, 0, 2)
    assert baseline is not None and baseline.rank == 13
    action, report = blocking_reference(state, 0, baseline, weight=12, deadline=None)
    assert action is None and report['reason'] == 'changed'
    risks = ShortHandRisks(PublicTacticalContext.from_state(state, 0))
    assert risks.after_action(state, 0, None) == {}
    assert risks.after_action(state, 0, baseline) == {1: 1.0}


def test_jiefeng_projection_uses_the_actual_new_leader():
    state = public_state([[card(13), card(8)], [card(14)], [card(6)]*2, []],
                         passed=(2, 1), top_owner=3, known=((1, (card(14),)),), finish_order=(3,))
    risks = ShortHandRisks(PublicTacticalContext.from_state(state, 0))
    assert risks.after_action(state, 0, None) == {1: 1.0}


def test_finish_has_priority_and_certain_unblockable_enemy_stays_legal():
    state = public_state([[card(101)], [card(14)], [card(6)]*2, [card(7)]*2], known=((1, (card(14),)),))
    action, report = blocking_reference(state, 0, None, weight=12, deadline=None)
    assert action is not None and action.rank == 101 and report['reason'] == 'legal_finish'
    state = public_state([[card(100), card(3), card(5)], [card(7)]*2, [card(6)]*2, [card(101)]],
                         top_owner=2, passed=(1,), known=((3, (card(101),)),))
    base = select_heuristic_action(state, 0, 2)
    action, report = blocking_reference(state, 0, base, weight=12, deadline=None)
    assert action_key(action) == action_key(base)
    assert report['reason'] == 'unchanged'


@pytest.mark.parametrize('seat', range(4))
@pytest.mark.parametrize('level', [2, 9, 14])
def test_hidden_hand_replacement_and_rotation_preserve_proposals(seat, level):
    state = reopening_state()
    state.level = level
    state.wild_card = card(level, Suit.HEARTS)
    out = copy.deepcopy(state)
    out.hands = [state.hands[(i-seat) % 4] for i in range(4)]
    out.turn_index = seat
    out.leader = (state.leader+seat) % 4
    out.passed_players = {(s+seat) % 4 for s in state.passed_players}
    out.history = [replace(e, player=(e.player+seat) % 4) if isinstance(e, (Pass, TurnPlayed))
                   else replace(e, from_player=(e.from_player+seat) % 4, to_player=(e.to_player+seat) % 4)
                   for e in state.history]
    baseline = select_heuristic_action(out, seat, 2)
    action, report = blocking_reference(out, seat, baseline, weight=12, deadline=None)
    altered = copy.deepcopy(out)
    for s in range(4):
        if s != seat:
            altered.hands[s] = [card(10)]*len(altered.hands[s])
    other, other_report = blocking_reference(altered, seat, baseline, weight=12, deadline=None)
    assert action_key(other) == action_key(action)
    assert other_report['risks'] == report['risks']


def test_timeout_and_incomplete_accounting_are_atomic():
    state = reopening_state()
    base = select_heuristic_action(state, 0, 2)
    result, report = blocking_reference(state, 0, base, weight=12, deadline=0)
    assert result == base and report['reason'] == 'budget_limited' and report['risks'] == []
    state.history = state.history[-3:]
    result, report = blocking_reference(state, 0, base, weight=12, deadline=None)
    assert result == base and report['reason'] == 'incomplete_public_state'


def test_root_keeps_baseline_pass_and_finishes_without_growing_candidates():
    state = reopening_state()
    baseline = select_heuristic_action(state, 0, 2)
    policy = ProfessionalStrategy(urgent_blocking=True, time_budget_ms=0)
    original = root_action_candidates(state, 0, max_actions=6, reference_actions=(baseline,))
    action = policy._reference_action(state, 0)
    assert action is None
    assert policy._urgent_candidates is not None
    assert len(policy._urgent_candidates) == len(original)
    assert action_key(baseline) in {action_key(a) for a in policy._urgent_candidates}
    assert ('pass',) in {action_key(a) for a in policy._urgent_candidates}


@pytest.mark.parametrize('weight', [-1, float('nan'), float('inf')])
def test_weight_validation(weight):
    with pytest.raises(ValueError, match='finite and nonnegative'):
        ProfessionalStrategy(urgent_blocking_weight=weight)


def test_defaults_and_invalid_combinations():
    assert not ProfessionalStrategy().urgent_blocking
    assert not DaiChangshengStrategy().urgent_blocking
    with pytest.raises(ValueError, match='require root search'):
        ProfessionalStrategy(search_mode='tree', urgent_blocking=True)
    with pytest.raises(ValueError, match='original tactical'):
        ProfessionalStrategy(urgent_blocking=True, team_tactics=True)


def test_disabled_path_does_not_import_or_call_new_tactic(monkeypatch):
    import guandan.ai.urgent_blocking as module
    monkeypatch.setattr(module, 'blocking_reference', lambda *a, **kw: pytest.fail('disabled path called'))
    state = reopening_state()
    strategy = ProfessionalStrategy(rng=random.Random(12), time_budget_ms=0)
    before = strategy.rng.getstate()
    assert strategy._reference_action(state, 0) == select_heuristic_action(state, 0, 2)
    assert strategy.rng.getstate() == before
    assert strategy.last_urgent_blocking is None


@pytest.mark.parametrize('replaceable', [True, False])
def test_candidate_replacement_is_bounded_and_protected(monkeypatch, replaceable):
    from guandan.ai import candidates, urgent_blocking
    from guandan.ai.strategies import professional

    state = public_state([[card(13), card(14), card(2), card(7), card(8)], [card(10)],
                          [card(6)]*2, [card(9)]*2], top_owner=2, passed=(1,))
    old = Pattern(PatternType.SINGLE, 13, 1, (card(13),))
    new = Pattern(PatternType.SINGLE, 2, 1, (card(2),))
    ordinary = Pattern(PatternType.SINGLE, 14, 1, (card(14),))
    pool = [old, None, ordinary] if replaceable else [old, None]
    report = {'reference_key': action_key(new), 'candidate_replaced': False}
    monkeypatch.setattr(professional, 'select_heuristic_action', lambda *a, **kw: old)
    monkeypatch.setattr(urgent_blocking, 'blocking_reference', lambda *a, **kw: (new, report))
    monkeypatch.setattr(professional, 'root_action_candidates', lambda *a, **kw: list(pool))
    monkeypatch.setattr(candidates, 'smallest_legal_pattern', lambda *a, **kw: old)
    policy = ProfessionalStrategy(urgent_blocking=True, time_budget_ms=0)
    choice = policy._reference_action(state, 0)
    if replaceable:
        assert choice == new
        assert policy._urgent_candidates == [old, None, new]
        assert report['candidate_replaced']
    else:
        assert choice == old
        assert policy._urgent_candidates is None
        assert report['reason'] == 'no_replaceable_candidate'
