# Historical AI measurements (through v0.8.2)

All settings, claims about “current” or “production”, and measurements below refer to the implementation before the revised difficulty ladder. They are retained as experiment records and do not describe the new implementation. See [the new benchmark report](README.md) for current results.

# AI Benchmark Baselines

The checked-in baseline uses the fixed mixed-seat configuration below:

```bash
python -m guandan.ai.benchmark \
  --games 20 \
  --difficulties 0,1,2,3 \
  --seed-start 800 \
  --max-turns 2000 \
  --json
```

## Current baseline

`v0.8.2b2-mixed-20.json` records the reference run for the current code:

- completion: `20/20` (`1.0`)
- average turns: `91.1`
- team wins: East-West `2`, South-North `18`
- average bombs: East-West `0.95`, South-North `1.15`

This benchmark mixes four difficulties across fixed seats (seat 0 novice, seat 1
intermediate, seat 2 advanced, seat 3 professional), so `team_wins` reflects the
seat/difficulty assignment, **not** a fair strength comparison. Use the arena for
strength claims.

Note that only the **fixed-iteration** arena mode is reproducible across
machines; the production clock budget makes simulation counts machine-dependent,
so a benchmark rerun on different hardware can shift `average_turns` and even
`team_wins` without any code change.

## Comparing a new run

```bash
python -m guandan.ai.benchmark \
  --compare benchmarks/v0.8.2b2-mixed-20.json current.json \
  --fail-completion-drop 0.05 \
  --fail-turn-increase 20 \
  --fail-bomb-drift 0.4
```

Duration is reported for diagnosis but is not used as a default gate because it
varies with CPU load and MCTS scheduling.

`--fail-bomb-drift` exists because `average_bombs` is the metric that drifted
without any gate noticing: between `v0.8.0b1-mixed-20.json` and the current
baseline the average bomb count moved from `[0.25, 0.45]` to `[0.95, 1.0]`
while completion and average turns stayed flat.

Measured rerun variance (same machine, same seeds, two consecutive runs):
`completion_rate` and both `average_bombs` values were **identical**, while
`average_turns` moved by 3.6 and `team_wins` by 2. That is why bomb drift gets a
tight threshold and turn drift gets a loose one — the benchmark is not
reproducible for outcomes because production AI runs on a clock budget, but the
bomb statistic is stable enough to gate at ±0.4.

Comparing the two checked-in baselines reproduces the original finding:

```bash
python -m guandan.ai.benchmark \
  --compare benchmarks/v0.8.0b1-mixed-20.json benchmarks/v0.8.1b2-mixed-20.json \
  --fail-completion-drop 0.05 --fail-turn-increase 20 --fail-bomb-drift 0.4
# gate=fail — average_bombs_drift_team0 +0.70 / team1 +0.55
```

The `v0.8.0b1` file is kept as a historical record and is **not** comparable
with current code: it predates the M9 search rewrite.

## Paired strength arena

Use identical deals with the candidate and baseline swapping fixed teams:

```bash
python -m guandan.ai.arena \
  --candidate 4 \
  --baseline 3 \
  --deals 20 \
  --seed-start 5000 \
  --max-p95-seconds 0.50 \
  --json
```

For the release/nightly gate, add `--full-match` to play every paired seed from
level 2 through a successful pass of A.

The arena reports candidate-only decision latency, level margin, a Wilson 95%
confidence interval and an Elo estimate. `ai-v2-style-tuning.json` records the
independent holdout used for the current Dai Changsheng profile.

`--deterministic-search` disables wall-clock cutoffs and uses calibrated fixed
counts (32 root evaluations for Professional, 96 for Dai Changsheng). It is intended
for cross-machine regression and exercises the full search-work ceiling.

**Production uses the same root search with a time limit.** The 240/420ms clock
budget can stop it before the 32/96 fixed ceilings, so neither mode's win rate
can stand in for the other. Production decisions report this through
`SearchResult.budget_limited`. A latency gate must be set above the budget
rather than equal to it, because the deadline is only observed between
simulations.

