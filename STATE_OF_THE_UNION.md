# REGIME TERMINAL — STATE OF THE UNION
## Handoff Document for Claude Code
### Date: 1 April 2026

---

## 1. WHAT THIS SYSTEM IS

Regime Terminal is an autonomous crypto trading system. It uses a Gaussian Hidden Markov Model to classify market regimes across multiple timeframes, then makes trading decisions based on regime transitions. Claude Opus operates as the portfolio manager — reading market state via API, forming theses, validating trades through a dual-layer system, and executing via exchange APIs.

The system is designed to be fully autonomous once deployed. Omar (the owner) sets the strategy parameters and capital allocation. Claude operates the book.

---

## 2. WHAT EXISTS AND WORKS RIGHT NOW

### 2.1 Data — Neon PostgreSQL

**18,681,371 candles** of 1-minute OHLCV data across 18 symbols, covering approximately 2 years (Mar 2024 — Mar 2026).

**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, AVAXUSDT, DOTUSDT, LINKUSDT, TAOUSDT, RENDERUSDT, FETUSDT, NEARUSDT, ARUSDT, INJUSDT, SUIUSDT, PENDLEUSDT

**Tables:**
- `candles` — 18.68M rows, 1-minute OHLCV + regime + confidence
- `candles_1h` — materialized view, 311,384 rows (aggregated hourly)
- `candles_4h` — materialized view, 77,863 rows (aggregated 4-hourly)
- `positions` — open/closed positions with entry/exit prices, P&L, strategy tags (currently empty)
- `allocations` — target allocation per strategy (regime=60%, tao=30%, manual=10%)
- `trade_log` — every trade action with metadata and reasoning (currently empty)

**Connection:** NEON_URI is set as a Railway environment variable. Do NOT hardcode it.

### 2.2 Regime Classifier — Real Gaussian HMM

**File:** `src/regime.py`

This is a genuine Hidden Markov Model using `hmmlearn.GaussianHMM`. It is NOT a deterministic scorer (the old version was replaced on 1 Apr 2026).

**How it works:**
- Features: log returns, realised volatility, volume ratio (computed over a 14-bar window)
- StandardScaler normalizes features before training (critical for convergence)
- Baum-Welch algorithm learns transition and emission parameters from data
- Viterbi algorithm infers the most likely state sequence
- Posterior probabilities provide genuine probabilistic confidence
- Covariance type: diagonal (more stable than full for this data)

**Three separate models trained, one per timeframe:**

| Timeframe | Purpose | Training Data | Model File |
|-----------|---------|---------------|------------|
| 1m | Execution timing (noisy, fast) | 50K recent 1-min candles | models/hmm_regime_1m.pkl |
| 1h | Signal confirmation | 17K recent 1-hr candles | models/hmm_regime_1h.pkl |
| **4h** | **Primary trading decisions** | **4K recent 4-hr candles** | **models/hmm_regime_4h.pkl** |

**7 states, ordered by mean return after training:**
- 0: Strong Bull
- 1: Bull
- 2: Weak Bull
- 3: Neutral
- 4: Weak Bear
- 5: Bear
- 6: Crash

**Key learned properties (from BTC training):**
- Bull regimes are sticky (~71-93% self-transition probability)
- Bear regimes are very sticky (~94% self-transition)
- Crash regimes often V-bottom into Bull (~35% Crash to Bull)
- Neutral resolves bullish more often than bearish (~16% Neutral to Strong Bull)

**HMM trains at Railway startup** on 50K recent BTC candles per timeframe. Takes ~30 seconds. Falls back to deterministic scorer if training fails.

### 2.3 Railway Deployment — LIVE

**URL:** https://regime-terminal-production-b43b.up.railway.app
**Project:** Trading
**Auto-deploy:** Every push to main branch triggers rebuild + deploy

**Environment variables set on Railway:**
- NEON_URI (database connection)
- DRY_RUN=true
- USE_TESTNET=true
- BINANCE_TESTNET_KEY (set)
- BINANCE_TESTNET_SECRET (set)

**Environment variables NOT yet set (needed for full operation):**
- ANTHROPIC_API_KEY (needed for operator.py and risk manager)
- BINANCE_API_KEY (real account — Omar setting up)
- BINANCE_API_SECRET
- KRAKEN_API_KEY (not yet generated)
- KRAKEN_API_SECRET
- TELEGRAM_BOT_TOKEN (not yet created)

