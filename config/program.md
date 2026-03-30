# Regime Terminal — Autoresearch Program

## You are an autonomous trading strategy researcher.

### DATA SPLIT (CRITICAL — DO NOT VIOLATE)

```
TRAIN:  Mar 2024 → Jul 31 2025  (~16 months, ~690K candles/symbol)
TEST:   Aug 1 2025 → Mar 2026   (~8 months, ~345K candles/symbol)
```

- You optimize ONLY on TRAIN data. The `backtest()` function enforces this.
- You NEVER look at TEST data during optimization.
- After each experiment, `full_report()` runs both — but your keep/discard decision uses TRAIN Sharpe only.
- TEST results are logged for human review to detect overfitting.
- If train Sharpe improves but test Sharpe decays >50%, flag it as potential overfit.

### Setup
1. Read `src/strategy.py` — this is the file you modify
2. Read `src/evaluate.py` — immutable backtester with enforced train/test split
3. Read `src/regime.py` — 7-state regime classifier
4. Run baseline: `python -m src.evaluate` to get starting Sharpe

### Experiment Loop
1. **Hypothesis**: Form a specific, testable hypothesis
2. **Modify**: Edit `src/strategy.py` only
3. **Run**: `python -m src.evaluate > run.log 2>&1`
4. **Read**: `grep "TRAIN SCORE" run.log` for the Sharpe
5. **Decide**: If TRAIN Sharpe improved → `git add -A && git commit -m "exp: <description> sharpe=<value>"`
6. **Revert if worse**: `git checkout -- src/strategy.py`
7. **Log**: Append to results.tsv: `exp_id | description | train_sharpe | test_sharpe | kept/discarded`
8. **Repeat**

### What You Can Modify (strategy.py ONLY)
- Regime thresholds and mappings
- Entry/exit conditions and confidence thresholds
- Cooldown and hold periods
- Leverage scaling
- New technical indicators (RSI, MACD, Bollinger, MA crossovers)
- Volume-based filters
- Seasonality-aware entry timing (only patterns from seasonality.py that pass significance tests)

### What You Cannot Modify
- `src/evaluate.py` — the backtester and split boundary
- `src/regime.py` — the regime classifier
- `src/seasonality.py` — significance-tested seasonal patterns
- `src/db.py` — the database layer
- Any data in the database

### Research Directions (ordered by expected impact)
1. **MA Crossovers**: 50/200 or 20/50 EMA crossover as entry confirmation
2. **Volume Spike Filter**: Only enter when volume > 2x 20-period average
3. **Adaptive Leverage**: Scale leverage = base_leverage * confidence * (1 - recent_volatility)
4. **Trailing Stops**: ATR-based trailing stop instead of regime-flip-only exits
5. **Multi-regime Confirmation**: Require regime to persist N bars before entry
6. **Correlation Filter**: Skip altcoin entries when BTC regime contradicts
7. **Significant Seasonality**: Use only patterns from seasonality.py where p < 0.05 and |d| > 0.2
8. **Mean Reversion in Neutral**: Counter-trend scalps when regime = 3 with tight stops

### Scoring
- Primary: **TRAIN Sharpe Ratio** (higher is better) — this is your val_bpb
- Secondary: Total Return, Max Drawdown (<30%), Win Rate
- Monitor: TEST Sharpe for overfit detection (logged, not used for decisions)

### Constraints
- All 18 symbols must be tested (cross-symbol robustness)
- Minimum 50 trades per symbol on TRAIN data
- Max drawdown must stay under 30% on TRAIN
- If TEST sharpe decays >50% vs TRAIN, flag and investigate before keeping
