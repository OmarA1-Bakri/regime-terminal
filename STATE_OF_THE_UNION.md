# REGIME TERMINAL — STATE OF THE UNION
## Complete Handoff Document
### Last Updated: 3 April 2026

---

## 1. WHAT THIS IS

Autonomous crypto trading system. Gaussian HMM classifies market regimes across 3 timeframes. Volume Profile / Point of Control confirms institutional positioning. Claude Opus operates as portfolio manager. Dual validation layer (rules engine + risk manager) gates every trade.

Budget: GBP 1,000. 30% cash buffer. Up to 30% per STRONG signal with leverage.

---

## 2. WHAT WORKS RIGHT NOW

### Data
- **18,682,811 candles** in Neon PostgreSQL (1-minute OHLCV)
- **18 symbols:** BTC, ETH, SOL, TAO, BNB, XRP, DOGE, ADA, AVAX, DOT, LINK, RENDER, FET, NEAR, AR, INJ, SUI, PENDLE
- **Materialized views:** candles_1h (311K rows), candles_4h (77K rows)
- **Tables:** positions, allocations, trade_log (empty, ready for live trading)

### HMM Regime Classifier
- Real `hmmlearn.GaussianHMM` with Baum-Welch training, Viterbi inference
- 3 features: log returns, realised volatility, volume ratio (14-bar window)
- 7 states: Strong Bull, Bull, Weak Bull, Neutral, Weak Bear, Bear, Crash
- 3 separate models: 1m (execution timing), 1h (confirmation), **4h (trading decisions)**
- Trains at Railway startup on 50K recent candles per timeframe

### Volume Profile / Point of Control
- POC: price with highest traded volume
- VAH/VAL: 70% volume range (Value Area)
- HVN/LVN: support/resistance and breakout zones
- POC shift detection: rising = institutional accumulation, falling = distribution
- **Combined with HMM:** regime says WHAT state, POC says WHERE in price structure

### ATR Module
- 14-period Average True Range on 4h candles
- Dynamic stop losses by symbol tier (2x/2.5x/3x ATR)
- Trailing stops (2x ATR below highest price)
- Pre-calculated stop levels via API

### Dual Validation
- **Layer 1 (Rules Engine):** Python, instant, free. Checks: POC signal gating, symbol tier, ATR stop, position limits, drawdown limits, kill switch.
- **Layer 2 (Risk Manager):** Claude Opus, ~2s. Checks: thesis coherence, correlation, timing, recent history.
- Both must pass before any trade executes.

### Railway Deployment
- **URL:** https://regime-terminal-production-b43b.up.railway.app
- **API v3.0.0** with 25+ endpoints
- Auto-deploys on push to main
- Env vars: NEON_URI, DRY_RUN=true, USE_TESTNET=true, testnet keys set
- **Missing:** ANTHROPIC_API_KEY, real BINANCE_API_KEY, KRAKEN keys, TELEGRAM token

---

## 3. BACKTEST RESULTS

All backtests: Aug 2025 to Mar 2026 (out-of-sample). HMM trained on TRAIN data only. Binance taker fees (0.1%) + slippage (0.03-0.3%) included.

### v1: HMM Only (flat 5% sizing, no leverage)

| Metric | Value |
|--------|-------|
| Avg return | -0.35% |
| Total P&L | -$63.64 |
| Avg win rate | 41.2% |
| Worst drawdown | -3.67% |
| Winners | 6/18 |
| Trading costs | $41.61 |

### v1.5: HMM + POC Filter (flat 5%, no leverage)

Added POC confirmation. Rejected 47% of HMM signals as low quality.

| Metric | Value |
|--------|-------|
| Avg return | -0.10% |
| Total P&L | -$18.45 |
| Trades | 280 (down from 423) |
| Worst drawdown | -2.14% |
| Winners | 6/18 |

POC signal quality: STRONG=60% WR, MEDIUM=37.5% WR, MARGINAL=23% WR.

### v2: All Improvements (flat 5%, no leverage)

Added: kill MARGINAL signals, short selling, ATR stops, symbol tiers, trailing stops.

| Metric | Value |
|--------|-------|
| Avg return | +0.29% |
| Total P&L | +$52.89 |
| Avg win rate | 56.2% |
| Worst drawdown | -1.22% |
| Winners | 14/18 |
| Trades | 545 (332 long, 213 short) |

### v2 Aggressive: Proper Sizing + Leverage

STRONG=10%, MEDIUM=5%. Leverage: Tier A STRONG=3x, MEDIUM=2x. 50% max deployment.

| Metric | Value |
|--------|-------|
| Avg return | +0.83% |
| Total P&L | +$149.94 |
| Winners | 14/18 |
| Worst drawdown | -3.62% |

### v2 Full Sizing: 30% STRONG + 3x Leverage on Tier A

30% cash buffer. Up to 30% position on STRONG signals. Tested on Tier A only.

| Metric | Value |
|--------|-------|
| Total P&L (Tier A) | +$352.58 |
| Avg return | +7.05% |
| Worst drawdown | -10.64% |

**Tier A breakdown:**