### 2.4 Live API Endpoints (Verified Working)

| Endpoint | Method | Status | What it returns |
|----------|--------|--------|-----------------|
| /health | GET | WORKS | System status, candle counts, HMM model status |
| /regimes?timeframe=4h | GET | WORKS | All 18 symbols with HMM regime + confidence (default 4h) |
| /regimes?timeframe=1h | GET | WORKS | Same, 1-hour timeframe |
| /regimes?timeframe=1m | GET | WORKS | Same, 1-minute timeframe |
| /regimes/multi/{symbol} | GET | WORKS | All 3 timeframes for one symbol |
| /regimes/transitions?timeframe=4h | GET | WORKS | 7x7 learned transition probability matrix |
| /regimes/states?timeframe=4h | GET | WORKS | Mean return/vol/volume per state |
| /regimes/{symbol} | GET | WORKS | Raw candle data + stored regime for a symbol |
| /split | GET | WORKS | Train/test split boundary (Aug 1 2025) |
| /symbols | GET | WORKS | 18 configured trading pairs |
| /train | POST | WORKS | Retrain HMM on demand |
| /sync/{symbol} | POST | WORKS | Fetch latest candles from Binance |
| /portfolio | GET | WORKS | Open positions (currently empty) |
| /portfolio/open | POST | WORKS | Open a new position |
| /portfolio/close/{id} | POST | WORKS | Close a position |
| /portfolio/pnl | GET | WORKS | Realised PnL summary |
| /portfolio/allocations | GET | WORKS | Target vs actual allocation per strategy |
| /portfolio/history | GET | WORKS | Trade log |
| /testnet/portfolio | GET | BLOCKED | HTTP 451 from Railway (Binance geo-blocks cloud IPs) |
| /testnet/balance/{asset} | GET | BLOCKED | Same geo-block |
| /testnet/execute/{symbol} | POST | BLOCKED | Same geo-block |
| /testnet/trades | GET | WORKS | Trade log (works, currently empty) |
| /testnet/price/{symbol} | GET | BLOCKED | Same geo-block |

### 2.5 Binance Testnet — Verified Working (Desktop Only)

**Test assets:** 462 assets (BTC 1.0, ETH 1.0, USDT 10K, TAO 2.0, etc.)
**Launcher:** C:\Users\albak\Desktop\regime-terminal\run_testnet.bat
**Status:** Connected and verified from desktop. Does NOT work from Railway cloud IPs.

### 2.6 GitHub Repository

**URL:** https://github.com/OmarA1-Bakri/regime-terminal
**Branch:** main (auto-deploys to Railway)

**Files:**

```
config/
  program.md              — Autoresearch agent instructions (original)
  program_portfolio.md    — Investment mandate for Claude
  program_signals.md      — Regime transition to action mapping
  program_risk.md         — Risk management rules, drawdown limits, kill switch
  program_research.md     — 8-point research checklist
  program_tao.md          — TAO strategy, subnet allocations, catalysts
  symbols.json            — 18 trading pair configuration

src/
  api.py                  — FastAPI (multi-timeframe HMM, portfolio, testnet)
  db.py                   — Neon PostgreSQL connection
  evaluate.py             — Backtester with train/test split
  paper_trade.py          — Binance Testnet paper trading
  portfolio.py            — Position CRUD, PnL, allocations
  regime.py               — 7-state Gaussian HMM (1m, 1h, 4h)
  seasonality.py          — Significance-tested seasonal patterns
  strategy.py             — Agent-modifiable strategy
  validator.py            — Dual validation (rules engine + Opus risk manager)

scripts/
  autoresearch.py         — Strategy code optimizer

bittensor/
  tao_deploy.py           — TAO subnet staking (skeleton)

Dockerfile, railway.json, requirements.txt
```

### 2.7 Train/Test Split

- TRAIN: Mar 2024 to Jul 31 2025 (~12.4M candles)
- TEST: Aug 1 2025 to Mar 2026 (~6.3M candles)
- Split boundary: SPLIT_MS = 1753833600000

### 2.8 Budget

Starting capital: GBP 1,000
- Regime directional: 60% (GBP 600)
- TAO staking: 30% (GBP 300)
- Cash reserve: 10% (GBP 100)

