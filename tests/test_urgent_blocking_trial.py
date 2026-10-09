"""Production-clock trial fairness, isolation, lineage and promotion checks."""
from __future__ import annotations

import random
import zipfile
from pathlib import Path

import pytest

from guandan.ai.strategy import make_strategy
from guandan.engine.state import make_initial_state
from scripts.ai_budget_refinement_trial import seed_for as previous_seed
from scripts.ai_team_trial import public_request
from scripts.ai_urgent_blocking_trial import (
    COUNTS,
    ROOT,
    Client,
    a_metadata,
    development_passed,
    promotion_passed,
    seed_for,
    verify_harness_manifest,
)
from scripts.fit_action_ranker import derived_seed


def test_seeds_disjoint_from_previous_studies_and_full_rounds():
    inputs = [(f'{stage}-{tier}', i) for stage, count in COUNTS.items() for tier in (3, 4) for i in range(count)]
    current = {seed_for(stage, i) for stage, i in inputs}
    old = {previous_seed(stage, i) for stage, i in inputs} | {derived_seed(stage, i) for stage, i in inputs}
    assert len(current) == len(inputs) and not current.intersection(old)
    full = [seed_for('full-deal', seed_for(f'full-{tier}', i), j) for tier in (3, 4) for i in range(48) for j in range(64)]
    assert len(set(full)) == len(full) and not current.intersection(full)


def clock_fixture():
    return {'records': [{'tier': tier, 'budget_passed': True} for tier in (3, 4) for _ in range(21)]}


def test_development_requires_both_gains_and_timing():
    good = {'pairs': 32, 'mean_paired_gain': .01, 'budget_gate_passed': True}
    assert development_passed(good, good, clock_fixture(), 3)
    assert not development_passed(good, {**good, 'mean_paired_gain': 0}, clock_fixture(), 3)
    assert not development_passed({**good, 'budget_gate_passed': False}, good, clock_fixture(), 3)
    clock = clock_fixture()
    clock['records'][0]['budget_passed'] = False
    assert not development_passed(good, good, clock, 3)


def acceptance_fixture():
    one = {'pairs': 240, 'gain_confidence_95': [.01, .03], 'budget_gate_passed': True,
           'observations': [{'strict_replay_passed': True}]}
    mixed = {**one, 'by_companion': {str(t): {'mean_paired_gain': .01} for t in range(3)}}
    full = {**one, 'pairs': 48, 'match_win_confidence_95': [.51, .70]}
    return [one, mixed, full]


@pytest.mark.parametrize('failure', ['team', 'partner', 'full', 'quality', 'replay', 'regression', 'clock'])
def test_no_failed_endpoint_can_promote(failure):
    reports, clock = acceptance_fixture(), clock_fixture()
    regression, replay, quality = {'passed': True}, {'passed': True, 'completed_branches': 1152}, {'passed': True}
    assert promotion_passed(reports, clock, regression, replay, quality, 3)
    if failure == 'team':
        reports[0]['gain_confidence_95'] = [-.01, .03]
    elif failure == 'partner':
        reports[1]['by_companion']['0']['mean_paired_gain'] = -.001
    elif failure == 'full':
        reports[2]['match_win_confidence_95'] = [.49, .70]
    elif failure == 'clock':
        clock['records'][0]['budget_passed'] = False
    else:
        {'quality': quality, 'replay': replay, 'regression': regression}[failure]['passed'] = False
    assert not promotion_passed(reports, clock, regression, replay, quality, 3)


def test_isolated_worker_and_direct_lower_tier_have_same_action_and_rng():
    client = Client(ROOT, 0)
    try:
        state = make_initial_state(seed=930400)
        actor = state.current_player()
        rng = random.Random(9)
        request = public_request(state, actor, 3)
        request.update(difficulty=2, mode='fixed', fixed_iterations=256, rng_state=rng.getstate())
        result = client.query(request)
        from guandan.storage.serialization import _dict_to_pattern
        policy = make_strategy(2)
        assert _dict_to_pattern(result['pattern']) == policy.select_pattern(state, actor)
        assert result['urgent'] is None
        assert result['budget_passed']
    finally:
        client.close()