Profile search is reproducible through:

```bash
python -m guandan.ai.tuning \
  --candidates 6 \
  --screening-deals 3 \
  --finalists 2 \
  --final-deals 10 \
  --output tuning-report.json
```

The tuner uses cost-controlled fixed counts (28/48) so CPU scheduling cannot
change candidate ranking. Selected parameters are then validated with Arena's
full 64/96 work ceilings and the latency-bounded production budgets.

## Action-value baseline

`action-value-baseline-200.json` caches high-precision action labels for 200
reproducible mid/late-game positions. Each of its 1,137 actions has 400 fixed-seed
playouts; the candidate union includes up to six search candidates, legal pass,
and the greedy policy's actual pick. This keeps paired evaluations at `n=200`
instead of silently dropping decisions that search or greedy can make.

`action-value-evaluation-200.json` records the paired `greedy`, `argmax32`,
`search32`, and `search64` run, including per-position regret, method confidence
intervals, paired confidence intervals and t values, and decision/runtime totals.
The root-search optimization adds five reusable experiment files:

- `action-value-evaluation-root-search-200.json`: uniform `flat32` versus failed
  early-elimination `race32/race64` variants;
- `action-value-evaluation-flat-budget-200.json`: the 32/64/96 uniform budget sweep;
- `action-value-evaluation-production-root-200.json`: the exact selected
  Professional/Dai settings, including their 40/48-turn rollout limits;
- `action-value-evaluation-root-ablation-200.json`: rollout-level and prior ablation;
- `action-value-evaluation-root-prior-200.json`: a weak-prior ablation holding
  the rollout cap at 40 turns for direct comparison with `flat96`.

The selected production settings are uniform root allocation, rollout level 1,
32 evaluations for Professional and 96 for Dai Changsheng. `race32/race64` are
kept only as negative results so the aggressive early-elimination experiment is
not repeated.

Additional diagnostics after v0.8.2-beta.1:

- `candidate-recall-audit-12.json`: 12 positions, all legal exact-card actions,
  200 paired novice continuations per action. Current six-action pool contains a
  best labeled action in 9/12 positions; mean pool oracle gap is 0.0096. This is
  exploratory because taking the maximum over many noisy action labels inflates
  the apparent gap.
- `action-value-evaluation-complex-rollout-200.json`: targeted structured
  replies to opponent-led complex tricks have regret 0.0537 versus 0.0487 for
  the production lightweight rollout, with higher latency. The experimental
  policy is not enabled in production.
- `action-value-diverse-24.json`: held-out positions balanced across levels
  2/9/A, four seats and novice/advanced source play, labeled by 100 advanced
  continuations per action. Paired differences between greedy, root32 and root96
  are not statistically resolved at this sample size.
- `root96-vs-root32-arena-8.json`: fixed-iteration paired Arena, eight seeds,
  16 complete rounds; root96 and root32 each win eight.
- `root96-vs-root32-clock-4.json`: production-clock paired Arena, four seeds,
  eight rounds; root96 wins two with a wide 95% Wilson interval (7.1%–59.1%).
  Its decision p95 is 377ms. This is a latency smoke check, not a strength claim.
- `v0.8.2b2-mixed-20.json`: production-clock rerun after the search-clone
  change. Completion, turns, wins and bombs match `v0.8.2b1-mixed-20.json`;
  the existing completion/turn/bomb gate passes.

Reproduce the new diagnostics with the `audit-candidates` and
`evaluate-diverse` commands of `scripts/action_value_baseline.py`. Both accept
seed, sample, playout and worker counts. The diverse run used:

```bash
python scripts/action_value_baseline.py evaluate-diverse \
  --positions 24 --playouts 100 --seed-start 10000 \
  --label-difficulty 2 --workers 8
```

Re-evaluate new methods against the cached labels without rebuilding them:

```bash
python scripts/action_value_baseline.py evaluate \
  --file benchmarks/action-value-baseline-200.json \
  --methods greedy,argmax32,search32,search64 \
  --out benchmarks/action-value-evaluation-200.json
```
