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

`v0.8.0b1-mixed-20.json` records the reference run:

- completion: `20/20` (`1.0`)
- average turns: `92.9`
- team wins: East-West `3`, South-North `17`
- average bombs: East-West `0.25`, South-North `0.45`

Compare a new run with:

```bash
python -m guandan.ai.benchmark \
  --compare benchmarks/v0.8.0b1-mixed-20.json current.json \
  --fail-completion-drop 0.05 \
  --fail-turn-increase 20
```

Duration is reported for diagnosis but is not used as a default gate because it
varies with CPU load and MCTS scheduling.

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
for cross-machine regression and exercises the full search-work ceiling; its
latency is deliberately not compared with the bounded production holdout.

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
