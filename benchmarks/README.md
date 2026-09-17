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

`v0.8.1b2-mixed-20.json` records the reference run for the current code:

- completion: `20/20` (`1.0`)
- average turns: `91.95`
- team wins: East-West `4`, South-North `16`
- average bombs: East-West `0.95`, South-North `1.0`

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
  --compare benchmarks/v0.8.1b2-mixed-20.json current.json \
  --fail-completion-drop 0.05 \
  --fail-turn-increase 20 \
  --fail-bomb-drift 0.5
```

Duration is reported for diagnosis but is not used as a default gate because it
varies with CPU load and MCTS scheduling.

`--fail-bomb-drift` exists because `average_bombs` is the metric that drifted
without any gate noticing: between `v0.8.0b1-mixed-20.json` and the current
baseline the average bomb count moved from `[0.25, 0.45]` to `[0.95, 1.0]`
while completion and average turns stayed flat. Comparing the two checked-in
baselines reproduces that finding:

```bash
python -m guandan.ai.benchmark \
  --compare benchmarks/v0.8.0b1-mixed-20.json benchmarks/v0.8.1b2-mixed-20.json \
  --fail-completion-drop 0.05 --fail-turn-increase 20 --fail-bomb-drift 0.5
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
counts (64 simulations for Professional, 96 for Dai Changsheng). It is intended
for cross-machine regression and exercises the full search-work ceiling.

**Production runs a different search than this mode.** The 240/420ms clock
budget stops production at roughly 40-80 simulations, and the two modes pick
different actions for a substantial share of decisions, so neither mode's win
rate can stand in for the other. Production decisions report this through
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