### 2.9 Current Market State (1 Apr 2026, 4h HMM)

BTC: Bull 0.919 | ETH: Neutral 0.991 | SOL: Neutral 0.989
TAO: Weak Bear 0.797 | BNB: Bear 0.998 | XRP: Bear 0.998

---

## 3. ARCHITECTURE

### Two Processes on Railway

PROCESS 1: operator.py (every 15 min) [NOT YET BUILT]
- Reads regime states, positions, detects transitions
- Calls Claude Opus with instruction files + market state
- Validates via rules engine (Python) then risk manager (Opus)
- Executes if both pass

PROCESS 2: autoresearch.py (daily) [PARTIALLY BUILT]
- Currently only mutates strategy.py
- Needs expansion to review ALL config/program_*.md files
- Read trade_log, review outcomes, improve instructions, commit

### Model Allocation

| Component | Model |
|-----------|-------|
| Operator | Claude Opus |
| Risk manager | Claude Opus |
| Rules engine | Python (no API) |
| Autoresearch | Claude Sonnet |

### Signal Logic (4h Regime Transitions)

| Transition | Action |
|------------|--------|
| Crash to Bear | WATCHLIST only |
| Bear to Neutral | ENTER 50% |
| Neutral to Bull | ENTER remaining 50% |
| Bull to Strong Bull | HOLD, trail stop 20% |
| Bull to Neutral | CLOSE 50% |
| Neutral to Bear | CLOSE 100% |
| Any to Crash | EMERGENCY EXIT |

### Risk Rules

- Per-trade stop: -3% | Leveraged: -2%
- Daily drawdown: -5% stop trading
- Weekly drawdown: -10% close all
- Kill switch: -20% everything closed
- Max positions: 3
- Max leverage: 5x
- Cash reserve: 10% minimum

---

## 4. WHAT NEEDS BUILDING

### Phase 2 (NEXT)
1. scripts/operator.py — autonomous 15-min loop
2. src/exchange.py — unified Kraken + Binance interface
3. Telegram bot for alerts

### Phase 3
4. Expand autoresearch to improve ALL instruction files
5. research_journal table in Neon

### Phase 4
6. TAO monitoring and staking execution
7. Populate TAO Strategy Google Doc

### Phase 5 (Later)
8. TradingView webhook + Pine Script indicator

### Phase 6 (When book hits GBP 3-5K)
9. Funding rate arbitrage scanner + delta-neutral execution

---

## 5. KNOWN ISSUES

1. Binance geo-blocks Railway IPs (HTTP 451). Testnet only works from desktop.
2. Materialized views (candles_1h, candles_4h) need manual REFRESH after syncs.
3. Daily sync only covers BTC. All 18 symbols should sync.
4. No ANTHROPIC_API_KEY on Railway yet.
5. Binance real account not active (KYC in progress).
6. Kraken API keys not generated.
7. No Telegram bot token.
8. HMM trains on BTC only — assumes BTC characteristics apply broadly.
9. Shorts mapped to spot SELL in paper_trade.py (no real futures execution).
10. Security: Desktop .env file has API keys that should be rotated post-compromise.

---

## 6. HOW TO OPERATE (FOR CLAUDE CODE)

Read ALL config/program_*.md files in the repo.
Use the API at https://regime-terminal-production-b43b.up.railway.app
Follow the decision process in config/program_portfolio.md.
Validate every trade through src/validator.py.
Log every decision with a thesis.

### API Examples

GET /regimes?timeframe=4h — primary regime states
GET /regimes/multi/BTCUSDT — all 3 timeframes
GET /portfolio — current positions
POST /portfolio/open — {symbol, side, quantity, entry_price, strategy, thesis, ...}
POST /portfolio/close/{id} — {exit_price, reason}

---

## 7. IMMEDIATE NEXT STEPS

1. Omar: Complete Binance setup (KYC + futures + API keys)
2. Omar: Provide ANTHROPIC_API_KEY for Railway
3. Build: scripts/operator.py
4. Build: src/exchange.py
5. Build: Telegram bot
6. Test: DRY_RUN for 1 week
7. Test: Testnet for 1 week
8. Deploy: Live with GBP 200 initial
9. Expand: Autoresearch for all instruction files
10. Scale: Funding rate arb when book hits GBP 3-5K