def test_frozen_baseline_worker_accepts_public_request_without_new_options(monkeypatch, tmp_path):
    baseline = tmp_path / 'frozen-baseline'
    with zipfile.ZipFile(Path(__file__).parent / 'fixtures/frozen-v11.zip') as archive:
        archive.extractall(baseline)
    # The historical checkout is a comparison fixture, not this project's
    # coverage target. Keep instrumentation for current-source worker tests.
    for name in ('COVERAGE_PROCESS_CONFIG', 'COVERAGE_PROCESS_START',
                 'COV_CORE_SOURCE', 'COV_CORE_CONFIG', 'COV_CORE_DATAFILE'):
        monkeypatch.delenv(name, raising=False)
    client = Client(baseline, 0)
    try:
        state = make_initial_state(seed=930401)
        request = public_request(state, state.current_player(), 3)
        request.update(difficulty=3, mode='fixed', fixed_iterations=16, rng_state=random.Random(9).getstate())
        result = client.query(request)
        assert result['urgent'] is None
        assert result['simulations'] <= 16
    finally:
        client.close()


def test_mixed_result_metadata_matches_actual_factory_difficulties(monkeypatch):
    from types import SimpleNamespace

    from scripts import ai_urgent_blocking_trial as trial

    class DummyClient:
        def __init__(self, *args):
            pass

        def close(self):
            pass

    def fake_match(seed, *, difficulties, strategy_factory, **kwargs):
        policies = [strategy_factory(d, seat) for seat, d in enumerate(difficulties)]
        assert tuple(p.difficulty for p in policies) == difficulties
        assert difficulties == (3, 3, 0, 0)
        return SimpleNamespace(finished=True, winner_team=0,
                               to_dict=lambda: {'finished': True, 'difficulties': difficulties,
                                                'finish_order': [0, 2, 1], 'initial_levels': (2, 2),
                                                'level': 2, 'match_finished': False,
                                                'match_winner_team': None, 'final_levels': (5, 2)})

    monkeypatch.setattr(trial, 'Client', DummyClient)
    monkeypatch.setattr(trial, 'run_match', fake_match)
    monkeypatch.setattr(trial, 'canonical_utility', lambda result, team: .5)
    rows = trial.trial_pair(0, 77, {'suite': 'dev-mixed', 'difficulty': 3, 'weight': 6,
                                  'baseline_root': str(ROOT), 'candidate_root': str(ROOT)})
    assert len(rows) == 2
    assert {r['candidate_team'] for r in rows} == {0, 1}
    assert all(r['companion_difficulty'] == 0 for r in rows)


def test_a_metadata_and_level_summary_use_completed_public_result():
    from scripts.ai_team_trial import summarize

    result = {'finish_order': [0, 1, 3], 'initial_levels': (14, 9), 'level': 14,
              'match_finished': False, 'match_winner_team': None, 'final_levels': (2, 9),
              'initial_a_failures': (2, 0), 'final_a_failures': (0, 0)}
    own = a_metadata(result, 0)
    assert own == {'a_attempted': True, 'a_succeeded': False, 'opponent_a_failed': None,
                   'a_utility_won': False, 'a_failure_before': 2, 'a_failure_after': 0,
                   'a_reset': True}
    enemy = a_metadata(result, 1)
    assert enemy['opponent_a_failed'] and not enemy['a_attempted']
    successful = {**result, 'finish_order': [0, 2, 1], 'match_finished': True, 'match_winner_team': 0}
    assert a_metadata(successful, 0)['a_succeeded']
    assert a_metadata(successful, 0)['a_utility_won']
    assert not a_metadata(successful, 0, full=True)['a_attempted']
    rows = [{'seed': 1, 'gain': 0, 'head_won': team == 0, 'level': 14,
             'budget_failures': [], **a_metadata(result, team)} for team in (0, 1)]
    report = summarize(rows)
    assert report['pairs'] == 1
    assert report['by_level']['14']['a_attempts'] == 1
    assert report['by_level']['14']['a_successes'] == 0


def test_shared_harness_or_replay_corpus_changes_reject_resume(tmp_path):
    import hashlib

    helper = tmp_path/'scripts'/'shared.py'
    helper.parent.mkdir()
    helper.write_text('unchanged helper')
    fixture = tmp_path/'tests'/'fixtures'/'ai-human-partner-replay.json'
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{}')
    manifest = {'files': {str(path.relative_to(tmp_path)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (helper, fixture)}}
    verify_harness_manifest(manifest, tmp_path)
    helper.write_text('changed helper')
    with pytest.raises(ValueError, match='dependency differs'):
        verify_harness_manifest(manifest, tmp_path)
    helper.write_text('unchanged helper')
    fixture.unlink()
    with pytest.raises(ValueError, match='dependency differs'):
        verify_harness_manifest(manifest, tmp_path)
