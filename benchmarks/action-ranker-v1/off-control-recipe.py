import json, sys
from pathlib import Path
from scripts.ai_team_trial import pair, source_fingerprint
from scripts.fit_action_ranker import derived_seed, label_recipe

root = Path('/private/tmp/guandan-action-ranker-v1-baseline')
tier = int(sys.argv[1])
rows = []
for suite in ('dev', 'mixed'):
    config = {'baseline_root': str(root), 'baseline_sha': label_recipe(root)['baseline_sha256'], 'suite': suite, 'variant': 'corrected', 'difficulty': tier, 'mode': 'fixed', 'fixed_iterations': 128, 'match_states': True}
    seed = derived_seed(f'off-control-{suite}-{tier}', 0)
    legs = pair((17, seed, config))
    same = legs[0]['result']['finish_order'] == legs[1]['result']['finish_order']
    zero = abs(sum(leg['gain'] for leg in legs)/2) < 1e-12
    assert same and zero, (suite, tier, legs)
    rows.append({'suite': suite, 'config': config, 'seed': seed, 'same_complete_ranking': same, 'paired_gain': sum(leg['gain'] for leg in legs)/2, 'observations': legs})
    print(f'tier {tier}/{suite}: disabled model control gain = 0; exact completed ranks match', flush=True)
report = {'tier': tier, 'source_sha256': source_fingerprint(), 'cases': rows, 'interpretation': 'Quality control only; one predeclared asymmetric third-A state per suite. No strength claim and no development/acceptance seeds used.'}
Path(f'benchmarks/action-ranker-v1/off-control-{tier}.json').write_text(json.dumps(report, indent=2)+'\n')
