"""Frozen, serial production-budget evaluation of weights 6/12 (v12).

The two teams use the same RPC worker and process/cache lifetime. Each leg
starts fresh workers; leg order alternates, and no clock games run concurrently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import sys
import time
import zipfile
from dataclasses import replace
from pathlib import Path

from guandan.ai import diagnostics
from guandan.ai.arena import paired_score_interval
from guandan.ai.benchmark import run_full_match, run_match
from guandan.engine.state import clone_state_for_search, pass_turn, play_pattern
from guandan.storage.serialization import _dict_to_pattern
from scripts.ai_action_ranker_validation import validate_pairs
from scripts.ai_manifest import evaluation_manifest, manifest_fingerprint
from scripts.ai_rpc import PolicyClient
from scripts.ai_team_trial import (
    canonical_utility,
    companion_difficulty,
    match_state,
    public_request,
    summarize,
)
from scripts.fit_action_ranker import snapshot_fingerprint

NAMESPACE = 'urgent-blocking-v12b'
COUNTS = {'dev-team': 32, 'dev-mixed': 32, 'holdout': 240, 'mixed': 240, 'full': 48}
WEIGHTS = (6, 12)
ROOT = Path(__file__).resolve().parents[1]


def seed_for(stage, index, round_index=0):
    return int.from_bytes(hashlib.sha256(f'{NAMESPACE}/{stage}/{index}/{round_index}'.encode()).digest()[:8], 'big')


def a_metadata(result, team, *, full=False):
    """Derive reporting fields solely from a completed public result."""
    if full:
        return {'a_attempted': False, 'a_succeeded': None, 'opponent_a_failed': None,
                'a_utility_won': None, 'a_failure_before': None, 'a_failure_after': None,
                'a_reset': False}
    order = list(result['finish_order'])
    order.extend(seat for seat in range(4) if seat not in order)
    won_head = order[0] % 2 == team
    head_passed_a = (order[0] + 2) % 4 != order[-1]
    levels = result['initial_levels'] or (result['level'], result['level'])
    own_a, enemy_a = levels[team] == 14, levels[1-team] == 14
    return {'a_attempted': own_a, 'a_succeeded': won_head and head_passed_a if own_a else None,
            'opponent_a_failed': not (not won_head and head_passed_a) if enemy_a else None,
            'a_utility_won': result['match_finished'] and result['match_winner_team'] == team if own_a else None,
            'a_failure_before': result['initial_a_failures'][team] if own_a else None,
            'a_failure_after': result['final_a_failures'][team] if own_a else None,
            'a_reset': own_a and not result['match_finished'] and result['final_levels'][team] == 2}


def verify_harness_manifest(manifest, root=ROOT):
    """Reject changed shared evaluation helpers and the public replay corpus."""
    for relative, expected in manifest['files'].items():
        if relative.startswith('scripts/') or relative == 'tests/fixtures/ai-human-partner-replay.json':
            path = root/relative
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f'frozen evaluation dependency differs: {relative}')


def freeze_candidate(folder):
    """Preserve the candidate before any timing or development outcomes exist."""
    archive = folder / 'candidate-snapshot.zip'
    target = Path('/tmp/guandan-urgent-v12-candidate')
    if archive.exists():
        with zipfile.ZipFile(archive) as z:
            manifest = json.loads(z.read('snapshot-manifest.json'))
            if manifest['source_sha256'] != snapshot_fingerprint(ROOT):
                raise ValueError('frozen candidate differs; use a new experiment version')
            verify_harness_manifest(manifest)
            z.extractall(target)
        return target
    paths = []
    for name in ('src', 'scripts', 'tests'):
        paths += [p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')]
    paths += [ROOT/name for name in ('pyproject.toml', 'uv.lock')]
    manifest = {'source_sha256': snapshot_fingerprint(ROOT),
                'files': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}}
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(paths):
            z.write(p, p.relative_to(ROOT))
        z.writestr('snapshot-manifest.json', json.dumps(manifest, indent=2)+'\n')
        z.extractall(target)
    return target


class Client(PolicyClient):
    def __init__(self, root, weight):
        super().__init__(
            [sys.executable, '-u', '-B', str(ROOT/'scripts/ai_urgent_worker.py'), '--root', str(root), '--weight', str(weight)],
            root=Path(root),
        )


class RemotePolicy:
    name = 'isolated'
    uses_stochastic_pass = False

    def __init__(self, client, tier, mode='clock', work=256):
        self.client, self.difficulty, self.mode, self.work = client, tier, mode, work
        self.rng = random.Random(0)
        self.decisions = []

    def select_pattern(self, state, player):
        request = public_request(state, player, 3)
        request.update(difficulty=self.difficulty, mode=self.mode, fixed_iterations=self.work,
                       rng_state=self.rng.getstate())
        result = self.client.query(request)
        raw = result.pop('rng_state')
        self.rng.setstate((raw[0], tuple(raw[1]), raw[2]))
        self.decisions.append(result)
        return _dict_to_pattern(result['pattern']) if result['pattern'] else None


def trial_pair(index, seed, config):
    rows = []
    for team in ((0, 1) if index % 2 == 0 else (1, 0)):
        clients = [Client(Path(config['baseline_root']), 0), Client(Path(config['candidate_root']), config['weight'])]
        policies = []
        mixed = 'mixed' in config['suite']
        full = config['suite'] == 'full'
        tier = config['difficulty']
        try:
            def factory(_difficulty, seat, mixed=mixed, tier=tier, clients=clients, team=team, policies=policies):
                difficulty = companion_difficulty(index) if mixed and seat >= 2 else tier
                policy = RemotePolicy(clients[int(seat % 2 == team)], difficulty)
                policies.append(policy)
                return policy
            if full:
                result = run_full_match(seed, difficulties=tier, strategy_factory=factory,
                                        round_seed_factory=lambda master, offset: seed_for('full-deal', master, offset))
            else:
                difficulties = tuple(companion_difficulty(index) if mixed and seat >= 2 else tier for seat in range(4))
                result = run_match(seed, level=(2, 9, 14)[index % 3], difficulties=difficulties,
                                   strategy_factory=factory, **match_state(index, team))
            if not result.finished:
                raise RuntimeError('trial failed to complete')
            utility = float(result.winner_team == team) if full else canonical_utility(result, team)
            decisions = [{'seat': seat, **decision} for seat, policy in enumerate(policies) for decision in policy.decisions]
            candidate_decisions = [d for d in decisions if d['seat'] % 2 == team and (not mixed or d['seat'] < 2)]
            payload = result.to_dict()
            rows.append({'seed': seed, 'candidate_team': team, 'level': 2 if full else (2, 9, 14)[index % 3],
                         'companion_difficulty': companion_difficulty(index) if mixed else None,
                         'utility': utility, 'gain': 2*utility-1,
                         'head_won': result.winner_team == team if not full else result.round_results[0].winner_team == team,
                         'budget_failures': [d for d in candidate_decisions if not d['budget_passed']],
                         'baseline_budget_failures': [d for d in decisions if d['seat'] % 2 != team and not d['budget_passed']],
                         'clock_decisions': decisions, 'strict_replay_passed': True,
                         **a_metadata(payload, team, full=full), 'result': payload})
        finally:
            for client in clients:
                client.close()
    return rows


def run_trial(config, folder):
    suite, tier, weight = config['suite'], config['difficulty'], config['weight']
    count = COUNTS[suite]
    seeds = [seed_for(f'{suite}-{tier}', i) for i in range(count)]
    path = folder/f'{suite}-{tier}-w{weight}.json'
    progress = path.with_suffix('.progress.jsonl')
    rows = []
    if path.exists():
        report = json.loads(path.read_text())
        if report['config'] != config:
            raise ValueError('completed trial recipe/source differs')
        validate_pairs(report['observations'], seeds)
        return report
    if progress.exists():
        for line in progress.read_text().splitlines():
            item = json.loads(line)
            if item['config'] != config:
                raise ValueError('checkpoint recipe/source differs')
            rows.extend(item['rows'])
        validate_pairs(rows, sorted({r['seed'] for r in rows}))
    done = {r['seed'] for r in rows}
    started = time.perf_counter()
    for i, seed in enumerate(seeds):
        if seed in done:
            continue
        new_rows = trial_pair(i, seed, config)
        with progress.open('a') as stream:
            stream.write(json.dumps({'config': config, 'rows': new_rows})+'\n')
            stream.flush()
            os.fsync(stream.fileno())
        rows.extend(new_rows)
        print(f'{suite}-{tier}-w{weight}: {len(rows)//2}/{count} pairs; {time.perf_counter()-started:.1f}s', flush=True)
    validate_pairs(rows, seeds)
    report = {'config': config, 'workers': 1, 'platform': platform.platform(), 'python': platform.python_version(),
              **summarize(rows), 'observations': sorted(rows, key=lambda r: (r['seed'], r['candidate_team']))}
    if suite == 'full':
        scores = [sum(r['utility'] for r in rows if r['seed'] == seed)/2 for seed in seeds]
        report.update(match_win_rate=sum(scores)/len(scores), match_win_confidence_95=paired_score_interval(scores, samples=5000))
    path.write_text(json.dumps(report, indent=2)+'\n')
    progress.unlink(missing_ok=True)
    return report


def clock_check(candidate, weight):
    records = []
    for tier in (3, 4):
        client = Client(candidate, weight)
        try:
            policy = RemotePolicy(client, tier)
            for cache, corpus in (('warm', diagnostics.positions()), ('cold', diagnostics.endgame_positions())):
                for index, (name, state) in enumerate(corpus):
                    request = public_request(state, state.current_player(), 3)
                    request.update(difficulty=tier, mode='clock', rng_state=random.Random(seed_for(f'clock-{tier}-{weight}', index)).getstate(),
                                   clear_caches=cache == 'cold')
                    result = client.query(request)
                    result.pop('rng_state')
                    records.append({'tier': tier, 'cache': cache, 'case': name, **result})
            state = clone_state_for_search(diagnostics.positions()[0][1])
            from guandan.ai.strategy import make_strategy
            human = make_strategy(2).select_pattern(state, state.current_player())
            if human is None:
                pass_turn(state, state.current_player())
            else:
                play_pattern(state, state.current_player(), human)
            for step in range(3):
                action = policy.select_pattern(state, state.current_player())
                result = policy.decisions[-1]
                records.append({'tier': tier, 'cache': 'consecutive', 'case': step, **result})
                if action is None:
                    pass_turn(state, state.current_player())
                else:
                    play_pattern(state, state.current_player(), action)
        finally:
            client.close()
    return {'weight': weight, 'workers': 1, 'records': records, 'passed': all(r['budget_passed'] for r in records)}


def development_passed(team, mixed, clock, tier):
    return (team['pairs'] == mixed['pairs'] == 32 and team['mean_paired_gain'] > 0 and mixed['mean_paired_gain'] > 0
            and team['budget_gate_passed'] and mixed['budget_gate_passed']
            and sum(r['tier'] == tier for r in clock['records']) == 21
            and all(r['budget_passed'] for r in clock['records'] if r['tier'] == tier))


def replay_check(baseline, candidate, tier, weight):
    """Only public human prefixes; subsequent outcomes belong to legal proxies."""
    from guandan.ai.mcts.determinize import determinize
    from guandan.ai.mcts.information_set import _apply_action
    from guandan.ai.strategy import make_strategy
    from guandan.engine.replay import replay_events
    from guandan.storage.serialization import deserialize_events
    from scripts.fit_action_ranker import frozen_playout

    fixture = ROOT/'tests/fixtures/ai-human-partner-replay.json'
    data = json.loads(fixture.read_text())
    rows = []
    for index in data['decision_events']:
        events = deserialize_events(data['events'][:index])
        events[0] = replace(events[0], a_failure_counts=(0, 0))
        state = replay_events(events, allow_incomplete_tail=True, ruleset_version=3)
        actor = state.current_player()
        actions, root_reports = [], []
        for root, enabled_weight in ((baseline, 0), (candidate, weight)):
            client = Client(root, enabled_weight)
            try:
                policy = RemotePolicy(client, tier)
                policy.rng = random.Random(seed_for(f'replay-action-{tier}', index))
                actions.append(policy.select_pattern(state, actor))
                root_reports.append(policy.decisions[-1])
            finally:
                client.close()
        styles = []
        policies = [make_strategy(t) for t in range(3)]
        memo, value_memo = {}, {}
        for style in range(3):
            values = [[], []]
            for sample in range(32):
                world = determinize(state, actor, random.Random(seed_for('replay-world', index, sample)))
                for branch, action in enumerate(actions):
                    sim = clone_state_for_search(world)
                    if not _apply_action(sim, actor, action):
                        raise ValueError('illegal replay root action')
                    values[branch].append(frozen_playout(sim, actor, style, policies, memo, value_memo))
            styles.append({'companion': style, 'old_values': values[0], 'new_values': values[1]})
        rows.append({'prefix': index, 'player': actor, 'roots': root_reports, 'styles': styles})
        print(f'replay-{tier}-w{weight}: prefix {index} complete', flush=True)
    return {'tier': tier, 'weight': weight, 'fixture_ruleset': data.get('ruleset_version', 2),
            'ruleset_projection': 3, 'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
            'completed_branches': len(rows)*3*32*2, 'positions': rows, 'passed': len(rows) == 6}


def promotion_passed(reports, clock, regression, replay, quality, tier):
    team, mixed, full = reports
    return (team['pairs'] == mixed['pairs'] == 240 and full['pairs'] == 48
            and team['gain_confidence_95'][0] > 0 and mixed['gain_confidence_95'][0] > 0
            and len(mixed['by_companion']) == 3
            and all(r['mean_paired_gain'] >= 0 for r in mixed['by_companion'].values())
            and full['match_win_confidence_95'][0] > .5
            and all(r['budget_gate_passed'] for r in reports)
            and all(row['strict_replay_passed'] for report in reports for row in report['observations'])
            and sum(row['tier'] == tier for row in clock['records']) == 21
            and all(row['budget_passed'] for row in clock['records'] if row['tier'] == tier)
            and regression['passed'] and replay['passed'] and replay['completed_branches'] == 1152
            and quality['passed'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-root', type=Path, default=Path('/tmp/guandan-urgent-v12-baseline'))
    parser.add_argument('--folder', type=Path, default=ROOT/'benchmarks/urgent-blocking-v12')
    parser.add_argument('--stage', choices=('freeze', 'clock', 'dev', 'validation', 'full', 'regression', 'replay', 'report', 'all'), required=True)
    args = parser.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    candidate = freeze_candidate(args.folder)
    baseline_manifest = json.loads((args.baseline_root/'snapshot-manifest.json').read_text())
    if snapshot_fingerprint(args.baseline_root) != baseline_manifest['source_sha256']:
        raise ValueError('frozen baseline changed')
    recipe = {'namespace': NAMESPACE, 'counts': COUNTS, 'weights': list(WEIGHTS), 'mode': 'clock', 'workers': 1,
              'baseline_root': str(args.baseline_root.resolve()), 'candidate_root': str(candidate.resolve()),
              'baseline_sha256': snapshot_fingerprint(args.baseline_root), 'candidate_sha256': snapshot_fingerprint(candidate),
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('ai_urgent_worker.py').read_bytes()).hexdigest(),
              'selection': 'largest minimum positive team/mixed development gain; timing must pass',
              'promotion': 'team/mixed 95% paired lower bounds >0; all companions >=0; full lower bound >50%; replay/clock/quality pass'}
    lineage = evaluation_manifest(ROOT, recipe)
    recipe['evaluation_manifest_sha256'] = manifest_fingerprint(lineage)
    lineage_path = args.folder/'evaluation-manifest.json'
    if lineage_path.exists() and json.loads(lineage_path.read_text()) != lineage:
        raise ValueError('evaluation dependencies changed; use a new experiment folder')
    recipe_path = args.folder/'recipe.json'
    if recipe_path.exists() and json.loads(recipe_path.read_text()) != recipe:
        raise ValueError('recipe changed; do not reuse this experiment')
    recipe_path.write_text(json.dumps(recipe, indent=2)+'\n')
    lineage_path.write_text(json.dumps(lineage, indent=2)+'\n')
    stages = ('regression', 'clock', 'dev', 'validation', 'full', 'replay', 'report') if args.stage == 'all' else (args.stage,)
    for stage in stages:
        if stage == 'freeze':
            print(json.dumps(recipe, indent=2))
        elif stage == 'regression':
            rows = []
            clients = [Client(args.baseline_root, 0), Client(candidate, 0)]
            try:
                for index, (name, state) in enumerate(diagnostics.positions()):
                    for tier in range(5):
                        outputs = []
                        for client in clients:
                            request = public_request(state, state.current_player(), 3)
                            request.update(difficulty=tier, mode='fixed', fixed_iterations=256 if tier == 3 else 768,
                                           rng_state=random.Random(68000+index).getstate())
                            outputs.append(client.query(request))
                        passed = all(outputs[0][k] == outputs[1][k] for k in ('pattern', 'reason', 'rng_state'))
                        rows.append({'case': name, 'tier': tier, 'passed': passed, 'outputs': outputs})
            finally:
                for client in clients:
                    client.close()
            (args.folder/'off-regression.json').write_text(json.dumps({**recipe, 'passed': all(r['passed'] for r in rows), 'records': rows}, indent=2)+'\n')
        elif stage == 'clock':
            for weight in WEIGHTS:
                clock = clock_check(candidate, weight)
                (args.folder/f'clock-w{weight}.json').write_text(json.dumps({**recipe, **clock}, indent=2)+'\n')
                print(f'clock-w{weight}: passed={clock["passed"]}', flush=True)
        elif stage == 'dev':
            selected = {}
            for tier in (3, 4):
                choices = []
                for weight in WEIGHTS:
                    reports = [run_trial({**recipe, 'difficulty': tier, 'weight': weight, 'suite': suite}, args.folder)
                               for suite in ('dev-team', 'dev-mixed')]
                    clock = json.loads((args.folder/f'clock-w{weight}.json').read_text())
                    if any(clock[k] != v for k, v in recipe.items()):
                        raise ValueError('clock recipe/source differs')
                    passed = development_passed(*reports, clock, tier)
                    choices.append({'weight': weight, 'development_passed': passed,
                                    'score': min(r['mean_paired_gain'] for r in reports)})
                selected[str(tier)] = max([c for c in choices if c['development_passed']] or choices, key=lambda c: c['score'])
            (args.folder/'validation-lock.json').write_text(json.dumps({**recipe, 'selected': selected}, indent=2)+'\n')
        elif stage in ('validation', 'full'):
            lock = json.loads((args.folder/'validation-lock.json').read_text())
            if any(lock[k] != v for k, v in recipe.items()):
                raise ValueError('locked recipe differs')
            for tier in (3, 4):
                item = lock['selected'][str(tier)]
                if not item['development_passed']:
                    print(f'tier {tier}: skipped {stage}; development failed', flush=True)
                    continue
                for suite in ('holdout', 'mixed') if stage == 'validation' else ('full',):
                    run_trial({**recipe, 'difficulty': tier, 'weight': item['weight'], 'suite': suite}, args.folder)
        elif stage == 'replay':
            lock = json.loads((args.folder/'validation-lock.json').read_text())
            for tier in (3, 4):
                weight = lock['selected'][str(tier)]['weight']
                replay = replay_check(args.baseline_root, candidate, tier, weight)
                (args.folder/f'replay-{tier}.json').write_text(json.dumps({**recipe, **replay}, indent=2)+'\n')
        elif stage == 'report':
            lock = json.loads((args.folder/'validation-lock.json').read_text())
            if any(lock[k] != v for k, v in recipe.items()):
                raise ValueError('locked recipe differs')
            records = []
            for tier in (3, 4):
                item = lock['selected'][str(tier)]
                eligible = False
                if item['development_passed']:
                    reports = [json.loads((args.folder/f'{suite}-{tier}-w{item["weight"]}.json').read_text()) for suite in ('holdout', 'mixed', 'full')]
                    for suite, report in zip(('holdout', 'mixed', 'full'), reports):
                        expected = {**recipe, 'difficulty': tier, 'weight': item['weight'], 'suite': suite}
                        if report['config'] != expected:
                            raise ValueError('acceptance recipe/source differs')
                        validate_pairs(report['observations'], [seed_for(f'{suite}-{tier}', i) for i in range(COUNTS[suite])])
                    clock = json.loads((args.folder/f'clock-w{item["weight"]}.json').read_text())
                    replay = json.loads((args.folder/f'replay-{tier}.json').read_text())
                    regression = json.loads((args.folder/'off-regression.json').read_text())
                    quality = json.loads((args.folder/'quality.json').read_text())
                    if any(report[k] != v for report in (clock, replay, regression, quality) for k, v in recipe.items()):
                        raise ValueError('supporting check recipe/source differs')
                    eligible = promotion_passed(reports, clock, regression, replay, quality, tier)
                records.append({'tier': tier, **item, 'eligible_for_default': eligible,
                                'independent_acceptance': 'completed' if item['development_passed'] else 'not_run_development_failed'})
            (args.folder/'validation.json').write_text(json.dumps({**recipe, 'tiers': records}, indent=2)+'\n')
            print(json.dumps(records, indent=2), flush=True)


if __name__ == '__main__':
    main()