| Symbol | Return | P&L | PF | Trades |
|--------|--------|-----|-----|--------|
| SUI | +18.11% | $181 | 4.64 | 12 |
| FET | +11.25% | $113 | 2.94 | 21 |
| TAO | +4.05% | $41 | 1.51 | 16 |
| BNB | +3.79% | $38 | 2.18 | 50 |
| SOL | -1.95% | -$19 | 0.91 | 82 |

### Key Finding

Buy and hold lost -58% average over the test period. Every version of the strategy massively outperformed. The edge is:
1. Capital preservation during bear regimes
2. Short selling during Bear transitions (v2)
3. POC filtering removes 47-58% of false signals
4. Leverage on high-conviction STRONG signals amplifies winners
5. ATR stops prevent getting knocked out on normal volatility

---

## 4. SYMBOL TIERS

| Tier | Symbols | Sizing | Requirements |
|------|---------|--------|-------------|
| A | FET, SUI, TAO, SOL, BNB | Full (30% STRONG) | HMM + POC signal |
| B | AVAX, LINK, RENDER, NEAR, XRP | Half (15% STRONG) | STRONG POC only + catalyst |
| C | BTC, ETH, ADA, DOGE, DOT, INJ, PENDLE, AR | Quarter (7.5% STRONG) | Specific catalyst + STRONG POC |

---

## 5. SIGNAL RULES

**Long entry:** 4h Bear to Neutral or Neutral to Bull + POC STRONG or MEDIUM.
**Short entry:** 4h Bull to Neutral or Neutral to Bear + inverted POC (distribution at resistance).
**Hard reject:** MARGINAL POC signals never traded. 23% win rate = guaranteed loss.
**Stops:** ATR-based. Tier 1=2x, Tier 2=2.5x, Tier 3=3x ATR(14).
**Trailing:** After +2x ATR profit, trail at 2x ATR below highest price.
**Exit:** Regime reversal triggers. Both timeframes (4h primary, 1h confirm).

Full rules in config/program_signals.md.

---

## 6. REPO STRUCTURE

```
config/
  program_portfolio.md    Investment mandate
  program_signals.md      Entry/exit rules + POC gating + short selling
  program_risk.md         Sizing, ATR stops, tiers, drawdown limits
  program_research.md     8-point pre-trade checklist
  program_tao.md          TAO/Bittensor strategy
  symbols.json            18 trading pairs

src/
  api.py                  FastAPI v3.0.0 (25+ endpoints)
  regime.py               7-state Gaussian HMM (1m, 1h, 4h)
  volume_profile.py       POC, VAH/VAL, HVN/LVN, POC shift
  atr.py                  ATR + dynamic stop levels
  validator.py            Dual validation (rules engine + Opus)
  portfolio.py            Position CRUD, P&L, allocations
  paper_trade.py          Binance testnet
  evaluate.py             Backtester
  strategy.py             Agent-modifiable strategy
  seasonality.py          Significance-tested patterns
  db.py                   Neon connection

scripts/
  autoresearch.py         Strategy optimizer (Sonnet mutations)

bittensor/
  tao_deploy.py           TAO staking (skeleton)

Dockerfile               Railway build
railway.json             Railway config
requirements.txt         All dependencies
```

---

## 7. WHAT NEEDS BUILDING

| Priority | Task | Status |
|----------|------|--------|
| 1 | scripts/operator.py — autonomous 15-min loop | NOT BUILT |
| 2 | src/exchange.py — unified Kraken + Binance | NOT BUILT |
| 3 | Telegram bot for alerts | NOT BUILT |
| 4 | Expand autoresearch to all instruction files | NOT BUILT |
| 5 | TAO monitoring + staking execution | SKELETON |
| 6 | TradingView webhook + Pine Script | NOT BUILT |
| 7 | Funding rate arbitrage (when book hits GBP 3-5K) | NOT BUILT |

---

## 8. KNOWN ISSUES

1. Binance geo-blocks Railway IPs (HTTP 451). Testnet only works from desktop.
2. Materialized views need REFRESH MATERIALIZED VIEW after syncs.
3. Daily sync only covers BTC. All 18 symbols should sync.
4. No ANTHROPIC_API_KEY on Railway.
5. Binance real account KYC in progress.
6. Kraken API keys not generated.
7. SOL overtrades (82 trades in backtest). Needs throttling or higher entry bar.
8. HMM trains on BTC only at startup. Per-symbol training would be more accurate.

---

## 9. ENVIRONMENT

**Railway:** regime-terminal-production-b43b.up.railway.app (auto-deploy from main)
**Neon:** NEON_URI in Railway env vars
**GitHub:** github.com/OmarA1-Bakri/regime-terminal
**Testnet:** Binance testnet keys set, 462 test assets, desktop only

---

## 10. FOR CLAUDE CODE

Read ALL config/program_*.md files. They are your operating manual.
Use the API at the Railway URL.
Follow the decision process in program_portfolio.md.
Validate every trade through src/validator.py.
Log every decision with a thesis.
Never trade MARGINAL POC signals.
Focus on Tier A symbols (FET, SUI, TAO, SOL, BNB).
Shorts are not optional — bear markets are half the opportunity set.
