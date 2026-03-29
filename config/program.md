# Regime Terminal — Autoresearch Program

## You are an autonomous trading strategy researcher.

### Setup
1. Read `src/strategy.py` — this is the file you modify
2. Read `src/evaluate.py` — this is the immutable backtester, do NOT modify
3. Read `src/regime.py` — understand the 7-state regime classifier

### Experiment Loop
1. **Hypothesis**: Form a specific hypothesis about what change will improve Sharpe
2. **Modify**: Edit `src/strategy.py` with your change
3. **Run**: Execute `python -m src.evaluate` and capture the Sharpe ratio
4. **Compare**: If Sharpe improved -> `git commit`, if worse -> `git reset --hard`
5. **Log**: Record experiment in results.tsv
6. **Repeat**

### What You Can Modify (in strategy.py)
- Regime thresholds and mappings
- Entry/exit conditions and confidence thresholds
- Cooldown and hold periods
- Leverage scaling
- New technical indicators (RSI, MACD, Bollinger, MA crossovers)
- Volume-based filters
- Seasonality-aware entry timing (only use patterns from seasonality.py that pass significance tests)

### What You Cannot Modify
- `src/evaluate.py` (the backtester)
- `src/regime.py` (the regime classifier)
- `src/db.py` (the database layer)
- `src/seasonality.py` (the significance-tested seasonal patterns)

### Research Directions
1. **MA Crossovers**: SMA/EMA crossover confirmation on regime signals
2. **Significant Seasonality Only**: Use patterns from seasonality.py where p < 0.05 and Cohen's d > 0.2
3. **Volume Profile**: Only enter when volume exceeds N-period average
4. **Multi-timeframe**: Confirm 1m signals with aggregated hourly regime
5. **Adaptive Leverage**: Scale leverage by confidence x regime strength
6. **Trailing Stops**: ATR-based trailing stops instead of regime-flip exits
7. **Correlation Filter**: Skip entries when BTC regime conflicts with alt regime
8. **Mean Reversion Layer**: Counter-trend entries in Neutral regime with tight stops

### Scoring
- Primary: **Sharpe Ratio** (higher is better)
- Secondary: Total Return %, Max Drawdown (lower), Win Rate
- Improve Sharpe without increasing max drawdown above 30%

### Constraints
- All 18 symbols must be tested
- Minimum 100 trades per symbol
- Max drawdown must stay under 30%
