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
