# Regime Terminal

Autonomous crypto trading system powered by Hidden Markov Models and Volume Profile analysis. Claude operates as portfolio manager — reading market state, forming theses, validating trades, and executing via exchange APIs.

## How It Works

```
18.7M candles (Neon PostgreSQL)
       |
       v
7-State Gaussian HMM (1m / 1h / 4h)
       |
       v
Volume Profile + Point of Control
       |
       v
Regime Transition Signal
       |
       v
Dual Validation (Rules Engine + Claude Risk Manager)
       |
       v
Exchange Execution (Kraken / Binance)
```

The HMM classifies market state into 7 regimes (Strong Bull to Crash). Regime TRANSITIONS trigger trade signals. Volume Profile confirms whether institutions agree (POC rising = accumulation, POC falling = distribution). Only trades where HMM + POC + research align get executed.

## Backtest Results

Aug 2025 to Mar 2026, out-of-sample, with Binance fees + slippage:

| Version | Total P&L | Avg Return | Worst DD | Winners |
|---------|----------|-----------|----------|--------|
| v1 HMM only | -$63.64 | -0.35% | -3.67% | 6/18 |
| v1.5 + POC filter | -$18.45 | -0.10% | -2.14% | 6/18 |
| v2 all improvements | +$52.89 | +0.29% | -1.22% | 14/18 |
| **v2 aggressive sizing** | **+$149.94** | **+0.83%** | **-3.62%** | **14/18** |
| **v2 + 30% STRONG + leverage** | **+$352.58** | **+7.05%** | **-10.64%** | **4/5 Tier A** |

Buy and hold lost -58% average over the same period. The strategy's edge is capital preservation in bear markets combined with leveraged entries on high-conviction signals.

## Architecture

**Railway** (always on): FastAPI serving regime data, portfolio state, HMM training at startup.

**Oracle VM / Desktop** (Claude Code): Autonomous operator loop every 15 min, reads state from Railway API, makes trading decisions via Claude Opus, validates through dual-layer system, executes.

**Neon PostgreSQL**: 18.7M 1-minute candles, materialized views for 1h and 4h, positions table, trade log.

## Quick Start

```bash
# Clone
git clone https://github.com/OmarA1-Bakri/regime-terminal.git
cd regime-terminal

# Install
pip install -r requirements.txt

# Run locally
export NEON_URI="your_neon_connection_string"
python -m src.api

# Or deploy to Railway (auto-deploys on push to main)
git push origin main
```

## Live API

**Base URL:** https://regime-terminal-production-b43b.up.railway.app

### Regime Classification
```
GET /regimes?timeframe=4h          # All 18 symbols with regime + confidence
GET /regimes?timeframe=1h          # 1-hour confirmation
GET /regimes/multi/BTCUSDT         # All 3 timeframes for one symbol
GET /regimes/transitions           # 7x7 transition probability matrix
GET /regimes/states                # Learned state characteristics
```

### Volume Profile
```
GET /volume-profile/BTCUSDT/analysis   # POC + price position + POC shift
GET /volume-profile/BTCUSDT/poc        # Quick POC / VAH / VAL
```

### ATR (Dynamic Stop Losses)
```
GET /atr/BTCUSDT                   # ATR with stop levels for all tiers
GET /atr                           # ATR for all symbols
```

### Portfolio
```
GET  /portfolio                    # Open positions
POST /portfolio/open               # Open position with thesis
POST /portfolio/close/{id}         # Close with reason
GET  /portfolio/pnl                # Realised P&L
GET  /portfolio/allocations        # Target vs actual
```

### Utility
```
GET  /health                       # System status + HMM model status
GET  /symbols                      # 18 configured pairs
POST /sync/{symbol}                # Fetch latest candles from Binance
POST /train                        # Retrain HMM on demand
```

## Symbol Tiers

From backtest analysis — not all symbols are equal:

| Tier | Symbols | How to Trade |
|------|---------|-------------|
| **A (Proven)** | FET, SUI, TAO, SOL, BNB | All valid HMM + POC signals, full sizing |
| B (Conditional) | AVAX, LINK, RENDER, NEAR, XRP | STRONG POC only + catalyst required |
| C (Research Only) | BTC, ETH, ADA, DOGE, DOT, INJ, PENDLE, AR | Specific catalyst + STRONG POC + full conviction |

## Signal Logic

**Entry (Long):** 4h Bear to Neutral + POC STRONG/MEDIUM = enter. Size by POC strength (STRONG=30%, MEDIUM=15%).

**Entry (Short):** 4h Bull to Neutral + inverted POC (price above VAH, POC falling) = enter short.

**Exit:** ATR-based trailing stops. Regime reversal triggers partial or full close.

**Hard filter:** MARGINAL POC signals (23% win rate) are automatically rejected. No exceptions.

## Key Files

```
config/
  program_portfolio.md    # Investment mandate (Claude reads this)
  program_signals.md      # Entry/exit rules with POC gating
  program_risk.md         # Position sizing, ATR stops, symbol tiers
  program_research.md     # 8-point pre-trade checklist
  program_tao.md          # TAO/Bittensor specific strategy

src/
  api.py                  # FastAPI v3.0.0
  regime.py               # 7-state Gaussian HMM (1m, 1h, 4h)
  volume_profile.py       # POC, Value Area, HVN/LVN, POC shift
  atr.py                  # ATR computation + dynamic stop levels
  validator.py            # Dual validation (rules engine + Opus)
  portfolio.py            # Position CRUD, P&L, allocations
  paper_trade.py          # Binance testnet execution
```

See [STATE_OF_THE_UNION.md](STATE_OF_THE_UNION.md) for the complete handoff document.

## Status

- [x] 18.7M candles in Neon (18 symbols, 2 years)
- [x] Real Gaussian HMM (3 timeframes)
- [x] Volume Profile / POC module
- [x] ATR-based dynamic stops
- [x] Portfolio management API
- [x] Dual validation layer
- [x] Railway deployment (auto-deploy)
- [x] Binance testnet connected
- [x] Full backtest with fees + slippage
- [ ] Operator loop (scripts/operator.py)
- [ ] Exchange abstraction (Kraken + Binance)
- [ ] Telegram alerts
- [ ] TAO staking execution
